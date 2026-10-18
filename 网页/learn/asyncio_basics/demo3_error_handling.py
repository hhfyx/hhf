# -*- coding: utf-8 -*-
"""demo3：错误处理 —— gather(return_exceptions=True) vs as_completed（21:30-22:00）

故意让 3 个任务里的第 2 个抛异常，观察另外两个任务的命运。

运行：python demo3_error_handling.py

必答问题：一个任务失败会不会影响其他任务？
--------------------------------------------------------------------------------
结论：**不会互相影响（不会被自动取消），但会影响你拿到结果的方式。**

1. `asyncio.gather(*coros)`（默认 return_exceptions=False）：
   第一个异常会**立刻向调用方抛出**。此时 gather 本身返回了，但
   **其他任务并不会被取消**，它们仍在事件循环里跑到底（只是你不再通过
   gather 收结果）。而且如果没人再 await 它们，异常可能只留下
   "Task exception was never retrieved" 的日志。
   -> 行为是"快速失败"，不是"全停"。

2. `asyncio.gather(*coros, return_exceptions=True)`：
   异常被当作**返回值**放进结果列表，等全部任务结束后一起返回；
   调用方不会抛异常，返回列表里既可能是结果也可能是 Exception 对象，
   需要逐个 `isinstance(r, Exception)` 判断。顺序仍是传入顺序。

3. `asyncio.as_completed(coros)`：
   返回一个迭代器，**谁先完成先给我**（完成顺序，不是传入顺序），
   每项都要自己 `await`，因此可以**逐个 try/except**：
   一个失败就当场处理，其余任务照常继续跑完。
   适合"哪个先好先处理哪个" + 需要精细错误处理的场景。

为什么没有"一个失败连累全家"？
因为每个协程被包成独立 Task，各自有自己的异常状态（Task.exception()）。
一个 Task 抛异常只会让它自己进入 finished 状态并记录异常，
其他 Task 与它之间没有耦合关系，除非你自己写了 cancel 逻辑。

补充：Py3.11 起有 `asyncio.TaskGroup`（结构化并发，一失败会取消同组其他任务），
Python 3.9 用不到，这里的写法在 3.9 上全部可运行。
"""

import asyncio


async def job(name: str, delay: float, fail: bool = False) -> str:
    """模拟一个任务：delay 秒后返回；fail=True 则抛异常。"""
    await asyncio.sleep(max(0.0, delay))
    if fail:
        raise RuntimeError(f"{name} 故意失败")
    return f"{name} 成功"


def show(item) -> str:
    if isinstance(item, Exception):
        return f"<异常> {type(item).__name__}: {item}"
    return f"<结果> {item}"


async def main() -> None:
    jobs = [("jobA", 0.2, False), ("jobB", 0.3, True), ("jobC", 0.4, False)]

    # ---------- 1) as_completed：逐个处理，一个失败不连累其他 ----------
    print("== 1) asyncio.as_completed：完成顺序返回，逐个 try/except ==")
    tasks = [asyncio.create_task(job(*args)) for args in jobs]
    for fut in asyncio.as_completed(tasks):
        try:
            print(f"    收到 {show(await fut)}")
        except Exception as exc:  # 只影响这一个任务的处理分支
            print(f"    捕获异常 {type(exc).__name__}: {exc}（继续处理剩余任务）")
    print(f"    全部任务最终状态: {[(t.get_name(), t.done(), t.cancelled()) for t in tasks]}")
    print("    -> 3 个任务都跑完了，jobB 的异常没有中断 jobA / jobC\n")

    # ---------- 2) gather 默认：第一个异常立刻抛出 ----------
    print("== 2) gather 默认模式：第一个异常立刻抛出 ==")
    try:
        await asyncio.gather(*(job(*args) for args in jobs))
    except RuntimeError as exc:
        print(f"    gather 抛出了: {type(exc).__name__}: {exc}")
        print("    -> 注意：另外两个任务并没有被取消，它们在后台继续跑（见下一步的说明）")
    # 给后台任务留点时间跑完，避免 "Task exception was never retrieved" 噪音
    await asyncio.sleep(0.5)

    # ---------- 3) gather(return_exceptions=True)：异常当返回值 ----------
    print("\n== 3) gather(..., return_exceptions=True)：等齐全部，异常混在结果里 ==")
    results = await asyncio.gather(
        *(job(*args) for args in jobs), return_exceptions=True
    )
    for i, r in enumerate(results, 1):
        print(f"    第{i}项 {show(r)}")
    oks = [r for r in results if not isinstance(r, Exception)]
    errs = [r for r in results if isinstance(r, Exception)]
    print(f"    成功 {len(oks)} 个 / 失败 {len(errs)} 个，调用方不会被异常打断，可以自己决定是否重试")


if __name__ == "__main__":
    asyncio.run(main())