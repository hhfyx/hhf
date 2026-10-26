# Pydantic v2 基础（2026-10-22 周四 20:00–22:00）

纯学习代码，用来留痕：4 个可独立运行的 demo + 3 个业务模型 + 2 个证明脚本。
风格对齐 [`../asyncio_basics`](../asyncio_basics)：每个 py 顶部的 docstring 就是当次笔记，本文只做索引和结论汇总。

## 运行环境

| 项 | 值 |
| --- | --- |
| 解释器 | `py -3.11`（3.11.2）—— 用到 `X \| None` 语法，**3.9 跑不了** |
| pydantic | **2.14.1** |
| pydantic-settings | **2.16.0** |
| 安装 | `py -3.11 -m pip install "pydantic>=2" "pydantic-settings>=2"` |

> 本机默认 `python` 是 3.9.23，**既没装 pydantic、也用不了 `X | None` 语法**（3.10+ 才有），
> 所以命令里一律显式写 `py -3.11`。实测 `py -3.9 demo1_base_model.py` 直接 `ModuleNotFoundError`。
> 建议带 `-X utf8`，避免 Windows 终端把中文输出成乱码。

## 怎么跑

```powershell
cd learn/pydantic_basics

# 四段课程 demo（各自独立，可单独跑）
py -3.11 -X utf8 demo1_base_model.py          # 20:00-20:35 基础模型
py -3.11 -X utf8 demo2_validators.py          # 20:35-21:05 校验器 + 报错格式
py -3.11 -X utf8 demo3_nested_serialize.py    # 21:05-21:30 嵌套 + 序列化
py -3.11 -X utf8 demo4_settings_config.py     # 21:30-22:00 配置管理

# 验收
py -3.11 -X utf8 verify_rejects.py            # 3 个业务模型，非法输入全部被拒（24 项断言）
py -3.11 -X utf8 verify_config.py             # app/core/config.py 读 .env（17 项断言）
```

两个 `verify_*.py` 退出码 0 = 全过；任一条不过会打印是哪条并以非 0 退出。六个文件均已实测 exit=0。

## 文件清单

| 文件 | 作用 |
| --- | --- |
| `demo1_base_model.py` | BaseModel、`Field(description=, ge=, le=, min_length=, max_length=)`、`str \| None = None`、lax 转换、赋值不校验 |
| `demo2_validators.py` | `@field_validator`（含 `mode="before"`）、`@model_validator(mode="after")`、`ValidationError` 的两层结构、v1 写法告警 |
| `demo3_nested_serialize.py` | 嵌套模型、`list[Model]`、`model_dump()` 两种 mode、`model_dump_json()`、`model_validate_json()`、`ConfigDict(extra="forbid")`、alias |
| `demo4_settings_config.py` | `BaseSettings` 读 `.env`、优先级、`SecretStr`、启动时校验、`lru_cache` 单例 |
| `app/core/config.py` | **验收要求的 `app/core/config.py`**：`Settings` + `get_settings()` |
| `app/core/models.py` | **验收要求的 3 个业务模型**：`ExtractRequest` / `ExtractResult` / `ErrorResponse` |
| `verify_rejects.py` | **验收要求的"证明非法输入被拒"的 py** |
| `verify_config.py` | 证明 `config.py` 正确读 `.env` + 配置错误启动即拒 |
| `.env.example` | 配置模板，复制成 `.env` 使用（`.env` 已在 `.gitignore` 里） |

## 四段必答问题

| 时间段 | demo | 必答问题 | 结论 |
| --- | --- | --- | --- |
| 20:00–20:35 | `demo1` | `Field(ge=...)` 什么时候、由谁执行？ | 见下 1 |
| 20:35–21:05 | `demo2` | 单字段/跨字段校验器怎么写，失败报错长什么样？ | 见下 2 |
| 21:05–21:30 | `demo3` | 嵌套错误怎么定位、dump 的两种模式差别在哪？ | 见下 3 |
| 21:30–22:00 | `demo4` | .env / 环境变量 / 传参 / 默认值，谁说了算？ | 见下 4 |

### 1. 基础模型

