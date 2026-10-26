# -*- coding: utf-8 -*-
"""依赖注入（任务 20:30–21:00）。

任务是"抽一个「读取配置 + 生成 request_id」的依赖，理解依赖的缓存与嵌套"。
这里把它拆成 4 个可组合的依赖，正好覆盖三个必须理解的点：

    [依赖 1] get_request_id      —— 从 request.state 取（中间件已生成）
    [依赖 2] get_settings_dep    —— 读配置（lru_cache 单例）
    [依赖 3] get_extractor       —— 嵌套依赖：要 registry，registry 又要 settings
    [依赖 4] PageQuery           —— 可复用参数组（路径/查询参数的"依赖化"）

**三个必须理解的点：**

1. **缓存（use_cache=True，默认开）**
   同一请求里 `Depends(get_settings_dep)` 出现 N 次，只执行 1 次；不同请求各执行 1 次。
   注意两个缓存层级不同：`lru_cache` 是**进程级**（跨请求同一个对象），
   FastAPI 的依赖缓存是**请求级**（同一请求内复用）。两个都要，缺一不可 ——
   只有 lru_cache：同一请求内多次调用不会重算，但拿不到"这次请求专属"的值（如 rid）；
   只有请求级缓存：每个请求都重新解析配置，白开 .env。

2. **嵌套**
   `get_extractor` 依赖 `get_registry`，`get_registry` 依赖 `get_settings_dep`。
   FastAPI 会递归解析整棵依赖树，同一层的相同依赖自动复用（缓存在整棵树内生效）。

3. **`request.state` 是传参的隐形通道**
   中间件设好 `request.state.request_id`，依赖直接读 —— 不用改路由函数签名，
   也不用把 rid 一路手动往下传。

懒加载小技巧：`get_extractor` 里先从 `request.state` 拿（lifespan 已经建好），
拿不到才现场构造 —— 这样单元测试可以直接调用路由函数，不用起 app。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, Path, Query, Request

from app.core.config import Settings, get_settings
from app.services.extractor import ResourceRegistry, RuleBasedExtractor

# ============================================================ 1) request_id
def get_request_id(request: Request) -> str:
    """读中间件写进 `request.state` 的 id。

    为什么不在依赖里现生成？因为**中间件先跑**，且异常处理器也要读同一个 id。
    依赖里生成会得到和日志不一致的第二个 id —— 典型的"日志里有、响应里没有"。
    """
    return getattr(request.state, "request_id", "-")


RequestIdDep = Annotated[str, Depends(get_request_id)]


# ============================================================ 2) 配置
def get_settings_dep() -> Settings:
    """配置依赖。

    包一层而不是直接把 `get_settings` 丢进 Depends，有两个好处：
    - 语义清晰：路由里看到 `Depends(get_settings_dep)` 就知道"这里要配置"；
    - 好替换：测试里 `app.dependency_overrides[get_settings_dep] = lambda: fake`
      一句就换掉，不用动 lru_cache。
    """
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


# ============================================================ 3) 资源 + 抽取器（嵌套）
def get_registry(request: Request, settings: SettingsDep) -> ResourceRegistry:
    """嵌套依赖第 1 层：registry 要 settings。

    lifespan 已经把 registry 挂在 `request.state`（yield 出来的 dict 会进 state），
    这里优先复用；没有就现场建 —— 后者只在测试里发生。
    """
    registry = getattr(request.state, "registry", None)
    if registry is not None:
        return registry
    return ResourceRegistry.load(settings)


RegistryDep = Annotated[ResourceRegistry, Depends(get_registry)]


def get_extractor(request: Request, registry: RegistryDep, settings: SettingsDep) -> RuleBasedExtractor:
    """嵌套依赖第 2 层：extractor 要 registry + settings。

    这棵树的形状（FastAPI 递归解析，自底向上）：

        get_extractor
        ├── get_registry
        │    ├── settings  (get_settings_dep)
        │    └── request   (框架注入)
        ├── get_settings_dep   ← 和上面那层是**同一个实例**（缓存命中）
        └── request

    实测：一次请求里 get_settings_dep 只执行 1 次，get_registry 也只执行 1 次。
    """
    extractor = getattr(request.state, "extractor", None)
    if extractor is not None:
        return extractor
    return RuleBasedExtractor(registry=registry, version=settings.extract_model)


ExtractorDep = Annotated[RuleBasedExtractor, Depends(get_extractor)]


# ============================================================ 4) 可复用参数组
class Pagination:
    """分页参数组 —— 用类把一组 Query 打包成"一个依赖"。

    等价于在每个路由上手写 `page: int = Query(...), size: int = Query(...)`，
    但写一次就能到处复用，而且 /docs 里会展开成两个独立参数（不是嵌套对象）。
    """

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
        size: int = Query(default=10, ge=1, le=100, description="每页条数，1-100"),
    ) -> None:
        self.page = page
        self.size = size
        self.offset = (page - 1) * size

    def as_dict(self) -> dict[str, Any]:
        return {"page": self.page, "size": self.size, "offset": self.offset}


PaginationDep = Annotated[Pagination, Depends(Pagination)]


# ============================================================ 5) 头部依赖（演示"取显式请求头"）
def get_client_name(x_client_name: Annotated[str | None, Header(alias="X-Client-Name")] = None) -> str:
    """从请求头取调用方标识，缺省 `anonymous`。

    `Header(alias=...)` 允许大写带连字符（HTTP 头本来就大小写不敏感），
    不写 alias 的话 FastAPI 会把参数名 `client_name` 转成 `client-name`。
    """
    return x_client_name or "anonymous"


ClientNameDep = Annotated[str, Depends(get_client_name)]


__all__ = [
    "ClientNameDep",
    "ExtractorDep",
    "Pagination",
    "PaginationDep",
    "RegistryDep",
    "RequestIdDep",
    "SettingsDep",
    "get_client_name",
    "get_extractor",
    "get_registry",
    "get_request_id",
    "get_settings_dep",
]
