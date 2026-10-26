# 周三 10/21 实操流程：asyncio 进阶（限流 / 队列 / 超时取消 / TaskGroup）

> 目标产物：`learn/asyncio_basics/advanced.py`，四个 demo 全部可独立运行。
> 本文是**从零到验收**的完整流程 + 注意事项，照着走一遍即可复现。
> 所有数字都是本机 Python 3.11.2 实测值。
>
> 如果只想看"跑什么"，直接跳到 [3. 整体验收](#3-整体验收4-分钟)；首次上手建议从 0 开始按序走。

---

## 0. 前置：确认解释器（1 分钟，别跳过）

这一步最容易翻车。本机有三个解释器：

```powershell
py -0p
```

结果是：默认 `python` = **3.9.23**，另有 `py -3.11`（3.11.2）。

**为什么必须先确认**：`advanced.py` 用了 `except*`（PEP 654，3.11 新语法）。
3.9 读到那一行会**在解析阶段直接 SyntaxError**，四个 demo 一个都跑不起来——包括前三个跟
3.11 无关的。所以命令里必须显式写 `py -3.11`，不能写 `python`。

```powershell
py -3.11 --version      # 预期：Python 3.11.2
```

> 实测：`python advanced.py 1` 在 3.9 下的报错是
> `File "advanced.py", line 306 / except* RuntimeError as eg: / SyntaxError: invalid syntax`

---

## 1. 准备目录

```powershell
cd D:\git\网页\learn\asyncio_basics
```

确认这几个文件都在（基础篇 + 进阶篇）：

```
README.md
demo0_coroutine_object_task.py
demo1_serial_vs_gather.py
demo2_blocking_trap.py
demo3_error_handling.py
advanced.py          ← 本次的产物
```

---

## 2. 按时间段跑四个 demo

一天拆成 4 段，每段对应一个 demo，**建议按顺序单独跑**（每个约 0.5–2.6s，很快）。
单独跑的好处：输出干净、出错时能立刻定位是哪个 demo 的问题。

### 20:00–20:35 Semaphore 限流

```powershell
py -3.11 advanced.py 1
```

**要看的**：
- 每行打印「当前并发数」，从 1 爬到 **5** 就不再往上
- 结尾必须有 `峰值并发数 = 5`
- 随后一段 `[对照] 不加 Semaphore：峰值并发数 = 20`

**验收标准**：峰值 ≤ 5，且脚本退出码为 0。
代码里第 80 行有 `assert stats["peak"] <= 5`——限流失效会直接 AssertionError，
不会"看起来正常"地混过去。

### 20:35–21:10 Queue 生产者-消费者

```powershell
py -3.11 advanced.py 2
```

**要看的**：
- 3 个 worker 交替取任务，生产者和消费者是交错的
- 结尾 `队列剩余 = 0`，三个 worker 的条数**加起来 = 10**
- `总耗时` 约 0.5s

**验收标准**：合计 10 条。第 151 行有 `assert sum(board.values()) == 10`。

### 21:10–21:40 超时与取消

```powershell
py -3.11 advanced.py 3
```

**要按顺序看三段**：

| 小节 | 该看到什么 | 别误解成什么 |
| --- | --- | --- |
| 3.1 `wait_for` | `TimeoutError` 在 **1.00s** 触发，没等满 5s | 不是"5s 的活儿还在后台跑"，`wait_for` 会把内部任务 cancel 掉 |
| 3.2 `shield` | 壳子被 cancel，但 `inner.cancelled()=False`、关键任务跑完 **3/3** | 不是"shapes 让任务变快"，只是让取消不传导 |
| 3.3 `cancel()` | A 正确 re-raise → `cancelled()=True`；B 吞掉 → 调用方拿到 `'B-吞掉 假装完成'`、`cancelled()=False` | B 的行为是**错误示范**，别当成正常路径 |

**验收标准**：三段输出齐全，退出码 0。3.3 的 B 分支是本 demo 的重点，它演示了
"取消被吞掉之后 cancel() 形同虚设"这个真实事故来源。

### 21:40–22:00 TaskGroup

```powershell
py -3.11 advanced.py 4
```

**要看的**：
- 4.1：用 `async with asyncio.TaskGroup()` 重写 demo1，耗时 ~1.04s、峰值仍是 5
- 4.2：gather 在 0.2s 抛异常但 A/C **继续跑完**；TaskGroup 在 0.2s **取消 A/C** 后抛 `ExceptionGroup`
- 4.3：P/Q 同时失败 → gather 只给 1 个、TaskGroup 聚到 **2 个**，`except* RuntimeError` 一次收齐

**验收标准**：4.3 里 `except* RuntimeError 捕获到 2 个`。

---

## 3. 整体验收（4 分钟）

```powershell
# 逐个跑，确认每个都能独立运行且退出码为 0
foreach ($d in 1..4) {
    py -3.11 advanced.py $d > $null 2>&1
    "demo$d exit=$LASTEXITCODE"
}
```

预期：
```
demo1 exit=0
demo2 exit=0
demo3 exit=0
demo4 exit=0
```

> ⚠️ **不要在验退出码的命令里用 `Select-Object -First`**。
> `py -3.11 advanced.py 1 | Select-Object -First 6` 会因为管道被提前关闭，
> 让 `$LASTEXITCODE` 变成 `-1`——看起来像脚本崩了，其实是 PowerShell 截断造成的。
> 要看前几行就先重定向到文件，再 `Get-Content -TotalCount`。
> 实测：同样一条命令，不截断 exit=0，用 `Select-Object -First` 截断后 exit=-1。

然后全跑一遍，确认没有警告噪音：

```powershell
py -3.11 advanced.py all > $env:TEMP\all.txt 2>&1
"all exit=$LASTEXITCODE"
Select-String -Path $env:TEMP\all.txt -Pattern "Traceback|Warning|never retrieved"
```

预期：`all exit=0`，第二条命令**没有输出**。

> `"never retrieved"` 是这个练习里最容易冒出来的噪音：gather 模式下一个任务失败了、
> 另一个的异常没人取，事件循环关闭时会打印 "Task exception was never retrieved"。
> 代码里用 `await asyncio.sleep(0.6)` 给 A/C 留了收尾窗口，所以正常情况不该出现。

---

## 4. 五分钟自测：能不能讲出来

跑通不等于学会。合上代码，试着回答这四个问题（答不上就回去重看对应 demo）：

1. 20 个任务 + `Semaphore(5)`，峰值为什么不可能是 6？
   （提示：`async with sem` 拿不到名额就在那行挂起，不是"先跑起来再限流"）
2. `queue.join()` 等的是"塞完了"还是"处理完了"？漏一个 `task_done()` 会怎样？
   （提示：等 `unfinished` 归零；漏一个就永远不返回）
3. `wait_for` 超时之后，那个 5s 的协程还在跑吗？`shield` 又在保护什么？
   （提示：wait_for 会 cancel；shield 让取消不传导到被保护任务）
4. gather 和 TaskGroup，一个任务失败时另外两个的命运有什么不同？
   （提示：gather 不取消、后台跑完；TaskGroup 自动取消兄弟）

---

## 注意事项（踩过的坑 + 会踩的坑）

### A. 解释器相关的坑

1. **必须 `py -3.11`，不能 `python`**。默认 `python` 是 3.9，`except*` 直接 SyntaxError。
   这是本文件唯一一个"用错就全崩"的硬约束。

2. **不要在文件里加版本检查**。`if sys.version_info < (3, 11): sys.exit(...)` 是死代码——
   低版本在**解析阶段**就挂了，根本执行不到那一行。只能在文件头注释里写清楚要求。

3. **`assert` 在 `-O` 下会失效**。本文件用 assert 兜底（峰值 ≤5、合计 =10），
   `py -3.11 -O advanced.py` 跑的话这两个断言会被跳过。日常跑没问题，
   但如果拿它当 CI 检查，要改成显式 `if ... raise`。

### B. demo2 的经典坑（这个真踩到了）

4. **`create_task` 之后立刻 `await q.join()` 会提前返回。**

原因：`create_task` 只是把协程登记进循环，当前协程还没让出 CPU，队列还是空的、
`unfinished == 0`，于是 `join()` 认为"已经全处理完了"，**立刻返回**。

第一次实测只处理了 5 条就打印"完成"，看起来一切正常，实际是个静默 bug。

修法（[advanced.py:142](advanced.py#L142)）：

```python
prod = asyncio.create_task(producer(q, 10))
await asyncio.sleep(0)   # ★ 让生产者先跑起来，unfinished 才 > 0
await q.join()
```

兜底：后面加了 `assert sum(board.values()) == 10`，以后再犯会当场报错。

**通用教训**：`create_task` 不等于"已经开始跑"，先 `await asyncio.sleep(0)` 让一轮，
再依赖它的副作用。

### C. 取消相关的坑

5. **`CancelledError` 是 `BaseException`**（3.8+），`except Exception` 抓不到它。
   想清理就用 `except asyncio.CancelledError:`，**清理完必须 `raise`**，
   否则取消信号被吞，`wait_for` / `TaskGroup` 的超时与取消整体失灵（见 3.3 的 B 分支）。

6. **`shield` 保护的是内层任务，不是"让 operation 不可取消"**。外层壳子照样收到
   `CancelledError`，只是内层继续跑。要拿结果还得自己 `await inner`。

### D. TaskGroup 的坑

7. **`except RuntimeError` 抓不到 TaskGroup 的异常**。它抛的是 `ExceptionGroup`，
   类型不是 `RuntimeError`，必须用 `except* RuntimeError`。

8. **被连带取消的兄弟任务不计入异常组**。取消是 TaskGroup 自己的清理手段，不算错误，
   所以聚合里不会出现 `CancelledError`。别指望用 `except* CancelledError` 去接被取消的兄弟
   （我一开始就这么写了，那个分支永远不触发，后来删掉了）。

9. **聚合到的数量是"取消生效前已失败的个数"**，不是"代码里写了几个失败"。
   如果 Q 比 P 晚失败，它早被取消了，聚合里就只有 P。想全收得让失败尽量同时发生。

### E. Windows 终端的编码坑

10. **直接 `py -3.11 advanced.py 1` 在 PowerShell 里可能显示乱码**。
    本机 console codepage 是 936（GBK），Python 输出中文会花。

    两种解法，选一个：
    ```powershell
    # 解法一：临时设 UTF-8（每个新终端都要设一次）
    $env:PYTHONIOENCODING="utf-8"; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8

    # 解法二：给 python 加 -X utf8（推荐，不用改环境）
    py -3.11 -X utf8 advanced.py 1
    ```
    实测 `-X utf8` 有效：不加时输出 `Semaphore ������` 这种乱码，加了就是正常中文。
    它只影响 Python 自己的编码，不影响 `py -3.11` 的版本选择，可以叠加用。

11. **重定向到文件时也要注意**。`advanced.py 1 > out.txt` 在 GBK 环境下写出的是 GBK 字节
    （实测以 `\xb1\xbe\xb4\xce` 开头，不是 UTF-8），用 UTF-8 编辑器打开会乱码。
    要么先设 `$env:PYTHONIOENCODING="utf-8"`，要么加 `-X utf8`。

12. **验退出码时别用 `Select-Object -First`**。管道被提前关闭会让 `$LASTEXITCODE` 变成 `-1`，
    看着像崩了其实没有。要么重定向到文件再读，要么别截断。

### F. 时间/耗时判读的坑

13. **别拿总耗时当验收指标**。本机跑 demo1 是 1.03s，换台机器可能是 1.2s 或 0.9s——
    受调度影响。硬指标是**峰值并发数 = 5**、**合计 = 10**、**聚合数 = 2** 这类计数，
    耗时就当参考。

14. **demo2 的 worker 条数分布每次都不一样**（可能 4/3/3，也可能 3/4/3）。
    这是正常的：3 个 worker 抢同一个队列，谁先醒谁拿。只校验**总和 = 10**。

---

## 附：一句话记住四个 demo

| demo | 一句话 |
| --- | --- |
| 1 Semaphore | 名额用完就在 `async with` 那行排队，所以峰值 = 容量 |
| 2 Queue | `join()` 等 `unfinished` 归零，每个 `get()` 必须配 `task_done()` |
| 3 超时取消 | `wait_for` 会 cancel；`shield` 挡住 cancel；`CancelledError` 清理完必须 raise |
| 4 TaskGroup | 一个失败，兄弟全取消，异常打包成 `ExceptionGroup` 用 `except*` 拆 |
