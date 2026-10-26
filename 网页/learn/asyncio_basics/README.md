# asyncio 基础（2026-10-20 周二 20:00–22:00）

纯学习代码，用来留痕：4 个可独立运行的小 demo + 4 个必答问题的结论。

> 进阶篇（周三 10/21）在 [`advanced.py`](advanced.py)，限流 / 生产者-消费者 / 超时取消 / TaskGroup，见本文末尾。

## 运行环境（两个解释器均已实测通过）

| 解释器 | 版本 | 说明 |
| --- | --- | --- |
| `python` | 3.9.23 | 基础四个 demo 的编写与验证 |
| `py -3.11` | 3.11.2 | `advanced.py` 全部（需 3.11+）+ 基础 demo 复跑 |

两个版本都能跑：基础四个 demo 没用到 3.10+ 的语法（`TaskGroup` 只在注释里提及）。
进阶篇 `advanced.py` 不同，它要求 3.11+，见下文。

## 怎么跑

```powershell
cd learn/asyncio_basics
python demo0_coroutine_object_task.py   # 概念：协程函数 / 协程对象 / Task
python demo1_serial_vs_gather.py        # 串行 await vs asyncio.gather（约 7s）
python demo2_blocking_trap.py           # asyncio.sleep vs time.sleep（约 6s）
python demo3_error_handling.py          # as_completed vs gather 错误处理（约 2s）
```
每个文件顶部的 docstring 就是当次的笔记，本文只做索引和结论汇总。

## 四个必答问题

| 时间段 | demo | 必答问题 | 结论 |
| --- | --- | --- | --- |
| 20:00–20:30 | `demo0_coroutine_object_task.py` | 协程函数 vs 协程对象 vs Task 的区别？ | 见下 1 |
| 20:30–21:00 | `demo1_serial_vs_gather.py` | 为什么 gather 快？ | 见下 2 |
| 21:00–21:30 | `demo2_blocking_trap.py` | 为什么同步阻塞会毁掉整个事件循环？ | 见下 3 |
| 21:30–22:00 | `demo3_error_handling.py` | 一个任务失败会不会影响其他任务？ | 见下 4 |

### 1. 协程函数 vs 协程对象 vs Task

| 概念 | 是什么 | 调用/创建后会不会跑 | 身份 |
| --- | --- | --- | --- |
| 协程函数 | `async def f()` 定义的函数本身 | 不会 | `function` |
| 协程对象 | `f()` 的返回值，一份"待执行说明书" | 不会，`await` 时才跑 | `coroutine` |
| Task | `asyncio.create_task(coro)` 的产物 | **创建即注册进事件循环，开始并发跑** | `Task`（`Future` 子类） |

- 协程对象只能被 await 一次，await 完就耗尽；没 await 就被 GC 会警告 "coroutine was never awaited"。
- Task 带来额外能力：`await`、`.cancel()`、`.done()`/`.cancelled()`、`.result()`/`.exception()`。
- 记忆：`协程函数 -> 调用 -> 协程对象 -> await(当前协程里同步跑) / create_task(后台并发跑)`。

### 2. 为什么 gather 快

gather 把 N 个协程各包成一个 Task 注册到**同一个事件循环**，N 个任务同时推进；
每个任务执行到 `await asyncio.sleep(delay)` 时就交还控制权，循环立刻去跑另一个就绪任务，
于是 N 段"等待"在时间轴上**重叠**。实测：串行 `3.0s` vs gather `1.0s`（≈ `max(延迟)` 而非 `sum(延迟)`）。

关键认知：asyncio 并发**不是**多线程/多进程。只有 1 线程 1 循环，任何时刻仍只有一段 Python
代码在跑；快的原因是 I/O 等待期间把 CPU 让出来。所以它是"I/O 密集型加速器"，
CPU 密集任务用它不会快。

### 3. 为什么同步阻塞会毁掉整个事件循环

事件循环是单线程的 `while True`，靠 OS 的 I/O 多路复用（selector/epoll/IOCP）等事件回来再回调 Task。

