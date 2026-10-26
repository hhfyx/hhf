# -*- coding: utf-8 -*-
"""统一错误响应体 + 异常处理器（任务 21:00–21:30）。

目标：**所有**非 2xx 响应长得一模一样 —— `{code, message, request_id, details}`。

为什么非得统一？因为默认行为是三套形状，前端得写三个分支：

    1. HTTPException            → {"detail": "..."}
    2. RequestValidationError   → {"detail": [{loc, msg, type, ...}, ...]}
    3. 未捕获异常               → 纯文本 "Internal Server Error"（还可能带 traceback）

这里把它们全焊成一套。分工：

    code   —— 给程序判断的稳定字符串（INVALID_INPUT / NOT_FOUND / ...）
    message—— 给人看的一句话
    request_id —— 中间件塞进 request.state 的那个 id；出错时也能拿它去日志捞链路
    details—— 字段级明细，前端靠 field 高亮输入框

注册顺序无关紧要，但**必须注册**：不注册就落回 FastAPI 默认形状。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.extract import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

# 业务错误码到 HTTP 状态码的映射（需要时用 AppError 抛）
CODE_TO_STATUS = {
    "INVALID_INPUT": 422,
    "NOT_FOUND": 404,
    "DOC_TOO_LONG": 413,
    "INTERNAL_ERROR": 500,
}


class AppError(Exception):
    """业务异常基类。

    与 `HTTPException` 的差别：
    - `HTTPException(404, "...")` 只能给 detail 一个字符串，**塞不进 code**；
    - 我们的 AppError 直接携带 code / status / details，处理器原样转成统一响应体。

    用法（在 services 或 api 层都可以抛）：

        raise AppError("DOC_TOO_LONG", "正文 12000 字符，超过上限 8000", status=413)
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status if status is not None else CODE_TO_STATUS.get(code, 400)
        self.details: list[ErrorDetail] = details or []


def _rid(request: Request) -> str:
    """取 request_id —— 中间件一定先跑，所以这里几乎总能拿到；兜底给 "-"。"""
    return getattr(request.state, "request_id", "-")


def _body(code: str, message: str, request_id: str, details: list[ErrorDetail] | None = None) -> dict[str, Any]:
    """统一响应体的唯一出口。用 ErrorResponse 走一遍，保证形状受模型约束。"""
    return ErrorResponse(
        code=code,
        message=message[:500],
        request_id=request_id,
        details=details or [],
    ).model_dump()


def _validation_details(exc: RequestValidationError) -> list[ErrorDetail]:
    """把 pydantic 的 errors() 翻成我们的 ErrorDetail。

    `loc` 是元组，可能含 int（列表下标）。两个实测出来的处理：

    1. **去掉开头的来源前缀**。FastAPI 在请求体错误前会加 `body`，
       查询参数前加 `query`，路径参数前加 `path`，请求头前加 `header`。
       留着的话前端拿到的路径是 `body.rules.0.name`，对着表单根本对不上；
       去掉之后是 `rules.0.name` —— 直接对应请求体结构。

    2. **跨字段校验失败的 loc 是空**（`loc=()`，或去前缀后为空），
       归一成 `_model`：前端应把这条归到表单顶部，而不是某个输入框。
    """
    details: list[ErrorDetail] = []
    for err in exc.errors():
        parts = [str(p) for p in err["loc"]]
        # 剥掉来源前缀（只剥第一层，且只剥这几个已知值）
        if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
            parts = parts[1:]
        field = ".".join(parts) or "_model"
        reason = str(err["msg"]).removeprefix("Value error, ")
        details.append(ErrorDetail(field=field, reason=reason))
    return details


