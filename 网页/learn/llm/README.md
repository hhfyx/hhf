# learn/llm — LLM 接入地基（W1）

本目录是"把大模型接进后端"这一课的实测记录。**代码在 `industrial-ai-platform/`，
笔记在这里** —— 因为真实调用要密钥，笔记和实验台应该能脱离服务跑。

## 文件

| 文件 | 作用 |
| --- | --- |
| [`01_params.md`](01_params.md) | **周一**：temperature / seed / max_tokens / stop 的参数影响表 + 温度选型结论 |
| [`02_function_calling.md`](02_function_calling.md) | **周二**：工具 schema / 注册表 / 单轮闭环 / 并行 tool_calls / 边界 |
| [`lab_params.py`](lab_params.py) | 周一四组对照实验的脚本，产出下面的 json |
| [`params_result.json`](params_result.json) | 周一的实测原始数据，笔记里的每个数字都出自这里 |

周二的代码与可执行验收：

| 文件（在 `industrial-ai-platform/`） | 作用 |
| --- | --- |
| `app/core/llm/tools.py` | 工具 schema（Pydantic 生成）、注册表、安全执行 `execute_tool` |
| `app/core/llm/tool_loop.py` | 闭环 `run_tool_loop`：请求 → tool_calls → 执行 → 回灌 → 二次请求 |
| `scripts/demo_tools.py` | 五格验收的可执行版本（A schema / B 注册表 / C 闭环 / D 并行 / E 边界） |
| `tests/test_tools.py` | 离线测试：全链路不联网，含"任何输入都不许抛异常"的参数化用例 |

## 复跑

```powershell
# 端点与密钥（本机网关；换云端只改这三个变量）
$env:LLM_API_KEY  = "<key>"
$env:LLM_BASE_URL = "http://127.0.0.1:8326/v1"
$env:LLM_MODEL    = "buddy/glm-5.3"        # 见下方"模型选择"

# 用服务项目的 venv（openai / httpx 都在那里）
cd D:\git\网页\industrial-ai-platform
.\.venv\Scripts\python.exe -X utf8 scripts\demo_tools.py

# 周一实验台
D:\git\网页\industrial-ai-platform\.venv\Scripts\python.exe -X utf8 ..\learn\llm\lab_params.py
```

`-X utf8` 是必须的：Windows 控制台默认 GBK，中文输出会乱码。

## 模型选择（周二实测的重要约束）

**`deepseek-account/deepseek-flash` 跑不了 Function Calling 闭环。**

它能正常返回 `tool_calls`，但第二轮回灌 `role="tool"` 消息时稳定报
`502 UNSUPPORTED_CONTENT`（裸 httpx 直接发也一样，是上游适配器限制）。
可用的替代：`buddy/glm-5.3`（本次采用）、`trae/qwen-3.5`、`qodercn/gmodel`。

> 教训：`tools=[...]` 能返回 tool_calls **不代表**支持 Function Calling。
> 完整能力是双向的 —— 还要能**接受** tool 结果消息。换任何新模型，
> 第一件事是跑一遍两轮闭环，不是验"能不能返回 tool_calls"。
> 详见 [`02_function_calling.md` §5](02_function_calling.md)。

## 必答问题

**周一：temperature=0 是否等于「每次都一样」？→ 不等于。** 实测 5 次出 3 种结果。
完整推理（浮点抖动 / 各家实现不一 / 服务端不可控）见 [`01_params.md` §5](01_params.md)。

**周二：Function Calling 是模型真的执行了函数吗？→ 不是，模型只告诉你「想调什么」，执行永远在你这侧。**
证据是 `tool_calls` 里只有名字和参数 JSON，没有任何函数体；`TOOL_REGISTRY[name](**args)`
是我们自己的 Python 在跑。这个认知直接决定 W9 Agent 的设计（注册表即权限边界、
执行即审计点、上限即安全阀）。详见 [`02_function_calling.md` 开头](02_function_calling.md)。

## 最该带走的结论

1. **确定性要自己实现**，不能靠 `temperature=0` 或 `seed` —— 本网关的 seed 实测无效。
2. **`finish_reason` 比内容长度可靠**：`length` 才是截断的唯一判据。
3. **`content is None` 要当失败**，不能 `or ""` 静默成空字符串（推理模型的思维链会吃光 `max_tokens`）。
4. **工具执行侧是不可信输入的第一道关口**：任何输入都不许抛异常，失败要作为数据回灌，
   模型才能自愈。`tool_call_id` 漏了就全盘错配。
5. **description 必须写「什么时候该用」**，只写"做什么"模型不会主动调。

## 与本课其它部分的关系

- 配置与 client 封装在 `industrial-ai-platform/app/core/config.py` 与
  `app/core/llm/client.py`；冒烟脚本在 `industrial-ai-platform/scripts/smoke_llm.py`。
- 上一课 [`learn/fastapi_basics`](../fastapi_basics/) 讲的是"配置怎么注入到路由"，
  本课周一接着讲"**昂贵资源**怎么注入" —— 区别在于 Settings 可以每次重建，
  而 `AsyncOpenAI` 持有连接池，必须是进程级单例，且**不能模块级实例化**。
- 并发部分见 [`learn/asyncio_basics`](../asyncio_basics/)：那里练的
  "限流 + 超时 + 取消"正是后续流式调用与并行工具执行的保命技能。
