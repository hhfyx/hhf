# -*- coding: utf-8 -*-
"""验收脚本：证明整套 FastAPI 外壳真的按预期工作。

跑法（在 learn/fastapi_basics 下）：

    py -3.11 -X utf8 verify_api.py

分 A–H 八组，每组都对应任务里点名的能力。退出码 0 = 全过；
任一条不过会打印期望值/实际值，并以非 0 退出。

设计原则：**每条断言都要有反证**。比如验证 response_model 过滤，就必须先证明
服务层真的多给了那个键，否则"字段不存在"和"被过滤掉了"看不出区别。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

# 兜底异常处理器要能被验证：TestClient 默认会把服务端异常重抛给测试代码
client = TestClient(app, raise_server_exceptions=False)

# 日志在验证时太吵，静音（但出错时我们断言的是响应体，不依赖日志）
logging.disable(logging.CRITICAL)

PASS = 0
FAIL = 0
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(f"{name}{(' | ' + detail) if detail else ''}")
        print(f"  [FAIL] {name} {detail}")


def eq(name: str, actual, expected) -> None:
    check(name, actual == expected, f"期望={expected!r} 实际={actual!r}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ==================================================================== A 启动与生命周期
def group_a_lifespan() -> None:
    section("A. lifespan：启动加载 / 关闭释放")
    with TestClient(app) as c:
        # 1) 启动后资源可用
        r = c.get("/api/v1/health")
        eq("A1 /health 状态码", r.status_code, 200)
        body = r.json()
        eq("A1 /health status", body["status"], "ok")
        check("A2 resources 里有 lifespan 加载的 registry", body["resources"]["rule_groups"] >= 1,
              f"resources={body['resources']}")
        eq("A2 registry 未关闭", body["resources"]["closed"], False)
        check("A3 uptime_s 是数字", isinstance(body["uptime_s"], (int, float)), f"type={type(body['uptime_s'])}")
        # 2) yield 的字典进了 request.state（而不是 app.state）
        check("A4 request.state 拿得到 registry", app.state.registry is not None)

    # 3) 关闭后资源被释放
    eq("A5 关闭后 registry.closed", app.state.registry, None)


# ==================================================================== B 路由与参数
def group_b_routing() -> None:
    section("B. 路由与参数：前缀 / 路径 / 查询 / Body")
    with TestClient(app) as c:
        # prefix
        r = c.get("/api/v1/health")
        eq("B1 prefix /api/v1 生效", r.status_code, 200)
        eq("B2 去掉 prefix 就 404", c.get("/health").status_code, 404)

        # 路径参数
        r = c.get("/api/v1/documents/doc-001")
        eq("B3 路径参数命中", r.status_code, 200)
        eq("B3 返回的 doc_id", r.json()["doc_id"], "doc-001")

        # 查询参数默认值
        p = r.json()["pagination"]
        eq("B4 默认 page", p["page"], 1)
        eq("B4 默认 size", p["size"], 10)
        eq("B4 offset 推导", p["offset"], 0)

        # 查询参数显式传值
        r = c.get("/api/v1/documents/doc-001?page=2&size=1")
        body = r.json()
        eq("B5 page=2&size=1 offset", body["pagination"]["offset"], 1)
        eq("B5 真的只返回 1 条", len(body["items"]), 1)
        eq("B5 第 2 条 page 值", body["items"][0]["page"], 2)

        # 查询参数约束：size 上限 100
        r = c.get("/api/v1/documents/doc-001?size=999")
        eq("B6 size 越界 422", r.status_code, 422)
        eq("B6 错误码统一", r.json()["code"], "INVALID_INPUT")

        # pattern 约束
        r = c.get("/api/v1/documents/doc-001?sort=up")
        eq("B7 sort 不合法 422", r.status_code, 422)

        # 路径参数 404（AppError 路径）
        r = c.get("/api/v1/documents/doc-999")
        eq("B8 不存在的文档 404", r.status_code, 404)
        eq("B8 统一错误体 code", r.json()["code"], "NOT_FOUND")
        check("B8 message 带上了 doc id", "doc-999" in r.json()["message"], r.json()["message"])

        # 嵌套路径参数
        r = c.get("/api/v1/documents/doc-001/fields/invoice_no")
        eq("B9 嵌套路径 200", r.status_code, 200)
        eq("B9 抽到发票号", r.json()["value"], "INV-2026-0042")


# ==================================================================== C Body + response_model
def group_c_body() -> None:
    section("C. Body：模型校验 + response_model 出参过滤")
    payload = {
        "doc_id": "doc-001",
        "text": "发票号：INV-2026-0042 合计金额：1,280.50 开票日期：2026-10-20",
        "rules": [
            {"name": "invoice_no", "type": "str", "required": True},
            {"name": "total_amount", "type": "float", "required": True},
            {"name": "invoice_date", "type": "date", "required": True},
        ],
    }
    with TestClient(app) as c:
        r = c.post("/api/v1/extract", json=payload)
        eq("C1 /extract 200", r.status_code, 200)
        body = r.json()
        eq("C1 invoice_no", body["fields"]["invoice_no"], "INV-2026-0042")
        eq("C1 total_amount 转 float", body["fields"]["total_amount"], 1280.5)
        eq("C1 invoice_date 转 date 字符串", body["fields"]["invoice_date"], "2026-10-20")
        eq("C1 missing 为空", body["missing"], [])
        check("C1 confidence 在 0-1", 0.0 <= body["confidence"] <= 1.0, f"confidence={body['confidence']}")
        eq("C1 model 版本来自配置", body["model"], get_settings().extract_model)

        # extra="forbid"：多传字段 → 422
        bad = dict(payload, typo_field="x")
        r = c.post("/api/v1/extract", json=bad)
        eq("C2 多传字段 422（extra=forbid）", r.status_code, 422)
        eq("C2 错误码", r.json()["code"], "INVALID_INPUT")

        # 跨字段校验：结束早于开始
        bad = dict(payload, started_on="2026-10-22", ended_on="2026-10-01")
        r = c.post("/api/v1/extract", json=bad)
        eq("C3 日期倒置 422", r.status_code, 422)
        check("C3 details 里能定位到跨字段错误", any(d["field"] == "_model" for d in r.json()["details"]),
              str(r.json()["details"]))

        # 缺必填
        bad = {k: v for k, v in payload.items() if k != "rules"}
        r = c.post("/api/v1/extract", json=bad)
        eq("C4 缺 rules 422", r.status_code, 422)

        # ---- response_model 是过滤，不是注释（前提：出参模型 extra="ignore"）----
        r = c.post("/api/v1/extract/raw", json=payload)
        eq("C5 /extract/raw 200", r.status_code, 200)
        raw = r.json()
        check("C5 服务层确实多给了 _internal_hint，但被裁掉", "_internal_hint" not in raw, str(raw.keys()))
        check("C5 stats 也被裁掉", "stats" not in raw, str(raw.keys()))
        # 两个接口的出参键完全一致 —— 这就是过滤生效的直接证据
        eq("C6 两个接口出参键一致", sorted(raw.keys()), sorted(body.keys()))

        # 反证：出参模型若用 extra="forbid"，多返回一个键就是 500（不是过滤）
        from app.schemas.extract import ExtractResult, REQUEST_CONFIG

        probe = ExtractResult.model_validate({**body})  # ignore：多余键被丢弃
        eq("C6b 出参模型是 ignore 语义", ExtractResult.model_config.get("extra"), "ignore")
        check("C6b forbid 才会炸",
              ExtractResult.model_config.get("extra") != "forbid" and probe is not None)

        # 超长正文 → AppError(413)
        long_text = "x" * (get_settings().max_doc_chars + 1)
        r = c.post("/api/v1/extract", json={"doc_id": "d", "text": long_text,
                                            "rules": [{"name": "a", "type": "str"}]})
        eq("C7 正文超长 413", r.status_code, 413)
        eq("C7 错误码", r.json()["code"], "DOC_TOO_LONG")

        # 422 的 details 要能定位到具体字段
        r = c.post("/api/v1/extract", json={"doc_id": "d", "text": "t",
                                            "rules": [{"name": "BAD-NAME", "type": "str"}]})
        eq("C8 非法字段名 422", r.status_code, 422)
        fields = [d["field"] for d in r.json()["details"]]
        check("C8 details 指到 rules.0.name", any("rules.0.name" == f for f in fields), str(fields))


# ==================================================================== D 依赖注入
def group_d_deps() -> None:
    section("D. 依赖注入：缓存 / 嵌套 / 单例")
    with TestClient(app) as c:
        r1 = c.get("/api/v1/deps/probe")
        r2 = c.get("/api/v1/deps/probe")
        b1, b2 = r1.json(), r2.json()

        # 请求内缓存：同一请求两次 Depends 拿到同一个对象
        eq("D1 请求内 settings 同一对象", b1["settings_same_object"], True)
        eq("D1 请求内 registry 同一对象", b1["registry_same_object"], True)

        # 进程级单例：跨请求 settings.id 不变
        eq("D2 跨请求 settings_id 相同（lru_cache）", b1["settings_id"], b2["settings_id"])

        # 请求级唯一：跨请求 request_id 必变
        check("D3 跨请求 request_id 不同", b1["request_id"] != b2["request_id"],
              f"{b1['request_id']} vs {b2['request_id']}")

        # 嵌套依赖：extractor 用的是 lifespan 建的那个（不是临时造的）
        eq("D4 extractor 来自 lifespan", b1["extractor_id"], id(app.state.extractor) if app.state.extractor else -1)

        # 头部依赖
        r = c.get("/api/v1/deps/probe", headers={"X-Client-Name": "verify-script"})
        eq("D5 自定义请求头注入", r.json()["client"], "verify-script")
        r = c.get("/api/v1/deps/probe")
        eq("D5 缺省 client", r.json()["client"], "anonymous")

        # rid 一致性：响应头 == 响应体里的 request_id
        r = c.get("/api/v1/deps/probe")
        eq("D6 响应头 X-Request-ID 与体内一致", r.headers.get("X-Request-ID"), r.json()["request_id"])

        # 客户端自带 X-Request-ID 时沿用（便于跨服务串联）
        r = c.get("/api/v1/deps/probe", headers={"X-Request-ID": "trace-abc-123"})
        eq("D7 沿用客户端传入的 rid", r.json()["request_id"], "trace-abc-123")
        eq("D7 响应头同步", r.headers.get("X-Request-ID"), "trace-abc-123")


# ==================================================================== E 错误处理
def group_e_errors() -> None:
    section("E. 错误处理：统一响应体 {code, message, request_id}")
    with TestClient(app, raise_server_exceptions=False) as c:
        # HTTPException
        r = c.get("/api/v1/debug/http-exception")
        eq("E1 HTTPException 状态码透传", r.status_code, 418)
        b = r.json()
        check("E1 统一体有 code", "code" in b)
        eq("E1 message 来自 detail", b["message"], "我是茶壶，不能泡咖啡")
        check("E1 有 request_id 且非空", bool(b.get("request_id")) and b["request_id"] != "-", str(b))

        # 未捕获异常 → 500（不泄露内部信息）
        r = c.get("/api/v1/debug/boom")
        eq("E2 未捕获异常 500", r.status_code, 500)
        b = r.json()
        eq("E2 code=INTERNAL_ERROR", b["code"], "INTERNAL_ERROR")
        check("E2 不泄露异常内容", "故意的崩溃" not in b["message"], b["message"])
        check("E2 仍有 request_id", bool(b.get("request_id")))

        # 404 由框架抛 starlette 版，也要被统一
        r = c.get("/api/v1/nope")
        eq("E3 不存在的路由 404", r.status_code, 404)
        eq("E3 404 也被统一", r.json()["code"], "NOT_FOUND")

        # 405 方法不允许
        r = c.delete("/api/v1/health")
        eq("E4 405 也被统一", r.status_code, 405)
        eq("E4 code", r.json()["code"], "METHOD_NOT_ALLOWED")

        # 三套形状归一：所有错误响应的键集合完全相同
        keys = set()
        for resp in (
            c.get("/api/v1/debug/http-exception"),
            c.get("/api/v1/debug/boom"),
            c.get("/api/v1/nope"),
            c.delete("/api/v1/health"),
            c.post("/api/v1/extract", json={}),
        ):
            keys.add(frozenset(resp.json().keys()))
        eq("E5 五种错误的响应体形状一致", len(keys), 1)
        eq("E5 形状就是四件套", set(next(iter(keys))), {"code", "message", "request_id", "details"})

        # 出错时响应头也有 rid（第二个中间件负责补）
        r = c.get("/api/v1/debug/boom")
        eq("E6 错误响应也有 X-Request-ID", r.headers.get("X-Request-ID"), r.json()["request_id"])


# ==================================================================== F /docs 生成的 schema
def group_f_openapi() -> None:
    section("F. /docs：OpenAPI schema 长对了没")
    with TestClient(app) as c:
        eq("F1 /docs 可访问", c.get("/docs").status_code, 200)
        eq("F2 /redoc 可访问", c.get("/redoc").status_code, 200)
        spec = c.get("/openapi.json").json()

        eq("F3 title 来自配置", spec["info"]["title"], get_settings().app_name)
        eq("F4 version 来自配置", spec["info"]["version"], get_settings().app_version)

        paths = spec["paths"]
        expected = {
            "/api/v1/health", "/api/v1/config", "/api/v1/deps/probe", "/api/v1/extract",
            "/api/v1/extract/raw", "/api/v1/documents/{doc_id}",
            "/api/v1/documents/{doc_id}/fields/{field_name}",
            "/api/v1/debug/http-exception", "/api/v1/debug/boom",
        }
        eq("F5 所有业务路径都进了 schema", set(paths) & expected, expected)

        # 请求体 schema 里能看到我们写的 description
        post = paths["/api/v1/extract"]["post"]
        ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        schema_name = ref.split("/")[-1]
        req_schema = spec["components"]["schemas"][schema_name]
        check("F6 requestBody 指向 ExtractRequest", schema_name == "ExtractRequest", schema_name)
        check("F6 doc_id 的 description 进了 schema",
              req_schema["properties"]["doc_id"].get("description") == "文档 id，由调用方生成",
              str(req_schema["properties"]["doc_id"]))

        # 响应 schema 是 ExtractResult
        ok_ref = post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        eq("F7 200 响应指向 ExtractResult", ok_ref.split("/")[-1], "ExtractResult")

        # 422 响应指向我们挂的 ErrorResponse（而不是默认的 HTTPValidationError）
        eq("F8 422 指向 ErrorResponse", post["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1],
           "ErrorResponse")

        # 查询参数在 schema 里展开（Pagination 是依赖，不是嵌套对象）
        params = {p["name"]: p for p in paths["/api/v1/documents/{doc_id}"]["get"]["parameters"]}
        check("F9 page 参数已展开", "page" in params, str(list(params)))
        check("F9 size 参数已展开", "size" in params, str(list(params)))
        eq("F9 sort 有 pattern 约束", params["sort"]["schema"].get("pattern"), "^(asc|desc)$")


# ==================================================================== G 配置 / 密钥
def group_g_config() -> None:
    section("G. 配置：SecretStr 掩码 / 进程内单例")
    with TestClient(app) as c:
        r1 = c.get("/api/v1/config")
        r2 = c.get("/api/v1/config")
        b1, b2 = r1.json(), r2.json()

        eq("G1 密钥被掩码", b1["api_key"], "**********")
        check("G1 响应里没有真实密钥",
              get_settings().api_key.get_secret_value() not in json.dumps(b1, ensure_ascii=False),
              "明文泄露了")
        eq("G2 config_id 跨请求不变", b1["config_id"], b2["config_id"])
        eq("G2 config_id 就是 id(get_settings())", b1["config_id"], id(get_settings()))
        eq("G3 max_doc_chars 来自 .env", b1["max_doc_chars"], get_settings().max_doc_chars)
        eq("G4 app_env", b1["app_env"], get_settings().app_env)


# ==================================================================== H 服务层独立性
def group_h_layer() -> None:
    section("H. 分层：services 不依赖 fastapi / 可直接跑")
    import ast
    import pathlib

    path = pathlib.Path("app/services/extractor.py")
    src = path.read_text(encoding="utf-8")

    # 关键：查 **import 语句**，不是查文本。docstring 里提到 "fastapi" 是允许的
    # （本文件正好在讲"不 import fastapi"，纯文本匹配会误报）。
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                imported.add(n.split(".")[0])

    check("H1 extractor.py 不 import fastapi", "fastapi" not in imported, f"imported={sorted(imported)}")
    check("H1 extractor.py 不 import starlette", "starlette" not in imported, f"imported={sorted(imported)}")
    check("H1 extractor.py 不 import app.core（业务不依赖配置实现）",
          not any(m.startswith("app.core") for m in imported), f"imported={sorted(imported)}")

    # 服务层能脱离 HTTP 直接调用
    from app.services.extractor import ResourceRegistry, RuleBasedExtractor

    settings = get_settings()
    reg = ResourceRegistry.load(settings)
    ext = RuleBasedExtractor(registry=reg, version="rule-v1-probe")
    report = ext.run(
        doc_id="cli-1",
        text="合同号：HT-2026-7781 合计金额：2,400.00 签订日期：2026-09-30",
        rules=[
            {"name": "contract_no", "type": "str", "required": True},
            {"name": "total_amount", "type": "float", "required": True},
            {"name": "sign_date", "type": "date", "required": True},
        ],
    )
    eq("H2 脱离 HTTP 抽到合同号", report.fields["contract_no"], "HT-2026-7781")
    eq("H2 金额转 float", report.fields["total_amount"], 2400.0)
    eq("H2 日期归一", report.fields["sign_date"], "2026-09-30")
    eq("H2 版本用的是传入值", report.model, "rule-v1-probe")
    check("H2 confidence 合理", 0.0 < report.confidence <= 1.0, f"{report.confidence}")

    # 抽不到的必填字段要进 missing，且不编造
    report2 = ext.run(doc_id="cli-2", text="此处没有任何单号",
                      rules=[{"name": "invoice_no", "type": "str", "required": True}])
    eq("H3 抽不到就 None", report2.fields["invoice_no"], None)
    eq("H3 进了 missing", report2.missing, ["invoice_no"])
    eq("H3 全都没抽到置信度 0", report2.confidence, 0.0)

    # 日期兜底：字段没抽到日期时用 started_on，并打折
    report3 = ext.run(doc_id="cli-3", text="没有日期",
                      rules=[{"name": "bill_date", "type": "date", "required": True}],
                      started_on=date(2026, 10, 1))
    eq("H4 日期兜底生效", report3.fields["bill_date"], "2026-10-01")
    check("H4 兜底后置信度被打折", report3.confidence <= 0.7, f"{report3.confidence}")


# ==================================================================== main
def main() -> int:
    for fn in (
        group_a_lifespan,
        group_b_routing,
        group_c_body,
        group_d_deps,
        group_e_errors,
        group_f_openapi,
        group_g_config,
        group_h_layer,
    ):
        fn()

    print("\n" + "=" * 60)
    print(f"通过 {PASS} 项，失败 {FAIL} 项")
    if FAIL:
        print("\n失败清单：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print("全部通过：路由/参数、依赖注入、错误处理、生命周期与中间件、/docs schema 都成立。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
