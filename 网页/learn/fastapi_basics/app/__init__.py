# -*- coding: utf-8 -*-
"""文档抽取服务 · FastAPI 核心课（2026-10-23 周五 20:00–22:00）。

验收要求：app/ 目录结构成型。

    app/
    ├── main.py               # 组装：lifespan + 中间件 + 异常处理器 + 挂路由
    ├── core/config.py        # 配置对象（可被 Depends 注入）
    ├── core/deps.py          # 依赖：request_id / 配置 / 抽取器
    ├── core/errors.py        # 统一错误响应体 {code, message, request_id}
    ├── core/middleware.py    # 中间件：request_id + 耗时
    ├── api/v1/router.py      # APIRouter(prefix="/api/v1")
    ├── schemas/extract.py    # 请求 / 响应模型（response_model 靠它）
    └── services/extractor.py # 规则版抽取器（先不接大模型）

分层规则（本课唯一要背的东西）：

    api/      → 只做 HTTP 的事：解析参数、注入依赖、挑状态码、选 response_model
    schemas/  → 只描述"对外长什么样"
    services/ → 只做业务：不 import fastapi，可被 CLI / 任务队列直接复用
    core/     → 横切关注点：配置、依赖、错误、中间件
"""
