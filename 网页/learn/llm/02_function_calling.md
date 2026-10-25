# 02 · Function Calling：模型只说要调什么，执行永远在你这侧

> W1 周二 20:00–22:00 的实测记录。代码在
> `industrial-ai-platform/app/core/llm/tools.py`（工具层）与
> `tool_loop.py`（闭环），可执行验收是
> `industrial-ai-platform/scripts/demo_tools.py`。
> 全部消息数组、错误体都是**真跑出来的**。

---

## 必答问题：Function Calling 是模型执行了函数吗？

**不是。模型只输出「我想调什么」这个意图数据结构，执行 100% 在你这侧。**

这是本次实测最直接的证据 —— 整个闭环里，模型这辈子没见过 `get_weather` 的代码：

```
[1] role=user      "北京现在天气怎么样？"
[2] role=assistant tool_calls=[{id: call_675..., name: get_weather, arguments: '{"city":"北京"}'}]
                   ↑ 模型只产出这段 JSON，它没有、也不能执行
[3] role=tool      "{"ok":true,"result":{"temperature":12.0,...}}"     ← 我方代码执行后回灌
[4] role=assistant "北京现在的天气是多云，气温约 12°C。"                 ← 模型只是读结果写总结
```

`tool_calls` 里连函数体都没有，只有**名字 + 参数 JSON 字符串**。那行
`TOOL_REGISTRY[name](**args)` 是我们自己的 Python 在跑。

所以"Function Calling"这个名字是有误导性的。更准确的说法是
**Model-Controlled Dispatch**：模型输出一个可校验的"调用意图"，我们决定要不要执行、怎么执行。

### 这个认知直接决定 W9 Agent 的设计

| 如果以为"模型会执行函数" | 实际上 |
| --- | --- |
| 注册什么工具都能被安全调用 | 模型会幻觉出**你从没注册过**的工具名（本次 E3 实测 `send_email`） |
| 参数一定是模型按 schema 生成的 | 参数可能是坏 JSON、类型错、缺必填（四类失败都要防） |
| 权限在工具内部检查就够 | 权限必须在**注册表这一层**做，因为"选哪个工具"是模型说了算 |
| 危险操作靠 prompt 拦住 | prompt 拦不住，必须在执行侧不提供这个工具 / 不给这个权限 |
| 审计日志记模型调用即可 | 要记的是**我们执行了哪次调用、用了什么参数** |

一句话：**模型是"提议者"，我们是"审批者 + 执行者"**。把执行侧当成不可信输入的第一道关口，
W9 的 Agent 才不会变成一个能被 prompt 注入随意调用的后门。

---

## 1. 工具 schema：description 是模型选工具的唯一依据

本课最容易写敷衍的地方就是 description。只写"查询天气"是**不够**的 ——
模型遇到"北京冷不冷"很可能直接凭训练数据猜一个温度，因为它不认为必须调工具。

对比一下两种写法会导出的行为差异：

| description 写法 | 模型行为 |
| --- | --- |
| `"查询天气"` | 明确问"北京天气怎么样"会调；但"北京冷不冷""明天要带伞吗"可能自己编 |
| 写清触发场景 + 反面约束（本次采用） | 上述都调；`"1+1 等于几"` 这种明确要求不用工具时才不调 |

本次 `get_weather` 的 description 结构（四段，每段有明确作用）：

1. **做什么**：查询指定城市的实时天气和温度
2. **什么时候用**：现在/今天的天气、气温、多少度、冷不冷、热不热、要不要带伞 —— 把用户的**各种问法**都列出来
3. **能力边界**：支持中英文城市名；只返回单个当前值，不查历史/预报
4. **反面约束**：不要凭常识替用户猜温度，凡是要给出具体温度都必须调用

第 3、4 段经常被省掉，但它们是减少"该调不调"和"不该调乱调"的关键。

### 约束写在类型里，比写在 description 里可靠

`unit` 用 `Literal["celsius","fahrenheit"]` 而不是 `str`：schema 里自动带上 `enum`，
模型看到枚举就不会瞎编 `"C"` / `"摄氏度"`。description 只是"建议"，`enum` 是**硬约束**。

**参数 schema 由 Pydantic 自动生成，不手写**（`model_json_schema()`）。
手写必然和校验模型漂移，而漂移的症状特别坑：模型按 schema 生成参数、校验模型却拒绝 ——
报错指向"参数不对"，但真正的错在 schema。

---

## 2. 注册表 + 安全执行：这是模型与真实世界之间唯一的闸门

`execute_tool()` 的一条铁律：**任何输入都不许抛异常**，失败也返回结构化 dict。

理由是上面那个认知的直接推论 —— 模型给的这一切都是**不可信输入**。
如果 `TOOL_REGISTRY[name]` 直接下标取值，一个幻觉出来的 `send_email` 就是 `KeyError`，
整个请求 500，而模型连"我错了、我换个工具"的机会都没有。

