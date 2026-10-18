# -*- coding: utf-8 -*-
"""demo0：协程函数 vs 协程对象 vs Task —— 三个概念的区别

20:00-20:30 概念打底的验证代码（对照官方文档 "Coroutines and Tasks" 前两节）。

运行：python demo0_coroutine_object_task.py

必答问题：协程函数 vs 协程对象 vs Task 的区别？
--------------------------------------------------------------------------------
1) 协程函数 (coroutine function)：用 `async def` 定义的函数本身。
   调用它**不会执行函数体**，只是返回一个协程对象。

2) 协程对象 (coroutine object)：`hello()` 的返回值。它是一个"待执行的说明书"，
   自己不会跑。只有被 `await`（或交给 Task 调度）时才会真正执行。
   注意：协程对象**只能被 await 一次**，await 完就"耗尽"了，
   再次 await 会抛 RuntimeError；而且没 await 就被 GC 掉会留下
   "coroutine was never awaited" 警告。

3) Task：`asyncio.create_task(coro)` 把协程包装成任务并**立刻注册到事件循环**，
   于是它开始并发运行，不需要你在原地 await。
   Task 是 Future 的子类，因此可以：await 它、取消它 (.cancel())、
   查它状态 (.done()/.cancelled())、拿结果 (.result()/.exception())。

一句话记忆：
    协程函数 -> 调用得到 -> 协程对象（惰性，不会自己跑）
    协程对象 -> await      -> 在当前协程里同步地跑完
    协程对象 -> create_task -> 变成 Task，在后台并发地跑
"""

import asyncio
import time


async def hello(name: str, delay: float) -> str:
    """一个普通的协程函数。注意：调用它并不会执行这里面的任何一行。"""
    print(f"    [hello] {name} 开始")
    await asyncio.sleep(delay)
    print(f"    [hello] {name} 结束")
    return f"{name}-done"


async def main() -> None:
    # ---------- 1) 协程函数：callable，但调用不执行 ----------
    print("== 1) 调用协程函数：只拿到对象，函数体一行都没跑 ==")
    coro = hello("A", 0.1)  # 没有任何 [hello] 输出
    print(f"    type(hello)      = {type(hello)}")
    print(f"    type(coro)       = {type(coro)}")
    print(f"    asyncio.iscoroutinefunction(hello) = {asyncio.iscoroutinefunction(hello)}")
    print(f"    asyncio.iscoroutine(coro)          = {asyncio.iscoroutine(coro)}")

    # ---------- 2) 协程对象：await 才执行 ----------
    print("\n== 2) await 协程对象：这时才真正执行 ==")
    t0 = time.perf_counter()
    result = await coro
    print(f"    返回值 = {result}，耗时 {time.perf_counter() - t0:.3f}s")

    # ---------- 3) Task：创建即开始跑 ----------
    print("\n== 3) create_task：不 await 也已经开始跑了 ==")
    t0 = time.perf_counter()
    tasks = [asyncio.create_task(hello(n, 0.3)) for n in ("B", "C", "D")]
    print(f"    创建 3 个 Task 后立刻检查：")
    for t in tasks:
        print(f"      {t.get_name():<12} done={t.done()} cancelled={t.cancelled()}")
    # 三个任务都在 0.3s 的 sleep 里并发重叠，所以总耗时应 ≈ 0.3s 而不是 0.9s
    names = await asyncio.gather(*tasks)
    print(f"    全部完成，返回值 = {names}，总耗时 {time.perf_counter() - t0:.3f}s（≈0.3s，说明 3 个 Task 是重叠跑完的）")

    # ---------- 4) 差异对照：不用 Task 的写法 ----------
    print("\n== 4) 对照：直接在列表推导里写 hello(...) 而不 create_task ==")
    t0 = time.perf_counter()
    coros = [hello(n, 0.3) for n in ("E", "F", "G")]
    # 注意：gather 接收的是协程对象，它内部会自动包成 Task，
    # 所以用 gather 仍然是并发的；真正"退化成串行"的是下面这种写法：
    for c in coros:
        await c  # 一个个 await -> 0.3 * 3 = 0.9s
    print(f"    逐个 await 总耗时 {time.perf_counter() - t0:.3f}s（≈0.9s，退化成串行）")


if __name__ == "__main__":
    asyncio.run(main())