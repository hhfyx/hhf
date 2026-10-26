# -*- coding: utf-8 -*-
"""schemas：对外契约（请求体 / 响应体）。

只描述"长什么样"，不掺业务流程 —— 流程在 services/ 里。
每张表的 `description` 都会原样出现在 /docs 的 schema 里：写字段说明 = 写接口文档。
"""

from .extract import (
    ConfigInfo,
    ErrorDetail,
    ErrorResponse,
    ExtractRequest,
    ExtractResult,
    FieldRule,
    FieldType,
    HealthResponse,
)

__all__ = [
    "ConfigInfo",
    "ErrorDetail",
    "ErrorResponse",
    "ExtractRequest",
    "ExtractResult",
    "FieldRule",
    "FieldType",
    "HealthResponse",
]
