# -*- coding: utf-8 -*-
"""demo1：串行 await vs asyncio.gather（20:30-21:00）

同一批 3 个 fetch(id, delay)，用两种方式跑，打印总耗时做对比。

运行：python demo1_serial_vs_gather.py

必答问题：为什么 gather 快？
--------------------------------------------------------------------------------
因为 gather 把 3 个协程各自包装成 Task 注册进**同一个事件循环**，3 个任务
同时推进；每个任务执行到 `await asyncio.sleep(delay)` 时会把控制权交还给事件
循环，循环立刻去跑另一个已经就绪的任务，于是 3 段"等待"在时间轴上**重叠**了。

对比串行：`await fetch(1, 1.0)` 会阻塞当前协程直到这个协程真正结束才轮到下一个，
3 段等待首尾相接，不重叠。

关键认知：asyncio 并发 ≠ 多线程/多进程。
- 只有 1 个线程、1 个事件循环，任何时刻仍然只有一段 Python 代码在跑；
- 快的原因是 **I/O 等待期间 CPU 被让出来干别的活**，所以总耗时 ≈ max(各延迟)
  而不是 sum(各延迟)。
- 正因为是单线程，一旦某个协程里写了同步阻塞调用（见 demo2），
  整个循环就会被卡住，"快"立刻消失。

验收输出（本机实测，Python 3.9.23）：
    串行 3.0s / 并发 1.0s
"""

import asyncio
import time


async def fetch(id: int, delay: float) -> str:
    """模拟一次网络请求：耗时 delay 秒，返回字符串。"""
    # ① 注意这里用的是 asyncio.sleep（可被事件循环挂起），不是 time.sleep
    await asyncio.sleep(max(0.0, delay))
    return f"fetch({id}) 完成"


async def run_serial() -> float:
    """串行：一个 await 完再 await 下一个。"""
    t0 = time.perf_counter()
    results = []
    for i in (1, 2, 3):
        results.append(await fetch(i, 1.0))  # 每个都要等满 1s
    cost = time.perf_counter() - t0
    for r in results:
        print(f"    {r}")
    return cost


async def run_gather() -> float:
    """并发：gather 把 3 个协程一起交给事件循环。"""
    t0 = time.perf_counter()
    # gather 的返回顺序 == 传入顺序，与谁先跑完无关
    results = await asyncio.gather(
        fetch(1, 1.0),
        fetch(2, 1.0),
        fetch(3, 1.0),
    )
    cost = time.perf_counter() - t0
    for r in results:
        print(f"    {r}")
    return cost


async def main() -> None:
    print("[demo1] 3 个 fetch，每个 delay=1.0s\n")
    print("-- 串行 await --")
    serial = await run_serial()
    print(f"    串行耗时: {serial:.1f}s")

    print("\n-- asyncio.gather --")
    concurrent = await run_gather()
    print(f"    并发耗时: {concurrent:.1f}s")

    print(f"\n结果: 串行 {serial:.1f}s / 并发 {concurrent:.1f}s")
    print("说明: 串行 ≈ 1.0+1.0+1.0 = 3.0s，并发 ≈ max(1.0,1.0,1.0) = 1.0s，提速约 3 倍。")


if __name__ == "__main__":
    asyncio.run(main())