# -*- coding: utf-8 -*-
"""demo2：阻塞陷阱 —— 把 await asyncio.sleep(1) 换成 time.sleep(1)（21:00-21:30）

用同一套 3 个任务，分别用 asyncio.sleep 和 time.sleep，观察并发是否失效。

运行：python demo2_blocking_trap.py

必答问题：为什么同步阻塞会毁掉整个事件循环？
--------------------------------------------------------------------------------
因为 asyncio 的事件循环是**单线程**的：它本质是一个 `while True` 循环，
靠操作系统的 I/O 多路复用（selector/epoll/IOCP）等"可读可写/超时"事件，
事件到了再回调对应的 Task 继续执行。

`time.sleep(1)` 是同步阻塞调用：它让**当前线程**原地睡 1 秒，期间不返回、
不让出控制权。事件循环正卡在这段代码里，于是：
- 它没法回到 `select()` 去收新的 I/O 事件；
- 它没法把控制权交给其他 Task；
- 其他任务的倒计时明明早就到点了，也只能排在后面干等。

结果：3 个任务的 1 秒**不能重叠**，总耗时退化成 3.0s，并发彻底失效——
事件循环被"独占"了，这期间整个进程里的所有异步任务都停摆（"head-of-line blocking"）。

修复思路（本 demo 只演示问题，不演示全部修复）：
1. 换掉同步阻塞调用：`time.sleep` -> `await asyncio.sleep`；
   同步 HTTP -> `aiohttp`/`httpx.AsyncClient`。
2. 没法换的同步阻塞代码（第三方库、CPU 密集、文件 I/O），
   用 `await asyncio.to_thread(fn, ...)`（Py3.9+）或
   `loop.run_in_executor(None, fn, ...)` 丢到线程池里执行，
   事件循环就不会被卡住。
3. 不要在协程里写 CPU 密集的死循环。

验收：asyncio 版 ≈ 1.0s，time.sleep 版 ≈ 3.0s。
"""

import asyncio
import time


async def fetch_async(id: int, delay: float) -> str:
    """正确写法：await asyncio.sleep，等待期间让出控制权。"""
    await asyncio.sleep(max(0.0, delay))
    return f"task{id} 完成 (asyncio.sleep)"


async def fetch_blocking(id: int, delay: float) -> str:
    """错误写法：在协程里做同步阻塞调用，事件循环被卡死。"""
    time.sleep(max(0.0, delay))  # ← 整个线程原地睡，循环无法调度其他任务
    return f"task{id} 完成 (time.sleep)"


async def bench(coro_fn, label: str) -> float:
    t0 = time.perf_counter()
    results = await asyncio.gather(*(coro_fn(i, 1.0) for i in (1, 2, 3)))
    cost = time.perf_counter() - t0
    for r in results:
        print(f"    {r}")
    print(f"    总耗时: {cost:.1f}s  <- {label}")
    return cost


async def main() -> None:
    print("[demo2] 3 个任务各等 1.0s，正常应 ≈1.0s（可重叠）\n")

    print("-- A. await asyncio.sleep(1.0) --")
    good = await bench(fetch_async, "并发生效")

    print("\n-- B. time.sleep(1.0)（同步阻塞） --")
    bad = await bench(fetch_blocking, "并发失效，退化成串行")

    print(f"\n结果: asyncio.sleep {good:.1f}s  vs  time.sleep {bad:.1f}s")
    print("结论: 同步阻塞调用独占线程，事件循环无法调度其他任务，3 段等待无法重叠。")


if __name__ == "__main__":
    asyncio.run(main())