六类失败，实测输出（`demo_tools.py` B 段原样打印）：

| 情况 | `kind` | 实测回灌给模型的内容 |
| --- | --- | --- |
| 正常 | — | `{"ok":true,"result":{"city":"北京","temperature":12.0,...}}` |
| 参数类型错 | `invalid_arguments` | `{"error":{"message":"参数不符合工具签名","fields":[{"field":"a","reason":"Input should be a valid number...","got":"abc"}]}}` |
| 参数 JSON 坏 | `invalid_arguments_json` | `{"message":"参数不是合法 JSON：Expecting property name enclosed in double quotes（位置 1）","raw":"{bad"}` |
| 工具名不存在 | `unknown_tool` | `{"message":"没有名为 'send_email' 的工具","available_tools":["calculate","get_weather"]}` |
| 除零 | `division_by_zero` | `{"message":"除数不能为 0"}` |
| 无此城市 | `city_not_found` | `{"message":"没有城市 '火星' 的天气数据；当前支持：..."}` |

两个设计细节：

- **`unknown_tool` 必须带上 `available_tools`**。只说"没有这个工具"模型会继续瞎猜；
  告诉它可选项，它下一轮就能选对。
- **只回灌 `field` / `reason` / `got`，不回灌 Pydantic 的完整 `str(exc)`**。
  那个多行文本会吃掉大量 token，而且模型并不需要 `loc` 的完整路径。

另外有意**不**catch 裸 `Exception`：handler 里真正的 bug（拼写错、`NoneType`）必须崩。
在这里 catch-all 会让 bug 伪装成"工具业务失败"，模型还会一本正经地向用户解释
一个根本不存在的业务错误 —— 那比 500 更难排查。

---

## 3. 单轮闭环：三个不会报错、但会毁掉结果的地方

标准骨架（本课的关键代码）：

```python
messages.append({"role": "assistant", "tool_calls": message.tool_calls})   # ① 必须带 id
results = execute_tool_calls(message.tool_calls)                          # ② 顺序与 calls 一致
messages.extend(build_tool_messages(message.tool_calls, results))          # ③ 按 id 配对
```

| 坑 | 后果 |
| --- | --- |
| ① 漏掉 assistant 的 `tool_calls` | 后续 `role="tool"` 成了"没有出处的回答"，多数服务直接 400 |
| ② 执行顺序和 `tool_calls` 不一致 | `tool_call_id` 与内容错配，模型看到"北京的结果挂在上海的 id 上"，答案莫名其妙 |
| ③ `content` 塞 dict 而不是字符串 | 协议要求 string；`json.dumps(..., ensure_ascii=False)` 还能让中文在日志里可读 |

`tool_call_id` 是第 ③ 步唯一不能漏的字段。漏了会得到：

```
400 Invalid parameter: messages with role 'tool' must be a response to a
    preceding message with 'tool_calls'
```

或者更糟 —— 不报错，模型把结果张冠李戴。

---

## 4. 并行 tool_calls：一次返回多个，必须按 id 一一配对

问"北京和上海今天天气分别怎么样"，模型**一次**返回 2 个 tool_call：

```
[2] role=assistant
     tool_call id=call_cbc9e1c390c6495389d55362   name=get_weather  arguments={"city":"北京"}
     tool_call id=call_a3f248bd2ff044328d35b366   name=get_weather  arguments={"city":"上海"}
[3] role=tool   tool_call_id=call_cbc9e1c390c6495389d55362   (北京的结果)
[4] role=tool   tool_call_id=call_a3f248bd2ff044328d35b366   (上海的结果)
```

**并行是模型自己决定的，不是我们并发调用的**。我们只是把这一批**顺序**执行完再回灌。
本课不引入 `asyncio.gather` 是有意的：两个假数据工具没有 IO，并发没有收益，
反而让"顺序必须与 tool_calls 一致"这条约束变得难以验证。真实系统里工具会打网络，
那时才值得并发 —— 但 id 配对的要求完全一样。

`demo_tools.py` 的 D 段做了显式核对，输出 `一一配对: True`。
这一步很值：id 错配在多数情况下**不报错**，只表现成"答案莫名其妙"，靠肉眼翻日志很难发现。

---

## 5. 本机网关的坑：`role=tool` 回灌被拒（重要）

**这是今天最大的意外，也是最该记住的一条。**

用 `deepseek-account/deepseek-flash` 跑闭环时，第二轮稳定报：

```
502 UNSUPPORTED_CONTENT
{"error":{"message":"DeepSeek Messages cannot represent user/tool-result
 content tool-result","type":"server_error","code":"UNSUPPORTED_CONTENT"}}
```

排查过程（每一步都排除了一个错误假设）：