`time.sleep(1)` 让**当前线程原地睡 1 秒**，期间不让出控制权，事件循环正卡在这行代码里：
收不到新 I/O 事件，也调度不了其他 Task —— 其他任务的计时早就到点，只能排队干等。
3 段 1 秒因此无法重叠，总耗时退化成 `3.0s`（实测：`asyncio.sleep 1.0s` vs `time.sleep 3.0s`），
这就是 head-of-line blocking：一个人卡住，全场停摆。

修复方向：
1. 换掉同步调用：`time.sleep` → `await asyncio.sleep`；`requests` → `aiohttp`/`httpx.AsyncClient`。
2. 换不掉的同步阻塞（第三方库、文件 I/O、CPU 密集）：`await asyncio.to_thread(fn, ...)`（3.9+）
   或 `loop.run_in_executor(None, fn, ...)` 丢进线程池。
3. 协程里别写 CPU 密集死循环。

### 4. 一个任务失败会不会影响其他任务

**不会互相影响（不会被自动取消），但会改变你拿到结果的方式。**

| 写法 | 一个任务抛异常时的行为 |
| --- | --- |
| `gather(*coros)`（默认） | 第一个异常**立刻向调用方抛出**；其他任务**不取消**，仍在后台跑到底，异常可能只留下 "Task exception was never retrieved" 日志 |
| `gather(*coros, return_exceptions=True)` | 异常当作**返回值**放进结果列表，等全部结束再一起返回；需要逐个 `isinstance(r, Exception)` 判断，顺序仍是传入顺序 |
| `asyncio.as_completed(coros)` | **谁先完成先给谁**（完成顺序≠传入顺序），每项自己 `await`，可逐个 `try/except`：一个失败当场处理，其余照常跑完 |

原因：每个协程被包成独立 Task，各有独立异常状态（`Task.exception()`），彼此没有耦合，
除非你自己写 `cancel` 逻辑。实测 `as_completed`：jobB 失败，jobA/jobC 依旧成功，
3 个 Task 最终全部 `done=True`。

补充：Python 3.11+ 的 `asyncio.TaskGroup` 是结构化并发，同组一个失败会取消其余任务
（3.9 用不到，此处代码在 3.9 上全部可运行）。

## 验收

demo1 输出：

```
结果: 串行 3.0s / 并发 1.0s
```

已实测通过（本机 Python 3.9.23），四个 demo 均无异常退出。

## 进阶篇：`advanced.py`（2026-10-21 周三 20:00–22:00）

> 完整的操作步骤、验收命令、坑清单见 **[RUNFLOW.md](RUNFLOW.md)**，本节只放结论。

W2 的流式 LLM 调用、W12 的并发压测都靠这里的「限流 + 超时 + 取消」保命。四个 demo
各自跑在自己的事件循环里，都可独立运行：

```powershell
cd learn/asyncio_basics
py -3.11 advanced.py 1      # Semaphore 限流：20 个任务 + Semaphore(5)，打印当前并发数
py -3.11 advanced.py 2      # Queue 生产者-消费者：1 生产者 10 条，3 worker 消费，queue.join()
py -3.11 advanced.py 3      # 超时与取消：wait_for / shield / task.cancel + CancelledError
py -3.11 advanced.py 4      # TaskGroup：重写 demo1，对比 gather 异常聚合
py -3.11 advanced.py all    # 全跑（约 6s）
```

**这个文件必须用 3.11+ 跑**：demo4 用了 `asyncio.TaskGroup` 和 `except*`（PEP 654），
后者是 3.11 的新语法，3.10 及以下**在解析阶段就 SyntaxError**（报错指到 `except*` 那一行）。
本机默认 `python` 是 3.9.23，所以命令里显式写 `py -3.11`——这一点和上面基础四个 demo 不同，
那些是 3.9/3.11 双跑通过的。

### 四个必答问题（进阶）

