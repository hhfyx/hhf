# FastAPI 核心（2026-10-23 周五 20:00–22:00）

纯学习代码，用来留痕：4 个时段的能力 + 一套成型目录 + 2 个证明脚本。
风格对齐 [`../pydantic_basics`](../pydantic_basics) 和 [`../asyncio_basics`](../asyncio_basics)：
每个 py 顶部的 docstring 就是当次笔记，本文只做索引和结论汇总。

## 运行环境

| 项 | 值 |
| --- | --- |
| 解释器 | `py -3.11`（3.11.2）—— 用到 `X \| None` 语法，**3.9 跑不了** |
| fastapi | **0.156.2** |
| starlette | 1.9.0（FastAPI 0.156 自带） |
| uvicorn | **0.54.0** |
| httpx | 0.28.1（仅 `TestClient` 用） |
| pydantic | 2.14.1 |
| pydantic-settings | 2.16.0 |

安装（**本机 PyPI 直连超时，必须用镜像**，实测阿里云可用）：

```powershell
py -3.11 -m pip install -i https://mirrors.aliyun.com/pypi/simple/ `
    --trusted-host mirrors.aliyun.com -r requirements.txt
```

> 踩过的网络坑：`pypi.org` 连接超时、清华镜像返回 403，阿里云镜像 200 正常。
> 三者都试过，别在 pypi 上反复重试浪费时间。

## 怎么跑

```powershell
cd learn/fastapi_basics
Copy-Item .env.example .env        # 必需：缺 API_KEY 会在启动时直接报错

# 起服务，然后打开 http://127.0.0.1:8000/docs
py -3.11 -m uvicorn app.main:app --reload --port 8000

