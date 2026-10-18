# asyncio 基础（2026-10-20 周二 20:00–22:00）

纯学习代码，用来留痕：4 个可独立运行的小 demo + 4 个必答问题的结论。

## 运行环境（两个解释器均已实测通过）

| 解释器 | 版本 | 说明 |
| --- | --- | --- |
| `python` | 3.9.23 | 首次编写与验证 |
| `D:\conda_envs\defectfill2\python.exe` | 3.11.15 | 复跑验收（demo1） |

两个版本都能跑：代码没用到 3.10+ 的语法（`TaskGroup` 只在注释里提及，未使用）。

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

## 资源

- Python 官方文档：Coroutines and Tasks
- Real Python: *Async IO in Python: A Complete Walkthrough*
- 《Python Concurrency with asyncio》(Manning) 第 1–3 章