- **执行时机**：约束声明在类上，校验发生在**实例化**（`Model(...)`、`model_validate(...)`、`model_validate_json(...)`）时，由 pydantic-core（Rust）跑一遍。不是定义类时，也不是访问属性时。
- **lax 模式**：`"42"` → `42`、`"2026-10-22"` → `date` 自动转换，但 `"十二"` → int 报 `int_parsing`。宽松 ≠ 不校验。
- **默认 `extra="ignore"`**：多传/拼错的字段被**静默丢弃**——`DocMeta(doc_id="d", page_count=1, typo_pagecount=99)` 不报错。这是最常见的"字段名写错了却没人告诉我"。要拦就 `ConfigDict(extra="forbid")`（demo3 起全用 forbid）。
- **默认赋值不校验**：`m.count = -5` 直接生效，实例进入非法状态。要管住开 `validate_assignment=True`。
- **可变默认值用 `default_factory=list`**，别写 `tags: list = []`。
- `Field(description=..., ge=..., le=...)` 同时喂给 `model_json_schema()`，前端表单和 OpenAPI 文档都靠它。

### 2. 校验器与报错格式

写法（v2，**不是** v1 的 `@validator`）：

```python
@field_validator("字段")          # 单字段，默认 mode="after"（拿到已转换的值）
@classmethod
def _f(cls, v): ...              # 必须 return v

@model_validator(mode="after")    # 跨字段，签名 (self)
def _m(self): ...                # 必须 return self
```

实测得到的报错语义：

- `ValidationError` 是 `ValueError` 子类，`except ValueError` 也能兜住。
- 两层结构：`str(exc)` 给人看（多行，带 errors.pydantic.dev 的 URL）；`exc.errors()` 给程序看（`type` / `loc` / `msg` / `input` / `url`）。
- 字段级失败 → `loc=('字段名',)`；跨字段失败 → **`loc=()`**，前端应归到表单顶部而不是某个输入框。
- **字段级错误会一起收集**（多个字段一次报完）；
- **但只要有一个字段级失败，`model_validator(mode="after")` 就不执行** —— 实例没构造出来，跨字段规则无从判定。所以"多次字段错"和"跨字段错"不会同时出现在一次 errors() 里。这点很容易想当然写错，demo2 第 4 节专门演示了。
- 自己 `raise ValueError("x")` → `msg="Value error, x"`。做对外错误体时用 `msg.removeprefix("Value error, ")` 洗掉前缀。
- **v1 写法还能 import，但会告警**：`@validator` 和 `class Config` 在 2.14 上各抛一条 `PydanticDeprecatedSince20`（实测两个都报）。旧教程照抄会一路飘黄。

### 3. 嵌套与序列化

- **嵌套错误的 loc 是完整路径**：`('rules', 1, 'name')` = 外层字段 + 列表下标 + 内层字段。前端要高亮到具体某一行就靠它。
- **`extra="forbid"` 不会自动往下传**：`StrictParent` 上的 forbid 只管父层；子模型不写 `model_config` 就仍是默认 `ignore`，子层多传字段照样被静默丢弃。整棵树要严格，要么每个模型都写，要么抽基类继承。
- **`model_dump()` 默认 `mode="python"`**：`datetime` 还是 `datetime`，直接丢 `json.dumps` 会 `TypeError`；
  **`model_dump(mode="json")`** 出 ISO 字符串；**`model_dump_json()`** 直接出 str（更快，中间不生成 dict）。
- **`model_validate_json(s)`** 直接在 JSON 文本上校验，脏数据入口用它；非法 JSON 文本也抛 `ValidationError`（`type=json_invalid`），不是 `JSONDecodeError`。
- `exclude_none=True` **只作用于模型字段，不会钻进 dict 内部**去清 `fields` 里的 `None`（实测踩到）。
- 联合类型（`str | int | float | None`）失败时，**每个分支各报一条**，`loc` 末尾带分支名：`('fields','x','str')`。做断言只能前缀匹配。
- 内部 snake_case、对外 camelCase：`alias=` + `populate_by_name=True`，序列化时 `by_alias=True`。

### 4. 配置管理