# 验收（两个脚本，退出码 0 = 全过）
py -3.11 -X utf8 verify_api.py     # 103 项：路由/依赖/错误/生命周期/docs
py -3.11 -X utf8 verify_config.py  # 26 项：配置读取/优先级/单例/启动即炸
```

> ⚠️ 在 PowerShell 里 `py ... verify_api.py 2>&1 | Select-Object` 会得到 exit 1 ——
> 那是 `httpx` 的 deprecation 提示走了 stderr，被 PowerShell 当成 NativeCommandError。
> 判断真实结果用：`py -3.11 -X utf8 -W ignore::DeprecationWarning verify_api.py; $LASTEXITCODE`
> （实测 0）。

## 目录结构（验收要求）

```
app/
├── main.py                 # 组装：lifespan + 中间件 + 异常处理器 + 挂路由
├── core/
│   ├── config.py           # Settings + get_settings()（lru_cache 单例）
│   ├── deps.py             # 依赖：request_id / 配置 / registry / extractor / 分页
│   ├── errors.py           # AppError + 4 个异常处理器 → 统一错误体
│   └── middleware.py       # lifespan + request_id/耗时中间件
├── api/v1/router.py        # APIRouter(prefix="/api/v1")，9 条路由
├── schemas/extract.py      # 6 个模型（入参 forbid / 出参 ignore）
└── services/extractor.py   # 规则版抽取器（不 import fastapi）
```

| 文件 | 任务要求 | 实际做了什么 |
| --- | --- | --- |
| `main.py` | 验收结构 | 只接线：`register_middlewares` / `register_exception_handlers` / `include_router` |
| `core/config.py` | 验收结构 | `Settings`（SecretStr 掩码、prod 守卫、启动即炸）+ `get_settings()` |
| `api/v1/router.py` | `APIRouter(prefix="/api/v1")` | 9 条路由，覆盖路径/查询/Body/`response_model` 四种参数形态 |
| `schemas/extract.py` | 验收结构 | 入参 `extra="forbid"`、出参 `extra="ignore"` —— 这是踩出来的 |
| `services/extractor.py` | "先写规则版" | 正则规则表 + 启发式置信度，零 fastapi 依赖 |

## 四段必答问题

| 时间段 | 主题 | 必答问题 | 结论 |
| --- | --- | --- | --- |
| 20:00–20:30 | 路由与参数 | 路径/查询/Body/`response_model` 各自在 /docs 里长什么样？ | 见下 1 |
| 20:30–21:00 | 依赖注入 | 依赖的缓存与嵌套到底怎么算？ | 见下 2 |
| 21:00–21:30 | 错误处理 | 怎么让所有非 2xx 都是一个形状？ | 见下 3 |
| 21:30–22:00 | 生命周期与中间件 | lifespan 和中间件的边界在哪？ | 见下 4 |

### 1. 路由与参数

- **`prefix` 放在 router 上**（`APIRouter(prefix="/api/v1")`），`main.py` 只管 `include_router`。
  想去掉 v1 就等于删一个文件，不用在 main 里翻路径。
- **四类参数的写法各不相同**：
  - 路径参数 → 函数签名里直接写类型，`doc_id: str` 就是 `/documents/{doc_id}`；
  - 查询参数 → 同样写签名，`page: int = 1` 自动变查询串；加 `Query(ge=1, le=100)` 就有约束；
  - 请求体 → `payload: ExtractRequest`，Pydantic 模型自动变 `requestBody`；
  - **参数组** → 用类把一组 Query 打包成依赖（`Pagination`），`/docs` 里会展开成两个独立参数，
    不是嵌套对象 —— 这点很多人以为会嵌套。
- **`response_model` 是校验，不是注释**（本课最大的坑）：

  | 出参模型的配置 | 服务层多返回一个键 |
  | --- | --- |
  | `extra="ignore"` | 静默裁掉（**这才叫"过滤"**） |
  | `extra="forbid"` | `ResponseValidationError` → **500** |

  实测：`response_model=Forbid` 时多给一个键，直接 500；`response_model=Ignore` 时才 200 且键被裁。
  所以本项目的入参用 `forbid`（拼错立刻 422）、出参用 `ignore`（多余裁掉）。
- **`Field(description=...)` 就是接口文档**：它会原样出现在 `/openapi.json` 的 `properties` 里，
  `/docs` 的输入框下方就是这些字。写字段说明 = 写文档，不用另维护一份。
- `/docs` 是 Swagger UI，`/redoc` 是另一套渲染，`/openapi.json` 是原始 schema。
  验证脚本直接断言 `openapi.json` 的 `paths` / `$ref`，比人眼看 /docs 靠谱。

### 2. 依赖注入

**两层缓存，作用域完全不同，缺一不可：**

| 机制 | 作用域 | 效果 |
| --- | --- | --- |
| `@lru_cache` 包 `get_settings()` | **进程级** | 整个进程只有一个 Settings，`id()` 跨请求不变 |
| FastAPI 依赖缓存（`use_cache=True` 默认开） | **请求级** | 同一请求里 N 处 `Depends(f)` 只执行 1 次 |

实测（`/api/v1/deps/probe`）：
- `settings_same_object=True` —— 请求内复用；
- `settings_id` 跨请求相同 —— 进程内单例；
- `request_id` 跨请求必变 —— 这才是请求级的值。

**嵌套**：`get_extractor` → `get_registry` → `get_settings_dep`，FastAPI 递归解析整棵树，
**同一棵树里的相同依赖自动复用**。所以 `extractor` 里那次 `settings` 和路由参数里的 `settings`
是同一个对象（实测 `settings_same_object=True`）。

**`request.state` 是传参的隐形通道**：中间件设 `request.state.request_id`，依赖直接读，
不用改每个路由的函数签名。这也是为什么 `request_id` 依赖不该自己生成 —— 会跟日志里的 id 对不上。

**懒加载小技巧**：`get_extractor` 先看 `request.state.extractor`（lifespan 建的），
没有才现场造。好处是单元测试可以直接调路由函数，不用起 app。

### 3. 错误处理

任务要求 `{code, message, request_id}`。难点不是写一个处理器，而是**默认行为有三套形状**：

| 来源 | 默认响应 |
| --- | --- |
| `HTTPException` | `{"detail": "..."}` |
| `RequestValidationError` | `{"detail": [{loc, msg, type}, ...]}` |
| 未捕获异常 | 纯文本 `Internal Server Error` |

本课用 **4 个处理器**全焊成一套（`app/core/errors.py`）：

1. `AppError`（自定义）—— 能带 `code`，`HTTPException` 的 detail 只能塞字符串；
2. `RequestValidationError` → 422，把 `errors()` 翻成 `details: [{field, reason}]`；
3. `StarletteHTTPException` → 404/405 等，**必须注册 starlette 版**，因为"路由不存在"
   是框架抛 starlette 的决定，只注册 FastAPI 那个接不住；
4. `ResponseValidationError` → 500（出参不符合契约 = 服务端 bug）；
5. `Exception` → 500 兜底，对外只给一句话，对内 `logger.exception` 打全堆栈。

**`loc` 前缀要剥掉**（实测）：FastAPI 会给请求体错误加 `body` 前缀，于是前端拿到
`body.rules.0.name`，对着表单根本对不上。剥掉后是 `rules.0.name`，直接对应请求体结构。
跨字段校验失败时 `loc` 为空，归一成 `_model`（前端应归到表单顶部）。

**验证方式**：把 5 种错误响应的键集合都取出来，断言 `len(keys) == 1` 且等于四件套 ——
这比逐个比对字段更能证明"真的统一了"。

### 4. 生命周期与中间件

**lifespan**（`@asynccontextmanager`）：

```python
@asynccontextmanager
async def lifespan(app):
    reg = ResourceRegistry.load(...)   # yield 之前 = 启动
    yield {"registry": reg}            # 这个 dict 进 request.state
    reg.close()                        # yield 之后 = 关闭