def register_exception_handlers(app: FastAPI) -> None:
    """把所有异常处理器挂到 app 上（main.py 里调一次）。"""

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        rid = _rid(request)
        logger.warning("app_error code=%s rid=%s msg=%s", exc.code, rid, exc.message)
        return JSONResponse(
            status_code=exc.status,
            content=_body(exc.code, exc.message, rid, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """422：请求体 / 查询参数 / 路径参数校验失败。

        这条最容易忘 —— 只注册 HTTPException 的话，输错字段仍然是 FastAPI 默认的
        `{"detail": [...]}`，前端又得写特例。
        """
        rid = _rid(request)
        details = _validation_details(exc)
        first = details[0].reason if details else "输入非法"
        logger.info("validation_error rid=%s fields=%d", rid, len(details))
        return JSONResponse(
            status_code=422,
            content=_body("INVALID_INPUT", f"{len(details)} 个字段校验失败：{first}", rid, details),
        )

    @app.exception_handler(ResponseValidationError)
    async def _response_validation_handler(request: Request, exc: ResponseValidationError) -> JSONResponse:
        """出参不符合 `response_model` —— **这是服务端 bug，不是客户端错误**。

        实测踩坑：出参模型若写了 `extra="forbid"`，服务层多返回一个键就会走到这里，
        默认表现是 500 加一段 traceback 文本。所以：
        - 出参模型用 `extra="ignore"`（这才是"过滤"），见 app/schemas/extract.py；
        - 但即便配置对了，类型不对（比如 confidence=1.5）仍会触发——
          这类错误必须让维护者看见，所以**对外 500 + 统一体，对内 ERROR 级堆栈**。

        这条处理器存在本身就是个提醒：`response_model` 是校验，不是注释。
        """
        rid = _rid(request)
        details = [
            ErrorDetail(
                field=".".join(str(p) for p in err["loc"]) or "_response",
                reason=str(err["msg"]).removeprefix("Value error, "),
            )
            for err in exc.errors()
        ]
        logger.error("response_validation_error rid=%s path=%s errors=%s",
                     rid, request.url.path, details)
        return JSONResponse(
            status_code=500,
            content=_body("INTERNAL_ERROR", "服务端返回的数据不符合契约，请携带 request_id 联系维护者", rid),
            headers={"X-Request-ID": rid},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """HTTPException + 框架内部抛的 404/405 都走这里。

        注意用 `StarletteHTTPException`（FastAPI 的 HTTPException 是它的子类）：
        只注册 FastAPI 那个的话，**路由不存在**（框架抛 starlette 版 404）不会被接管。
        """
        rid = _rid(request)
        code = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            413: "DOC_TOO_LONG",
            429: "TOO_MANY_REQUESTS",
        }.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = str(exc.detail) if exc.detail else "请求失败"
        logger.info("http_exception status=%s code=%s rid=%s", exc.status_code, code, rid)
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(code, message, rid),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底：任何没被上面接住的异常。

        - 对外只给一句话，**不回显异常内容**（防止把 SQL、路径、密钥漏出去）；
        - 对内 logger.exception 打完整堆栈，靠 request_id 关联。

        **两个实测踩坑（都写在这里，因为它们只在这一层暴露）：**

        1. `Exception` 处理器注册在 Starlette 最外层的 `ServerErrorMiddleware` 里，
           它**在所有 `@app.middleware("http")` 之外**。所以：
           - 中间件"后半"代码根本不执行（实测中间件只打印了前半）——
             想在中间件里补 `X-Request-ID` 是补不到的；
           - 中间件的耗时 `finally` 仍会跑（`call_next` 重抛），但拿不到 response。
           结论：**这个处理器必须自己写 `X-Request-ID` 响应头**，别指望中间件。

        2. TestClient 默认 `raise_server_exceptions=True` 会把异常重抛给测试代码，
           甚至不会进入这个处理器。验证脚本里必须显式 `raise_server_exceptions=False`。
        """
        rid = _rid(request)
        logger.exception("unhandled_error rid=%s path=%s", rid, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_body("INTERNAL_ERROR", "服务器内部错误，请携带 request_id 联系维护者", rid),
            headers={"X-Request-ID": rid},
        )


__all__ = ["AppError", "CODE_TO_STATUS", "register_exception_handlers"]