| 时间段 | demo | 必答问题 | 结论 |
| --- | --- | --- | --- |
| 20:00–20:35 | `demo1_semaphore` | 怎么确认并发被限住？ | 见下 5 |
| 20:35–21:10 | `demo2_queue` | `queue.join()` 等的到底是啥？ | 见下 6 |
| 21:10–21:40 | `demo3_timeout_cancel` | 超时 / 取消 / shield 各管什么？ | 见下 7 |
| 21:40–22:00 | `demo4_taskgroup` | TaskGroup 与 gather 的异常差异？ | 见下 8 |

### 5. Semaphore 限流

`asyncio.Semaphore(5)` 只有 5 个"名额"，第 6 个任务会**停在 `async with sem` 这一行排队**，
拿到名额才进临界区。实测：20 个任务峰值并发 = **5**；去掉信号量后峰值 = **20**。
关键点：信号量限制的是"进入临界区的任务数"，不是"创建的任务数"——
`create_task` 100 个也没关系，多出来的只是排队，不消耗连接。

### 6. queue.join() 等的是什么

`join()` 等的是 **`unfinished` 计数归零**，而不是"生产者塞完了"：每次 `put` +1，
每次 `task_done()` -1。所以每个 `get()` 必须配一个 `task_done()`（放在 `finally` 里），
漏一个就永远 join 不返回。

**踩到的坑**：`create_task(producer(...))` 只是登记，当前协程还没让出 CPU 时队列是空的、
`unfinished == 0`，于是 `await q.join()` **立刻返回**（第一次实测只处理了 5 条）。
修法是 `create_task` 之后先 `await asyncio.sleep(0)` 让生产者跑起来，代码里已用 assert 兜住。

### 7. 超时 / 取消 / shield 各管什么

| 工具 | 管什么 | 实测现象 |
| --- | --- | --- |
| `asyncio.wait_for(coro, 1)` | 到点抛 `TimeoutError`，**并取消**内部任务 | 5s 的调用在 1.00s 返回，后台没有残留 |
| `asyncio.shield(task)` | 取消只落在"等待者"身上，被保护的任务照跑 | 壳子被 cancel，内层仍跑完 3/3，`inner.cancelled()=False` |
| `task.cancel()` | 向任务内抛 `CancelledError` | 正确写法 re-raise → `cancelled()=True`；吞掉 → 调用方以为"正常完成"，取消失效 |

要点：`CancelledError` 在 3.8+ 继承 `BaseException`，`except Exception` **抓不到**它；
清理逻辑写在 `except CancelledError` 里，做完必须 `raise`，否则 `wait_for` / `TaskGroup` 的取消会整体失灵。

### 8. TaskGroup vs gather

| 维度 | `gather`（默认） | `TaskGroup`（3.11+） |
| --- | --- | --- |
| 第一个异常 | 立刻原样抛给调用方 | 等组内清理完，抛 `ExceptionGroup` |
| 其他任务 | **不取消**，后台跑到底（易泄漏） | **自动取消**同组剩余任务 |
| 多个异常 | 只拿第一个，其余可能变日志噪音 | 全部聚合进 `.exceptions`（实测同时失败聚到 2 个） |
| 结束时机 | 第一个异常就返回 | `async with` 退出时保证全组结束（结构化并发） |
| 捕获写法 | `try/except RuntimeError` | `except* RuntimeError`（PEP 654） |

`except*` 与普通 `except` 的区别：`ExceptionGroup` **不是** `RuntimeError`，所以
`except RuntimeError` 根本抓不到它；`except*` 会按类型把组拆成若干子组，每个分支只拿自己那一类。

注意聚合数量的语义：TaskGroup 只收"取消生效前已经失败"的那些；如果 Q 比 P 晚失败，
它早被取消了，聚合里就只有 P。另外**被连带取消的兄弟任务不计入异常组**——取消是 TaskGroup
自己的清理手段，不算错误，所以聚合里不会出现 `CancelledError`。TaskGroup 的价值是
"不漏掉同时发生的失败"，不是"收齐所有潜在失败"。

## 资源

- Python 官方文档：Coroutines and Tasks / Synchronization Primitives / Queues
- Real Python: *Async IO in Python: A Complete Walkthrough*
- 《Python Concurrency with asyncio》(Manning) 第 1–3 章