```

- **yield 出来的字典进 `request.state`，不进 `app.state`**（实测：`request.state.registry`
  拿得到，`app.state.registry` 是 None）。想挂 app 层面就得显式 `app.state.x = ...`。
- 比 `@app.on_event("startup")` 好在：一对 `async with` 表达"获取 + 释放"，
  异常时也能保证释放；`on_event` 已废弃且两个钩子容易漏配对。

**中间件的真实边界（本课最反直觉的一条，实测确认）**：

```
ServerErrorMiddleware      ← Exception 处理器在这层，绕开所有用户中间件
  └─ request_context_middleware   ← 我们的中间件
       └─ ExceptionMiddleware     ← AppError/422/HTTPException/ResponseValidationError
            └─ 路由
```

推论：
- `AppError` / `422` / `HTTPException`：处理器在中间件**之内**，响应正常穿过 `call_next`
  → 中间件能补 `X-Request-ID`；
- **未捕获异常**：`Exception` 处理器在最外层，中间件的"后半"根本不执行
  （实测只打印了"前半"，`X-MW` 头补不上）→ **必须由那个处理器自己写响应头**。

所以本项目：中间件给正常响应补头，`Exception` 处理器自己写头，两条路径都覆盖。
一开始我写了两个中间件（外层补头 + 内层兜底），实测发现内层也补不上——
这不是"中间件数量"的问题，是框架层级边界。

**耗时日志放 `finally`**：报错请求同样有耗时记录，`status` 变量默认 500 就是这个用途。

## 验收

任务要求：`app/` 目录结构成型（`main.py` / `core/config.py` / `api/v1/router.py` /
`schemas/extract.py` / `services/extractor.py`），规则版 extractor。

**实测结果**（两个脚本，共 129 项断言）：

```
verify_api.py    → 通过 103 项，失败 0 项   exit=0
verify_config.py → 通过  26 项，失败 0 项   exit=0
```

覆盖矩阵：

| 组 | 内容 | 项数 |
| --- | --- | --- |
| A | lifespan 启动加载 / 关闭释放 / `request.state` 注入 | 6 |
| B | prefix / 路径参数 / 查询参数（含约束）/ Body / 嵌套路径 404 | 13 |
| C | Body 校验 + `response_model` 过滤 + 422 details 定位 + 413 | 14 |
| D | 依赖缓存（请求内/跨请求）/ 嵌套 / 单例 / 头部依赖 / rid 一致性 | 11 |
| E | 5 种错误统一体 + 形状一致性 + 不泄露内部信息 | 12 |
| F | `/docs`、`/redoc`、`/openapi.json` 的 title/version/paths/`$ref`/参数展开 | 14 |
| G | SecretStr 掩码 / 进程内单例 / .env 生效 | 6 |
| H | 分层（AST 查 import）/ 脱离 HTTP 直接调用服务层 | 10 |

**这个脚本真的抓到过 2 个 bug**（都是写完才发现，不是设计时想到的）：

1. **`response_model` + `extra="forbid"` = 500**。`/extract/raw` 故意多返回两个键，
   原以为会被裁掉，结果抛 `ResponseValidationError`。改成出参 `ignore` 才对。
2. **`Exception` 处理器绕过中间件**。原以为中间件能补 `X-Request-ID`，实测补不上
   （中间件"后半"根本没跑）。改成处理器自己写头。

两条都写进了代码注释，因为这类"想当然"的错误，抄代码的人最容易原样再踩一次。

## 踩坑速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `/docs` 里 422 显示 `HTTPValidationError` | 没挂 `responses={422: {"model": ErrorResponse}}` | 路由上显式声明 |
| 路由不存在时 404 还是 `{"detail":...}` | 只注册了 FastAPI 的 `HTTPException` | 注册 `StarletteHTTPException` |
| 出参多一个键就 500 | 出参模型 `extra="forbid"` | 出参用 `extra="ignore"`，入参才 forbid |
| 报错响应没有 `X-Request-ID` | `Exception` 处理器在中间件之外 | 处理器自己写响应头 |
| 前端拿到的错误字段是 `body.rules.0.name` | FastAPI 加了来源前缀 | 剥掉 `body/query/path/header` 首层 |
| 改了 `.env` 但服务没变 | `lru_cache` 已缓存 | `get_settings.cache_clear()` 或重启 |
| `py ... 2>&1 \| Select-Object` 得 exit 1 | PowerShell 把 stderr 当错误 | 看 `$LASTEXITCODE`，或 `-W ignore::DeprecationWarning` |
| `pip install` 卡住 / 403 | pypi 超时、清华 403 | 用阿里云镜像 |
| `TestClient` 看不到 500 统一体 | 默认 `raise_server_exceptions=True` 会重抛 | 构造时传 `False` |
| `import app.main` 就报缺 API_KEY | 配置在模块级解析（有意为之，早炸） | 先 `Copy-Item .env.example .env` |

## 与上一课的衔接

| 上一课（pydantic_basics） | 这一课（fastapi_basics） |
| --- | --- |
| `BaseSettings` 能读 `.env` | 它怎么被 `Depends` 注入、缓存几层 |
| 模型校验非法输入 | 模型怎么变成 `/docs` 里的 schema |
| `ValidationError.errors()` 的结构 | 怎么翻成统一的 `{code, message, request_id}` |
| `get_settings()` + `lru_cache` | 进程级缓存 vs 请求级缓存的分工 |

**没有重复上一课的内容**：字段校验规则（`ge/le/min_length/field_validator`）直接复用，
本课只加"HTTP 那一层"该管的东西。

## 下一步

- `services/extractor.py` 换成接大模型：`ResourceRegistry` 里换模型 client，
  业务入口签名不变（这正是分层的价值）；
- 加鉴权依赖（`Depends(require_api_key)`）+ 限流中间件；
- 把 `Pagination` 抽成通用分页响应模型（`{items, total, page, size}`）；
- 加 `pytest` 测试替代现在的 `verify_*.py` 脚本（脚本只适合一次性验收）。

## 资源

- FastAPI 官方中文文档：<https://fastapi.tiangolo.com/zh/>
  - *Tutorial - Dependencies*（缓存与嵌套的权威说明）
  - *Advanced - Middleware* / *Lifespan Events*
  - *Advanced - Response Model*（出参过滤的语义）
- Starlette 中间件顺序：搜 `ServerErrorMiddleware` / `ExceptionMiddleware`
- OpenAPI 3.1 spec（`/openapi.json` 的字段含义）
