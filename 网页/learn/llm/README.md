# learn/llm — LLM 接入地基（W1 周一）

本目录是"把大模型接进后端"这一课的实测记录。**代码在 `industrial-ai-platform/`，
笔记在这里** —— 因为真实调用要密钥，笔记和实验台应该能脱离服务跑。

## 文件

| 文件 | 作用 |
| --- | --- |
| [`01_params.md`](01_params.md) | **主笔记**：temperature / seed / max_tokens / stop 的参数影响表 + 温度选型结论 + 必答问题 |
| [`lab_params.py`](lab_params.py) | 四组对照实验的脚本，产出下面的 json |
| [`params_result.json`](params_result.json) | 实测原始数据，笔记里的每个数字都出自这里 |

## 复跑

```powershell
# 端点与密钥（本机网关；换云端只改这三个变量）
$env:LLM_API_KEY  = "<key>"
$env:LLM_BASE_URL = "http://127.0.0.1:8326/v1"
$env:LLM_MODEL    = "deepseek-account/deepseek-flash"

# 用服务项目的 venv（openai / httpx 都在那里）
D:\git\网页\industrial-ai-platform\.venv\Scripts\python.exe -X utf8 lab_params.py
```

`-X utf8` 是必须的：Windows 控制台默认 GBK，中文输出会乱码；
脚本自己也会把结果写进 `params_result.json`（UTF-8），以文件为准。

## 必答问题

**temperature=0 是否等于「每次都一样」？→ 不等于。** 实测 5 次出 3 种结果。
完整推理（浮点抖动 / 各家实现不一 / 服务端不可控）见
[`01_params.md` §5](01_params.md)。

## 三条最该带走的结论

1. **确定性要自己实现**，不能靠 `temperature=0` 或 `seed` —— 本网关的 seed 实测无效。
2. **`finish_reason` 比内容长度可靠**：`length` 才是截断的唯一判据。
3. **`content is None` 要当失败**，不能 `or ""` 静默成空字符串（推理模型的思维链会吃光 `max_tokens`）。

## 与本课其它部分的关系

- 配置与 client 封装在 `industrial-ai-platform/app/core/config.py` 与
  `app/core/llm/client.py`；冒烟脚本在 `industrial-ai-platform/scripts/smoke_llm.py`。
- 上一课 [`learn/fastapi_basics`](../fastapi_basics/) 讲的是"配置怎么注入到路由"，
  本课接着讲"**昂贵资源**怎么注入" —— 区别在于 Settings 可以每次重建，
  而 `AsyncOpenAI` 持有连接池，必须是进程级单例，且**不能模块级实例化**
  （import 副作用 / 密钥被固化 / 连接池无人关闭，见 `client.py` 的模块 docstring）。
- 并发部分见 [`learn/asyncio_basics`](../asyncio_basics/)：那里练的
  "限流 + 超时 + 取消"正是 W2 流式调用的保命技能。
