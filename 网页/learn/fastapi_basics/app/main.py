# -*- coding: utf-8 -*-
"""组装（验收要求：app/main.py）。

这个文件只做"接线"，不含任何业务逻辑。启动顺序：

    1. FastAPI(...)             —— 实例化，把 lifespan 挂上
    2. register_middlewares     —— 中间件（先注册的在最外层）
    3. register_exception_handlers —— 异常处理器
    4. include_router           —— 挂 v1 路由

为什么顺序重要：

- **异常处理器必须在 include_router 之前注册**？其实不影响（注册表是 app 级的），
  但养成的习惯是"先装基础设施，再挂业务"；
- **中间件顺序是真的有影响**：`request_context_middleware` 必须在
  `request_id_header_middleware` 外层，因为它要生成 rid，内层要用它补响应头。

启动命令：

    py -3.11 -m uvicorn app.main:app --reload --port 8000

然后开 <http://127.0.0.1:8000/docs> 看生成的 schema。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import lifespan, register_middlewares

# 配置在这里**第一次**被解析（lifespan 里也是第一次，但这里要给 FastAPI 的 title）。
# 注意：如果 .env 里缺 API_KEY，这行会在 import 阶段就抛 ValidationError ——
# 这正是"早炸"的效果。想验证"缺配置启动失败"，删掉 .env 里的 API_KEY 再启动即可。
_settings = get_settings()

logging.basicConfig(
    level=getattr(logging, _settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title=_settings.app_name,
    version=_settings.app_version,
    description=(
        "文档字段抽取服务（规则版）。\n\n"
        "**统一错误体**：所有非 2xx 都是 `{code, message, request_id, details}`。\n\n"
        "**统一请求 id**：响应头 `X-Request-ID`，与错误体里的 `request_id` 一致。"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

register_middlewares(app)
register_exception_handlers(app)
app.include_router(v1_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """根路径只做导航，不进 OpenAPI（`include_in_schema=False`）。"""
    return {
        "service": _settings.app_name,
        "version": _settings.app_version,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/api/v1/health",
    }


__all__ = ["app"]
