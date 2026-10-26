# -*- coding: utf-8 -*-
"""中间件 + 生命周期（任务 21:30–22:00）。

两块内容：

--- 1. 中间件：给每个请求发 request_id、记耗时 ---

用 `@app.middleware("http")` 装饰器（底层就是 BaseHTTPMiddleware）。
执行顺序要记住：**洋葱模型**，先注册的后执行。

    add_middleware(A); add_middleware(B)
    请求 → A 前半 → B 前半 → 路由 → B 后半 → A 后半 → 响应

所以 request_id 中间件如果依赖耗时中间件的结果，要注意先后；这里两者独立，
顺序无关，但 `request_id` 必须排在**最外层**（先注册），否则内层出错时它还没设好。

关键细节：`request.state.request_id` 在 call_next **之前**设好，因为路由和异常处理器
都要读它。下游抛异常时中间件里的 `call_next` 会重抛 —— 统一错误响应体是
异常处理器生成的，中间件只负责补响应头。

--- 2. lifespan：启动加载资源 / 关闭释放 ---

    @asynccontextmanager
    async def lifespan(app): yield {"xx": ...}

- yield **之前**是启动，**之后**是关闭；
- yield 出来的 dict 会被塞进 `request.state`（不是 `app.state`！实测确认）；
- 想给 app 本身挂东西，就显式 `app.state.xx = ...`。

为什么用 lifespan 而不是 `@app.on_event("startup")`：on_event 已废弃，
且 startup/shutdown 两个钩子容易漏配对；lifespan 用一个 `async with` 表达，
资源获取与释放写在同一处，异常时也能保证释放。
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI, Request, Response

from app.core.config import get_settings
from app.services.extractor import ResourceRegistry, RuleBasedExtractor

logger = logging.getLogger(__name__)


# ============================================================ 生命周期
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """启动：解析配置、装载资源；关闭：释放。

    这里做了一件"能被验证"的事：把规则版抽取器实例和它加载的词表放进来，
    后面 `/api/v1/extract` 每次请求都用它，`/api/v1/health` 再把资源摘要吐出来。
    """
    settings = get_settings()  # 第一次解析发生在这里 —— 配置错就启动失败
    logger.info(
        "startup app=%s env=%s version=%s",
        settings.app_name,
        settings.app_env,
        settings.app_version,
    )

    registry = ResourceRegistry.load(settings)
    extractor = RuleBasedExtractor(registry=registry, version=settings.extract_model)

    started_at = time.perf_counter()

    # 显式挂到 app.state（想从 app 层面访问时用；路由里更常用 request.state）
    app.state.registry = registry
    app.state.extractor = extractor
    app.state.started_at = started_at

    # yield 出来的字典会进 request.state —— 路由里 request.state.extractor 直接可用
    yield {
        "settings": settings,
        "registry": registry,
        "extractor": extractor,
        "started_at": started_at,
    }

    logger.info("shutdown app=%s", settings.app_name)
    registry.close()
    # 主动清掉引用，避免热重载时旧实例被闭包吊住
    app.state.registry = None
    app.state.extractor = None


# ============================================================ 中间件
async def request_context_middleware(request: Request, call_next: Callable) -> Response:
    """最外层用户中间件：分配 request_id，记录耗时，给正常响应补头。

    `request.state` 是"每请求一份"的命名空间，往下传参靠它，不用改函数签名。
    响应头里回传 `X-Request-ID`：客户端报障时直接报这个 id，服务端 grep 整条链路。

    **实测出来的边界（很重要）：**

        ExceptionMiddleware（异常处理器）  ── 在所有 @app.middleware("http") 之内层
        ServerErrorMiddleware（Exception 处理器）── 在所有中间件之**外**

    所以：
    - `AppError` / `HTTPException` / `RequestValidationError`：异常处理器在中间件之内，
      响应会正常穿过 `call_next` 返回 → 这里能补 `X-Request-ID`；
    - 未捕获异常：`Exception` 处理器在最外层，**中间件的"后半"不会执行**
      （实测只打印了前半，`call_next` 直接重抛）→ 这里补不到头，
      必须由那个处理器自己写 `X-Request-ID`（见 core/errors.py 的说明）。

    耗时日志放 `finally`：报错请求同样有耗时记录 —— 这是它在这里唯一的用处。
    """
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    request.state.request_id = rid

    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers.setdefault("X-Request-ID", rid)
        return response
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "access rid=%s method=%s path=%s status=%s cost_ms=%.2f",
            rid,
            request.method,
            request.url.path,
            status,
            elapsed_ms,
        )


def register_middlewares(app: FastAPI) -> None:
    """注册顺序 = 从外到内。

    洋葱模型：先注册的是外层。完整链路（含框架自带的两个）：

        ServerErrorMiddleware   ← Exception 处理器在这层，绕开用户中间件
          └─ request_context_middleware（分配 rid、记耗时、给正常响应补头）
               └─ ExceptionMiddleware  ← AppError/HTTPException/422/ResponseValidationError
                    └─ 路由

    本课只需要一个用户中间件就够了：拆成两个反而会让人以为"内层能补上异常响应头"，
    实际补不上 —— 那是框架层级的边界，不是中间件数量的问题。
    """
    app.middleware("http")(request_context_middleware)


__all__ = ["lifespan", "register_middlewares", "request_context_middleware"]