| 试的变体 | 结果 | 排除了什么 |
| --- | --- | --- |
| `content` 是 JSON 字符串 | 502 | 不是 content 格式问题 |
| `content` 是 parts 数组 `[{type,text}]` | 502 | 不是"要不要数组"的问题 |
| 不带 `content` 键 | 502 | 不是空 content 的问题 |
| assistant 消息不带 `content` | 502 | 不是我多传了 `content` |
| **裸 httpx 直接发同样的 body** | 502 | **不是 SDK 或我的构造问题** |
| 同样的 messages 换 `buddy/glm-5.3` | **200** | 是**模型/上游适配器**的差异 |

结论：这个网关里 `deepseek-*` 系列的适配器**无法表达 tool 结果消息**，
而 `buddy/glm-5.3`、`trae/qwen-3.5`、`qodercn/gmodel` 可以。所以本次把
`LLM_MODEL` 换成了 `buddy/glm-5.3`（`.env`）。

**这条的普适教训**：`tools=[...]` 能返回 `tool_calls` **不代表**这个模型完成了
Function Calling。完整的能力要求是**双向**的：

1. 会产出 `tool_calls`（几乎所有模型都行）
2. 会**接受** `role="tool"` 的回灌消息（各家差异极大）

只验证第 1 步就上线，会在第二轮才炸，而且错在"看起来完全无关"的地方。
**接入任何新模型，测试清单第一条应该是"跑一遍两轮闭环"，不是"能不能返回 tool_calls"。**

---

## 6. 循环上限：没有它就是在无限烧钱

模型可能"调工具 → 结果不满意 → 再调 → 再不满意"地循环，每轮都是一次计费的真实请求。
`MAX_TOOL_ROUNDS = 3` 够覆盖"查两个城市 → 算温差"这类合理链条。

实测 E4 正好用满 3 轮（`rounds=3 tool_calls=3`）：

```
round1  get_weather(北京) + get_weather(上海)   ← 并行两个
round2  calculate(19.5, subtract, 12.0) = 7.5   ← 用第一轮的结果做二次计算
round3  无工具调用 → 最终答案
```

第 2 轮调 `calculate` 用的 `a=19.5, b=12.0` 来自第 1 轮的 tool 结果 ——
这说明**回灌是有效的**，模型真的读到了工具返回值。

E5 用 `max_rounds=1` 强制触发上限，返回 `stopped_reason="max_rounds"` 而不是假装完成。
**超限要如实说"没答完"**，不能把半成品当最终答案交付 —— 那会让用户以为得到的是结论。

---

## 7. 边界清单（每条都有对应用例）

| 边界 | 实测行为 | 用例 |
| --- | --- | --- |
| 模型直接回答、不调工具 | `tool_calls=0`，只发 1 次请求就结束 | E1 / `test_loop_stops_immediately...` |
| 参数类型错 | Pydantic 拦下，回灌 `fields[{field,reason,got}]` | E2 / `test_execute_tool_never_raises` |
| 工具名不存在 | 返回 `available_tools`，不抛 `KeyError` | E3 / `test_unknown_tool_lists_available` |
| 连续 3 轮 | 正常收敛到最终答案 | E4 |
| 超过轮数上限 | `stopped_reason="max_rounds"`，不假装完成 | E5 / `test_loop_respects_max_rounds` |
| 数字写成字符串 `"12"` | **能转**（Pydantic lax），20 而不是报错 | `test_string_numbers_are_coerced` |
| 除以 0 | `division_by_zero` 回灌，不崩 | `test_calculate_divide_by_zero_and_overflow` |
| 结果溢出成 `inf` | 拦下（`Infinity` 不是合法 JSON，下游解析器会崩） | 同上 |

"数字写成字符串能转"这条值得单独记：它是**刻意的宽容**。模型经常把数字写成 `"12"`，
为此报错会让模型白跑一轮；但真正转不了的 `"abc"` 必须报错 —— 宽容要有边界。

---

## 8. 给 W9 Agent 的回扣

今天这些坑，到了 W9 会以放大十倍的形态出现：

| 今天 | W9 |
| --- | --- |
| 模型幻觉一个工具名 | 模型幻觉一个**有破坏性**的工具名（删库、发邮件、转账） |
| 参数类型错 | 参数类型错但**看起来合法**（正确的表名 + 错误的 where） |
| 3 轮上限 | 需要 planner/executor 分离、中间状态可回滚 |
| 工具结果是假数据 | 工具结果来自真实系统，错误会**改变真实世界** |

所以 W9 的 Agent 不该是"给模型一堆工具让它自己玩"，而是：
**注册表即权限边界**（不在表里的工具模型点不到）、
**执行即审计点**（每次调用都留 `tool_call_id` + 参数 + 结果）、
**上限即安全阀**（轮数、金额、影响面都要有硬上限）。

这些不是"以后再说"的工程细节 —— 它们是"模型只说不做"这个事实的直接推论。