- **优先级：构造参数 > 真实环境变量 > `.env` 文件 > 字段默认值**。生产机 `export APP_ENV=prod` 就能盖掉仓库里的 `.env`，不用改代码也不用改 .env。
- 键名默认**大小写不敏感**：`API_KEY` / `api_key` / `Api_Key` 都认。
- **`SecretStr` 是给密钥的**：`repr()`、`model_dump()`、`model_dump_json()`、日志里全是 `**********`，只有 `.get_secret_value()` 给明文。日志里一把 key 就是这么漏的。
- **配置错误在启动时炸**：缺 `API_KEY` → `type=missing`；`LOG_LEVEL=verbose` → `literal_error`；`REQUEST_TIMEOUT=0` → `greater_than`。早炸好过半夜炸。
- **`extra="ignore"` vs `"forbid"`**：ignore 让 `.env` 里遗留的旧键不致命；forbid 让未声明/拼错的键直接拒绝启动，报 `loc=('legacy_db_url',)`。团队项目更推荐 forbid。
- **`@lru_cache` 包 `get_settings()`**：全进程只解析一次；测试里用 `get_settings.cache_clear()` 重载。

## 验收

任务要求：写 3 个业务模型（`ExtractRequest` / `ExtractResult` / `ErrorResponse`），每个至少 1 条校验规则，且有一个 py 能证明非法输入被拒。

**模型**（`app/core/models.py`）：

| 模型 | 校验规则 |
| --- | --- |
| `ExtractRequest` | `doc_id` 1-64 字符；`rules` 至少 1 条；`rules[].name` 不重复（跨字段）；`rules[].name` 必须小写 snake_case；**结束日期不能早于开始日期**（跨字段，任务点名用例）；`extra="forbid"` |
| `ExtractResult` | `confidence` ∈ [0,1]；`finished_at >= started_at`（跨字段）；`fields` 的 key 必须⊆`allowed_fields`（拦模型幻觉字段）；`fields` 值只允许 `str/int/float/None`；`extra="forbid"` |
| `ErrorResponse` | `code` 必须全大写且只含 `A-Z/0-9/_`；`message` 1-500 字符；`retryable=True` 时必须给 `retry_after_s > 0`（跨字段）；`details` 最多 20 条；`extra="forbid"` |

**证明**（`verify_rejects.py`）：每条规则一个反例，断言抛 `ValidationError` 且 `loc`/`type` 命中预期；再给每个模型一个合法输入断言通过（避免"全都拒"的假阳性）。实测输出：

```
通过 24 项，失败 0 项
全部通过：3 个业务模型的非法输入都被正确拒绝。
```

其中"结束日期早于开始日期"这条的实测报错：

```
loc=() type=value_error 错误数=1
Value error, 结束日期不能早于开始日期：started_on=2026-10-22, ended_on=2026-10-01
```

**这个脚本真的抓到过 bug**：`ExtractRequest.started_on` 第一版声明成了 `str | None`，
于是 `"2026/10/01"` 这种脏值被原样放过去，`verify_rejects.py` 当场报"本应被拒但通过了"。
改成 `date | None` 后，`date_from_datetime_parsing` 正确拒绝，且"结束早于开始"变成真正的日期比较而不是字符串字典序。
—— 这就是"有一个 py 能证明非法输入被拒"的价值：人眼读十遍，不如断言跑一遍。

## 踩坑速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 字段名拼错却无声无息 | 默认 `extra="ignore"` | 加 `ConfigDict(extra="forbid")` |
| `json.dumps(model.model_dump())` 报 `TypeError` | `mode="python"`，datetime 没序列化 | 用 `mode="json"` 或 `model_dump_json()` |
| 跨字段规则没触发 | 有字段级校验先失败了，`mode="after"` 不执行 | 先保证字段级通过；或用 `mode="before"` 拿原始 dict 判 |
| 子模型多传字段没被拦 | `extra="forbid"` 不向下继承 | 每个子模型都写，或抽公共基类 |
| 赋值后模型变非法 | 赋值校验默认关闭 | `ConfigDict(validate_assignment=True)` |
| 密钥出现在日志里 | 字段声明成了 `str` | 用 `SecretStr`，取值显式 `.get_secret_value()` |
| 生产误用测试 key | 没人管"环境 × 密钥"的组合 | `@model_validator(mode="after")` 按 `app_env` 卡住 |
| 日期规则按字符串比出了怪结果 | 声明成 `str` 而不是 `date` | 用 `date \| None`，比较才是日期语义 |

## 资源

- 官方文档：Pydantic v2 *Models* / *Validators* / *Serialization* / *Migration Guide (v1 → v2)*
- pydantic-settings：*Settings management*（优先级表就在这页）
- 迁移检查表：搜 `PydanticDeprecatedSince20`，把 `@validator` / `class Config` 一次性清干净
