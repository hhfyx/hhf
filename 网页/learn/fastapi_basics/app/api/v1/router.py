# -*- coding: utf-8 -*-
"""API v1 路由（任务 20:00–21:00）。

一个 `APIRouter(prefix="/api/v1")` 收齐本期所有路径。prefix 放在这里而不是
main.py，好处是"删掉 v1 就等于删掉整个版本"，v2 加一个平级包即可。

本文件覆盖任务点名的 5 件事，每条路由都能在 /docs 里点着验证：

    路径参数        GET  /documents/{doc_id}
    查询参数        GET  /documents/{doc_id}?page=1&size=10&sort=asc
    Body + model    POST /extract
    response_model  POST /extract（出参过滤）、GET /config
    依赖注入        GET  /deps/probe（看缓存与嵌套）

再加两条"故意出错"的：
    GET  /documents/{doc_id}/fields/{field_name}  → 404，走 AppError
    POST /debug/boom                              → 500，走兜底异常处理器

约定：本层**不做业务计算**，只负责 HTTP 语义（状态码、参数解析、模型转换）。
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, status

from app.core.config import get_settings
from app.core.deps import (
    ClientNameDep,
    ExtractorDep,
    PaginationDep,
    RegistryDep,
    RequestIdDep,
    SettingsDep,
    get_extractor,
    get_registry,
    get_settings_dep,
)
from app.core.errors import AppError
from app.schemas.extract import (
    ConfigInfo,
    ErrorResponse,
    ExtractRequest,
    ExtractResult,
    HealthResponse,
)

router = APIRouter(prefix="/api/v1", tags=["v1"])

# 统一错误响应在 /docs 里的声明：把 ErrorResponse 的 schema 挂上去，
# Swagger 就会在接口下显示 "422 / 404 / 500 → ErrorResponse" 而不是空。
ERR_422 = {422: {"model": ErrorResponse, "description": "输入校验失败"}}
ERR_404 = {404: {"model": ErrorResponse, "description": "资源不存在"}}
ERR_500 = {500: {"model": ErrorResponse, "description": "服务端错误"}}


# ============================================================ 健康 / 配置
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    responses={**ERR_500},
)
async def health(
    request: Request,
    registry: RegistryDep,
    request_id: RequestIdDep,
) -> HealthResponse:
    """探活。

    `/health` 会在 `resources` 里吐出 lifespan 加载的资源摘要 ——
    这是"生命周期真的执行了"的可视证据：没走 lifespan 就没有 registry，这里会报错。

    `uptime_s` 取自 lifespan yield 出来的 `started_at`（进了 `request.state`），
    而不是模块级全局变量 —— 后者的值在热重载时会变得不可信。
    """
    started = getattr(request.state, "started_at", None)
    uptime = round(time.perf_counter() - started, 2) if started else 0.0
    return HealthResponse(
        status="ok",
        uptime_s=uptime,
        resources={**registry.summary(), "request_id": request_id},
    )


@router.get(
    "/config",
    response_model=ConfigInfo,
    summary="查看生效配置",
    responses={**ERR_500},
)
async def read_config(settings: SettingsDep) -> ConfigInfo:
    """返回配置摘要。

    两个验证点：
    1. `api_key` 恒为 `**********` —— SecretStr 不会漏明文；
    2. `config_id` 是 `id(settings)`，反复调用它都一样 —— 进程内单例的证据。
    """
    return ConfigInfo(**settings.public_info())


# ============================================================ 依赖缓存实证
@router.get(
    "/deps/probe",
    summary="依赖注入探针",
    description="同一请求内重复注入依赖，看 id 是否相同：这是 FastAPI 依赖缓存的直接证据。",
)
async def deps_probe(
    request_id: RequestIdDep,
    settings_a: SettingsDep,
    settings_b: SettingsDep,
    registry_a: RegistryDep,
    registry_b: RegistryDep,
    extractor: ExtractorDep,
    client: ClientNameDep,
) -> dict[str, Any]:
    """一次请求里这几组参数各要了两次同样的依赖。

    预期（实测）：
    - `settings_a.id == settings_b.id` → 请求内缓存命中，只求值一次；
    - `registry_a.id == registry_b.id` → 同上，且两者都是 lifespan 建的那个；
    - `extractor.id` 是 lifespan 建的那个；
    - `request_id` 与响应头 `X-Request-ID` 完全一致；
    - 跨请求再看：`settings.id` 不变（lru_cache），`request_id` 每次都变。
    """
    return {
        "request_id": request_id,
        "client": client,
        "settings_id": id(settings_a),
        "settings_same_object": settings_a is settings_b,
        "registry_id": id(registry_a),
        "registry_same_object": registry_a is registry_b,
        "extractor_id": id(extractor),
        "extractor_version": extractor.version,
        "note": "settings_id 跨请求不变；request_id 跨请求必变",
    }


# ============================================================ 核心：抽取
@router.post(
    "/extract",
    response_model=ExtractResult,
    status_code=status.HTTP_200_OK,
    summary="抽取字段（规则版）",
    responses={**ERR_422, **ERR_500},
)
async def extract(
    payload: Annotated[ExtractRequest, Body(description="抽取请求：文档正文 + 字段规则")],
    extractor: ExtractorDep,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> ExtractResult:
    """按规则从正文抽字段。

    这条路由把任务的四件事一次用全：

    - **Body**：`payload: ExtractRequest = Body(...)`，整个请求体落成一个模型；
    - **依赖**：`extractor` 是嵌套依赖树（extractor ← registry ← settings）；
    - **错误处理**：正文超长抛 `AppError`，处理器统一转成 `{code, message, request_id}`；
    - **response_model**：只返回 `ExtractResult` 声明的键，服务层多给的一律裁掉。

    返回里含 `missing`（必抽但没抽到）与 `confidence`（规则版是启发式，越低越可疑）。
    """
    if len(payload.text) > settings.max_doc_chars:
        raise AppError(
            "DOC_TOO_LONG",
            f"正文 {len(payload.text)} 字符，超过上限 {settings.max_doc_chars}",
            status=413,
        )

    report = extractor.run(
        doc_id=payload.doc_id,
        text=payload.text,
        rules=[r.model_dump() for r in payload.rules],
        started_on=payload.started_on,
        ended_on=payload.ended_on,
    )

    # 服务层的 report 在这里翻译成对外契约；`debug` 之类内部字段不出现在响应里
    return ExtractResult(
        doc_id=report.doc_id,
        fields=report.fields,
        missing=report.missing,
        confidence=report.confidence,
        model=report.model,
        started_at=report.started_at,
        finished_at=report.finished_at,
    )


@router.post(
    "/extract/raw",
    summary="抽取（故意多返回字段）",
    description="返回体里多塞了服务层内部字段，用来验证 response_model 的出参过滤。",
    response_model=ExtractResult,
)
async def extract_raw(
    payload: Annotated[ExtractRequest, Body(description="同上")],
    extractor: ExtractorDep,
) -> dict[str, Any]:
    """和 /extract 一样的逻辑，但**返回 dict 且多塞两个键**。

    用途：在 /docs 里对比 `/extract` 和 `/extract/raw` 的响应 ——
    两者 schema 相同，`_internal_hint` / `stats` 会被 response_model 直接裁掉。
    这就是"response_model 是过滤，不是注释"的实证。
    """
    report = extractor.run(
        doc_id=payload.doc_id,
        text=payload.text,
        rules=[r.model_dump() for r in payload.rules],
    )
    return {
        "doc_id": report.doc_id,
        "fields": report.fields,
        "missing": report.missing,
        "confidence": report.confidence,
        "model": report.model,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "_internal_hint": "这行会被 response_model 裁掉",
        "stats": {"rules": len(payload.rules)},
    }


# ============================================================ 路径 + 查询参数
_SAMPLE_DOCS: dict[str, list[dict[str, Any]]] = {
    "doc-001": [
        {"page": 1, "text": "发票号：INV-2026-0042 合计金额：1,280.50 开票日期：2026-10-20"},
        {"page": 2, "text": "备注：样品单，无税额"},
        {"page": 3, "text": "合同号：HT-2026-7781 签订日期：2026-10-01"},
    ],
    "doc-002": [
        {"page": 1, "text": "订单号：SO-2026-1123 总计：899.00 日期：2026-10-18"},
    ],
}


@router.get(
    "/documents/{doc_id}",
    summary="分页读取文档分页文本",
    responses={**ERR_404, **ERR_422},
)
async def read_document(
    doc_id: Annotated[str, Path(description="文档 id，如 doc-001", min_length=1, max_length=64)],
    page: PaginationDep,
    sort: Annotated[str, Query(pattern="^(asc|desc)$", description="页码排序方向")] = "asc",
) -> dict[str, Any]:
    """路径参数 + 查询参数（含参数组依赖）一次演示。

    - `doc_id` 来自路径：`/documents/doc-001`；
    - `page` / `size` 来自查询串，由 `Pagination` 依赖打包（约束 `ge/le` 生效，
      传 `size=999` 直接 422）；
    - `sort` 用 `pattern=` 卡住取值，传 `sort=up` 也是 422。

    不存在就抛 `AppError("NOT_FOUND", ...)`，不用 HTTPException ——
    两者都走统一错误体，但 AppError 能带 code。
    """
    if doc_id not in _SAMPLE_DOCS:
        raise AppError("NOT_FOUND", f"文档不存在：{doc_id}")

    items = _SAMPLE_DOCS[doc_id]
    items = sorted(items, key=lambda x: x["page"], reverse=(sort == "desc"))[page.offset : page.offset + page.size]

    return {
        "doc_id": doc_id,
        "pagination": page.as_dict(),
        "sort": sort,
        "items": items,
        "available": list(_SAMPLE_DOCS),
    }


@router.get(
    "/documents/{doc_id}/fields/{field_name}",
    summary="读取单个字段（演示 404 与路径参数类型）",
    responses={**ERR_404},
)
async def read_document_field(
    extractor: ExtractorDep,
    doc_id: str = Path(description="文档 id"),
    field_name: str = Path(description="字段名，如 invoice_no"),
) -> dict[str, Any]:
    """嵌套路径参数 + 404。

    依赖参数写在**前面、无默认值**，带默认值的 Path 参数写在后面 ——
    这是 Python 语法要求（有默认值的参数不能在有默认值的参数之前……反之也不行）。
    踩坑记录：写成 `extractor: ExtractorDep = None` 也能跑，但注释里会变成
    "可空依赖"，读的人会以为是可选注入，属于自己给自己挖坑。
    """
    if doc_id not in _SAMPLE_DOCS:
        raise AppError("NOT_FOUND", f"文档不存在：{doc_id}")

    text = " ".join(item["text"] for item in _SAMPLE_DOCS[doc_id])
    report = extractor.run(
        doc_id=doc_id,
        text=text,
        rules=[{"name": field_name, "type": "str", "required": False}],
    )
    value = report.fields.get(field_name)
    if value is None:
        raise AppError("NOT_FOUND", f"字段未找到：{field_name}")
    return {"doc_id": doc_id, "field": field_name, "value": value}


# ============================================================ 故意出错
@router.get(
    "/debug/http-exception",
    summary="演示 HTTPException",
    responses={418: {"model": ErrorResponse, "description": "我是茶壶"}},
)
async def debug_http_exception() -> None:
    """`HTTPException` 的 detail 是字符串，进统一体时被塞进 `message`。

    想带 code 就用 AppError；这里演示"老代码里已有的 HTTPException 也能被统一"。
    """
    raise HTTPException(status_code=418, detail="我是茶壶，不能泡咖啡")


@router.get(
    "/debug/boom",
    summary="演示未捕获异常 → 500 统一体",
    responses={**ERR_500},
)
async def debug_boom() -> None:
    """故意抛一个没被接住的异常。

    预期：客户端拿到 500 + `{code: "INTERNAL_ERROR", ...}`，**看不到**异常内容；
    服务端日志里有完整堆栈 + 同一个 request_id。
    注意 TestClient 默认 `raise_server_exceptions=True` 会重抛，验证脚本里要关掉。
    """
    raise RuntimeError("故意的崩溃：验证兜底异常处理器")


__all__ = ["router"]
