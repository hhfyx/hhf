# -*- coding: utf-8 -*-
"""验收核心：证明非法输入被拒（3 个业务模型 × 各自规则）。

这个文件就是"能证明非法输入被拒"的那一个 py：
- 每条规则一个反例，断言**确实**抛 ValidationError、且 `loc` / `type` 落在预期位置；
- 再给每个模型一个合法输入，断言能被接受（避免"全都拒"的假阳性）；
- 最后把错误转成对外 ErrorResponse，演示真实链路。

运行：py -3.11 -X utf8 verify_rejects.py
退出码 0 = 全部通过；任一断言失败 -> 非 0 并打印是哪条。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from pydantic import ValidationError

from app.core.models import ErrorResponse, ExtractRequest, ExtractResult

PASSED = 0
FAILED: list[str] = []


def expect_reject(model, payload: dict, *, expect_loc, expect_type, case: str) -> None:
    """断言 model(**payload) 必须失败，且错误定位符合预期。"""
    global PASSED
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        locs = [err["loc"] for err in exc.errors()]
        types = [err["type"] for err in exc.errors()]
        if expect_loc not in locs:
            FAILED.append(f"{case}: 报了 {locs}，但没命中预期 loc={expect_loc}")
            return
        if expect_type not in types:
            FAILED.append(f"{case}: 报了 {types}，但没命中预期 type={expect_type}")
            return
        PASSED += 1
        first = exc.errors()[0]
        print(f"  [拒绝] {case}")
        print(f"         loc={first['loc']} type={first['type']} 错误数={exc.error_count()}")
    else:
        FAILED.append(f"{case}: 本应被拒但通过了！")


def expect_reject_prefix(model, payload: dict, *, expect_prefix, case: str) -> None:
    """断言失败且某条错误的 loc 以 expect_prefix 开头。

    联合类型（`str | int | float | None`）失败时，pydantic 会为每个分支各报一条，
    loc 末尾多带一段分支名（如 ('fields','x','str')），所以只能按前缀匹配。
    """
    global PASSED
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        locs = [err["loc"] for err in exc.errors()]
        if not any(loc[: len(expect_prefix)] == tuple(expect_prefix) for loc in locs):
            FAILED.append(f"{case}: 报了 {locs}，但没命中前缀 {expect_prefix}")
            return
        PASSED += 1
        print(f"  [拒绝] {case}")
        print(f"         loc 共 {len(locs)} 条（联合类型按分支各报一条），首条={locs[0]}")
    else:
        FAILED.append(f"{case}: 本应被拒但通过了！")


def expect_accept(model, payload: dict, *, case: str):
    """断言合法输入被接受，并返回实例。"""
    global PASSED
    try:
        inst = model.model_validate(payload)
    except ValidationError as exc:
        FAILED.append(f"{case}: 本应通过却失败 {exc.errors()}")
        return None
    PASSED += 1
    print(f"  [通过] {case}")
    return inst


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ============================================================ 1) ExtractRequest
section("1) ExtractRequest（抽取请求）")

valid_request = {
    "doc_id": "doc-001",
    "rules": [
        {"name": "invoice_no", "type": "str"},
        {"name": "total_amount", "type": "float", "required": False},
    ],
    "started_on": "2026-10-01",
    "ended_on": "2026-10-22",
}
req = expect_accept(ExtractRequest, valid_request, case="合法请求：2 条规则 + 日期区间正常")
if req:
    print(f"          doc_id={req.doc_id} rules={[r.name for r in req.rules]}")

# 规则 1：rules 至少 1 条
expect_reject(
    ExtractRequest,
    {"doc_id": "doc-001", "rules": []},
    expect_loc=("rules",),
    expect_type="too_short",
    case="rules 为空列表 -> 至少 1 个抽取字段",
)

# 规则 1b：doc_id 非空
expect_reject(
    ExtractRequest,
    {"doc_id": "", "rules": [{"name": "a"}]},
    expect_loc=("doc_id",),
    expect_type="string_too_short",
    case="doc_id 为空字符串",
)

# 规则 2：rules[].name 重复（跨字段 model_validator，loc 落在模型级 = ()）
expect_reject(
    ExtractRequest,
    {"doc_id": "d", "rules": [{"name": "amount"}, {"name": "amount"}]},
    expect_loc=(),
    expect_type="value_error",
    case="rules 里字段名重复（跨字段校验）",
)

# 规则 3：结束日期早于开始日期（任务里点名的用例）
expect_reject(
    ExtractRequest,
    {"doc_id": "d", "rules": [{"name": "a"}], "started_on": "2026-10-22", "ended_on": "2026-10-01"},
    expect_loc=(),
    expect_type="value_error",
    case="结束日期早于开始日期（ISO 字符串比较）",
)

# 规则 3b：日期格式非法（声明成 str 时这条会漏过去，lax 转换救不了 "2026/10/01"）
expect_reject(
    ExtractRequest,
    {"doc_id": "d", "rules": [{"name": "a"}], "started_on": "2026/10/01"},
    expect_loc=("started_on",),
    expect_type="date_from_datetime_parsing",
    case="日期格式非法（2026/10/01）",
)

# 规则 5：extra="forbid" 在嵌套子模型上也生效
expect_reject(
    ExtractRequest,
    {"doc_id": "d", "rules": [{"name": "a", "typ0": 1}]},
    expect_loc=("rules", 0, "typ0"),
    expect_type="extra_forbidden",
    case="规则对象里多传未声明字段（extra=forbid）",
)

# 规则 5b：顶层的未声明字段
expect_reject(
    ExtractRequest,
    {"doc_id": "d", "rules": [{"name": "a"}], "dry_run": True},
    expect_loc=("dry_run",),
    expect_type="extra_forbidden",
    case="请求顶层多传未声明字段（extra=forbid）",
)

# 规则 2b：字段名必须 snake_case 小写
expect_reject(
    ExtractRequest,
    {"doc_id": "d", "rules": [{"name": "InvoiceNo"}]},
    expect_loc=("rules", 0, "name"),
    expect_type="value_error",
    case="字段名不是小写 snake_case（InvoiceNo）",
)


# ============================================================= 2) ExtractResult
section("2) ExtractResult（抽取结果）")

now = datetime(2026, 10, 22, 21, 20, 0)
valid_result = {
    "doc_id": "doc-001",
    "fields": {"invoice_no": "INV-2026-001", "total_amount": 1299.5},
    "confidence": 0.93,
    "started_at": now,
    "finished_at": now + timedelta(seconds=3),
    "allowed_fields": {"invoice_no", "total_amount"},
}
result = expect_accept(ExtractResult, valid_result, case="合法结果：confidence=0.93 且字段都在白名单")
if result:
    print(f"          model_dump_json={result.model_dump_json()}")

# 规则 1：confidence 越界
expect_reject(
    ExtractResult,
    {**valid_result, "confidence": 1.5},
    expect_loc=("confidence",),
    expect_type="less_than_equal",
    case="confidence=1.5 超出 [0,1]",
)
expect_reject(
    ExtractResult,
    {**valid_result, "confidence": -0.1},
    expect_loc=("confidence",),
    expect_type="greater_than_equal",
    case="confidence=-0.1 超出 [0,1]",
)

# 规则 2：finished_at 早于 started_at
expect_reject(
    ExtractResult,
    {**valid_result, "finished_at": now - timedelta(hours=1)},
    expect_loc=(),
    expect_type="value_error",
    case="finished_at 早于 started_at",
)

# 规则 3：fields 出现未声明字段（幻觉拦截）
expect_reject(
    ExtractResult,
    {**valid_result, "fields": {"invoice_no": "x", "hallucinated": 1}},
    expect_loc=(),
    expect_type="value_error",
    case="fields 含未声明字段（hallucinated）",
)

# 规则 3b：fields 的值类型不合法。注意 loc 是 ('fields', 'invoice_no', 'str') ——
# 联合类型会为每个分支各报一条，loc 末尾带上分支名，所以这里断言的是前缀匹配。
expect_reject_prefix(
    ExtractResult,
    {**valid_result, "fields": {"invoice_no": ["not", "scalar"]}},
    expect_prefix=("fields", "invoice_no"),
    case="fields 的值是 list（只允许 str/int/float/None）",
)

# 额外：必填字段缺失由业务层检查（模型只管自洽，跨模型交叉校验放 service 层）
if result and req:
    rules = req.rules  # 来自上面合法请求：invoice_no(required) / total_amount(not required)
    print(f"          合法结果 missing_required -> {result.missing_required(rules)}")
    if not result.missing_required(rules) == []:
        FAILED.append("missing_required 对合法结果应为空")

    partial = ExtractResult.model_validate(
        {**valid_result, "fields": {"invoice_no": "INV-1"}}  # total_amount 允许缺
    )
    print(f"          缺非必填字段 missing_required -> {partial.missing_required(rules)}")

    empty = ExtractResult.model_validate({**valid_result, "fields": {}})
    missing = empty.missing_required(rules)
    print(f"          全缺 missing_required -> {missing}（这类交叉校验必须拿到 request 才能判，"
          f"\n          所以不放模型的 model_validator 里，否则模型得带上无关上下文）")
    if missing != ["invoice_no"]:
        FAILED.append(f"missing_required 应只报必填的 invoice_no，实际 {missing}")
    PASSED += 1


# ============================================================= 3) ErrorResponse
section("3) ErrorResponse（统一错误体）")

valid_error = {
    "code": "INVALID_INPUT",
    "message": "doc_id 不能为空",
    "details": [{"field": "doc_id", "reason": "不能为空"}],
}
err = expect_accept(ErrorResponse, valid_error, case="合法错误体：code 大写 + 1 条明细")
if err:
    print(f"          model_dump_json={err.model_dump_json()}")

# 规则 1：code 必须大写
expect_reject(
    ErrorResponse,
    {**valid_error, "code": "invalid_input"},
    expect_loc=("code",),
    expect_type="value_error",
    case="code 小写（invalid_input）",
)

# 规则 1b：code 非法字符
expect_reject(
    ErrorResponse,
    {**valid_error, "code": "INVALID-INPUT"},
    expect_loc=("code",),
    expect_type="value_error",
    case="code 含连字符（INVALID-INPUT）",
)

# 规则 2：message 过长
expect_reject(
    ErrorResponse,
    {**valid_error, "message": "x" * 501},
    expect_loc=("message",),
    expect_type="string_too_long",
    case="message 超过 500 字符",
)

# 规则 3：retryable 必须给 retry_after_s
expect_reject(
    ErrorResponse,
    {"code": "UPSTREAM_TIMEOUT", "message": "上游超时", "retryable": True},
    expect_loc=(),
    expect_type="value_error",
    case="retryable=True 但没给 retry_after_s",
)

# 规则 3b：retry_after_s 必须 > 0
expect_reject(
    ErrorResponse,
    {"code": "UPSTREAM_TIMEOUT", "message": "上游超时", "retryable": True, "retry_after_s": 0},
    expect_loc=("retry_after_s",),
    expect_type="greater_than",
    case="retry_after_s=0（必须 > 0）",
)

# 规则 4：details 最多 20 条
expect_reject(
    ErrorResponse,
    {**valid_error, "details": [{"field": f"f{i}"} for i in range(21)]},
    expect_loc=("details",),
    expect_type="too_long",
    case="details 超过 20 条",
)


# ================================================ 4) 端到端：非法输入 -> 错误体
section("4) 端到端：把非法请求转成对外 ErrorResponse")

try:
    ExtractRequest.model_validate(
        {"doc_id": "", "rules": [{"name": "Bad-Name"}], "started_on": "2026/10/01"}
    )
except ValidationError as exc:
    resp = ErrorResponse.from_validation_error(exc)
    print(f"  {resp.model_dump_json(indent=2)}")

    # 错误体自身也必须合法（它能直接序列化回前端）
    assert isinstance(resp, ErrorResponse)
    assert len(resp.details) == exc.error_count()
    PASSED += 1
    print(f"  错误体合法，details 条数 {len(resp.details)} == error_count() {exc.error_count()}")


# ==================================================================== 汇总
print(f"\n{'=' * 70}")
print(f"通过 {PASSED} 项，失败 {len(FAILED)} 项")
print("=" * 70)
if FAILED:
    for item in FAILED:
        print(f"  [失败] {item}")
    sys.exit(1)
print("全部通过：3 个业务模型的非法输入都被正确拒绝。")
