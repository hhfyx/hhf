# -*- coding: utf-8 -*-
"""services：业务逻辑。这一层**不 import fastapi**。

好处很实际：`python -m app.services.extractor` 能直接跑，也能被 CLI、后台任务、
单元测试复用，不用起 HTTP 服务。HTTP 那套（状态码、Depends、HTTPException）
全部留在 api/ 层。

这是本课"分层"唯一有牙齿的约束：打开 extractor.py 全文搜索 `fastapi`，结果为 0。
"""

from .extractor import ResourceRegistry, RuleBasedExtractor, RuleExtractReport

__all__ = ["ResourceRegistry", "RuleBasedExtractor", "RuleExtractReport"]
