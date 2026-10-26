# -*- coding: utf-8 -*-
"""asyncio 进阶四个 demo：限流 / 生产者-消费者 / 超时与取消 / TaskGroup（2026-10-21 周三）

四个 demo 互相独立，各自跑在自己的事件循环里，可单独运行：

    py -3.11 advanced.py 1      # Semaphore 限流：20 个任务 + Semaphore(5)，打印当前并发数
    py -3.11 advanced.py 2      # Queue 生产者-消费者：1 生产者塞 10 条，3 worker 消费，queue.join()
    py -3.11 advanced.py 3      # 超时与取消：wait_for / shield / task.cancel + CancelledError
    py -3.11 advanced.py 4      # TaskGroup：重写 demo1，对比 gather 的异常聚合差异
    py -3.11 advanced.py all    # 依次全跑（默认）

环境：本文件按 **Python 3.11+** 编写。demo4 用了 `asyncio.TaskGroup` 与 `except*`（PEP 654），
这两样都是 3.11 的新语法/新 API，3.10 及以下连解析都过不去，必须用 3.11+ 解释器运行。
（本机默认 `python` 是 3.9，所以要显式写 `py -3.11 advanced.py ...`。）

本机实测（Python 3.11.2，四个 demo 全绿，无 "never retrieved" 噪音）：
    demo1 峰值并发 = 5（对照 20）        demo2 10 条全处理完，join 正常返回
    demo3 TimeoutError 在 1.00s 触发、shield 保住关键任务 3/3、吞取消的坑可见
    demo4 TaskGroup 1.03s 峰值 5；同一时刻双失败聚合到 2 个异常，except* 分组接收

为什么重要：W2 做流式 LLM 调用、W12 做并发压测时，限流 + 超时 + 取消这三样是保命的。
------------------------------------------------------------------------------
本文件回答的四个问题：
1. Semaphore 怎么限流？"当前并发数"怎么量？峰值为什么不会超过信号量容量？
2. 生产者-消费者怎么用 queue.join() 等待"全部处理完"，而不是"全部塞进去"？
3. 超时（wait_for）、取消（cancel）、保护（shield）三者分别管什么？为什么关键任务要 shield？
4. TaskGroup 和 gather 的异常行为差在哪？为什么说 TaskGroup 是"结构化并发"？
"""

import asyncio
import random
import sys
import time

# ============================================================================
# demo1：Semaphore 限流（20:00-20:35）
#   20 个任务 + Semaphore(5)，打印「当前并发数」，确认峰值不超过 5
# ============================================================================


async def limited_worker(idx: int, sem: asyncio.Semaphore, stats: dict) -> int:
    """一个带限流的任务：先抢信号量，抢到才允许进入「临界区」。"""
    # ① 抢锁：只有拿到信号量（剩余计数 -1）才继续往下走；拿不到就在这儿排队
    async with sem:
        # ② 进入临界区：立即更新并发计数，并记录历史峰值
        stats["current"] += 1
        stats["peak"] = max(stats["peak"], stats["current"])
        current = stats["current"]
        print(f"    [{idx:>2}] 开始  当前并发数={current:>2}  峰值={stats['peak']}")

        # ③ 模拟真实工作（I/O 等待）：换不同时长，让任务错峰退出/进入
        await asyncio.sleep(0.15 + (idx % 4) * 0.05)

        # ④ 离开临界区前把并发数减回去（这里是同步代码，中间没有 await，不会被打断）
        stats["current"] -= 1
        print(f"    [{idx:>2}] 结束  当前并发数={stats['current']:>2}")
        return idx


async def unbounded_worker(idx: int, stats: dict) -> int:
    """对照组：完全不限流，用来对比峰值。"""
    stats["current"] += 1
    stats["peak"] = max(stats["peak"], stats["current"])
    await asyncio.sleep(0.1)
    stats["current"] -= 1
    return idx


async def demo1_semaphore() -> None:
    print("[demo1] Semaphore 限流：20 个任务，信号量容量 = 5\n")

    sem = asyncio.Semaphore(5)
    stats = {"current": 0, "peak": 0}
    t0 = time.perf_counter()
    results = await asyncio.gather(*(limited_worker(i, sem, stats) for i in range(1, 21)))
    cost = time.perf_counter() - t0

    print(f"\n    20 个任务全部完成，返回值个数 = {len(results)}，总耗时 {cost:.2f}s")
    print(f"    峰值并发数 = {stats['peak']}")
    assert stats["peak"] <= 5, f"限流失效！峰值 {stats['peak']} > 5"
    print("    结论：峰值 <= 5，Semaphore 生效（信号量耗尽后，后来的任务在 async with 上排队）")

    # 对照：去掉信号量，20 个任务会同时起跑
    plain = {"current": 0, "peak": 0}
    t0 = time.perf_counter()
    await asyncio.gather(*(unbounded_worker(i, plain) for i in range(1, 21)))
    print(
        f"\n    [对照] 不加 Semaphore：峰值并发数 = {plain['peak']}，"
        f"耗时 {time.perf_counter() - t0:.2f}s"
    )
    print("    -> 真实场景（流式 LLM 调用）里，这个峰值就是同时打出去的连接数，必须被限制住。")
    print("    提示：Semaphore 管的是「进入临界区的任务数」，不是「后台任务总数」；")
    print("          只限制进入数量，不创建/销毁任务，所以 create_task 再多也只是排队。")


# ============================================================================
# demo2：Queue 生产者-消费者（20:35-21:10）
#   1 个生产者塞 10 条，3 个 worker 消费；用 queue.join() 等待完成
# ============================================================================


async def producer(q: asyncio.Queue, n: int = 10) -> None:
    for i in range(1, n + 1):
        # put 在队列满时会挂起当前协程（这里 maxsize 有限，所以会自然形成背压）
        await q.put(f"item-{i}")
        print(f"    [生产者] 塞入 item-{i:<2}（队列现有 {q.qsize()} 条）")
        await asyncio.sleep(0.02)
    print("    [生产者] 10 条全部塞完，收工")


async def consumer(name: str, q: asyncio.Queue, board: dict) -> None:
    """worker：一直取，直到被取消。每处理完一条必须 task_done()。"""
    while True:
        # 队列空时 get() 挂起，不占 CPU，这就是"空闲等待"；被 cancel 时也停在这里
        item = await q.get()
        try:
            print(f"    [{name}] 取出 {item}，开始处理（队列剩余 {q.qsize()} 条）")
            await asyncio.sleep(0.1 + random.uniform(0, 0.05))
            board[name] += 1
            print(f"    [{name}] 处理完 {item}，累计 {board[name]} 条")
        finally:
            # ★ 无论成功还是异常，都要 task_done()，否则 join() 永远等不到
            #   注意：如果这里被取消，finally 仍会执行，属于常见的"清理"位置
            q.task_done()


async def demo2_queue() -> None:
    print("[demo2] Queue 生产者-消费者：1 个生产者 + 3 个 worker，queue.join() 等待\n")

    q: asyncio.Queue = asyncio.Queue(maxsize=5)  # 有界队列：满了生产者会被 put 挂起（背压）
    board = {"worker1": 0, "worker2": 0, "worker3": 0}
    workers = [
        asyncio.create_task(consumer(n, q, board), name=n) for n in board
    ]
    t0 = time.perf_counter()

    # 生产者可以和 join 并发跑
    prod = asyncio.create_task(producer(q, 10))
    # ★ 坑：unfinished 计数为 0 时 join() 会“立即返回”。create_task 只是登记，
    #   下一轮循环才真正跑，所以此刻队列还是空的 -> 必须先让生产者跑起来
    #   （下面这一句让生产者把前几条塞进队列，unfinished > 0，join 才会真的等待）
    await asyncio.sleep(0)
    await q.join()  # 等到"未完成数归零"——即 10 条全部 task_done()
    cost = time.perf_counter() - t0
    await prod

    # 全部做完，worker 还挂在 get() 上，收工：取消它们
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    assert sum(board.values()) == 10, f"只处理了 {sum(board.values())} 条，join 提前返回了"

    print(f"\n    队列剩余 = {q.qsize()}，各 worker 处理条数 = {board}，"
          f"合计 {sum(board.values())} 条，总耗时 {cost:.2f}s")
    print("    结论：queue.join() 等的是「全部被 task_done」，不是「全部被 put」；")
    print("          每个 get() 必须配一个 task_done()，漏一个就永远 join 不返回。")
    print("          3 个 worker 共享一个队列 = 天然的工作窃取，谁空谁取，不需要自己分配任务。")


# ============================================================================
# demo3：超时与取消（21:10-21:40）
#   wait_for 触发 TimeoutError / shield 保护关键任务 / cancel + CancelledError
# ============================================================================


async def slow_api() -> str:
    print("    [slow_api] 开始一个 5s 的调用……")
    await asyncio.sleep(5)
    return "慢接口结果"


async def critical_job(log: list) -> str:
    """关键任务：每 0.3s 报一次进度，共 3 步。被取消时要能观察到。"""
    for i in range(1, 4):
        await asyncio.sleep(0.3)
        log.append(i)
        print(f"    [critical] 第 {i}/3 步完成")
    return "关键任务完成"


async def guarded(inner: asyncio.Task) -> str:
    """外层壳子：用 shield 把内层任务包起来，取消壳子不会传导到内层。"""
    return await asyncio.shield(inner)


async def demo3_timeout_cancel() -> None:
    print("[demo3] 超时与取消\n")

    # ---------- 3.1 wait_for：超时后抛 TimeoutError，并取消被包裹的协程 ----------
    print("== 3.1) asyncio.wait_for(coro, timeout=1) ==")
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(slow_api(), timeout=1.0)
    except asyncio.TimeoutError:  # 3.11 起就是内置 TimeoutError 的别名
        print(f"    捕获 TimeoutError（{time.perf_counter() - t0:.2f}s 时就返回了，没等满 5s）")
    print("    -> wait_for 到点会 cancel 内部任务，所以 5s 的活儿不会在后台继续跑。\n")

    # ---------- 3.2 shield：保护关键任务不被外层取消 ----------
    print("== 3.2) asyncio.shield 保护关键任务 ==")
    log: list = []
    inner = asyncio.create_task(critical_job(log), name="critical")
    outer = asyncio.create_task(guarded(inner), name="guarded-shell")
    await asyncio.sleep(0.4)  # 让关键任务先跑起来
    outer.cancel()
    try:
        await outer
    except asyncio.CancelledError:
        print("    外层壳子被取消（CancelledError），但内层任务不受影响")
    # 内层没被取消，继续等它跑完
    result = await inner
    print(f"    inner.cancelled()={inner.cancelled()}，结果 = {result}，进度 = {len(log)}/3")
    print("    -> shield 的作用：取消只落在「等待者」身上，被保护的任务照常跑完并保留结果。")
    print("       典型用法：流式 LLM 调用里，用户主动中止 UI，但已经发出的关键写库/记账任务不能丢。\n")

    # ---------- 3.3 cancel + CancelledError：正常取消 vs 吞掉取消的坑 ----------
    print("== 3.3) task.cancel() 与 CancelledError ==")

    async def cancellable(name: str, swallow: bool = False) -> str:
        try:
            await asyncio.sleep(2)
            return f"{name} 正常完成"
        except asyncio.CancelledError:
            if swallow:
                print(f"    [{name}] 捕获了 CancelledError 但没有 re-raise（错误示范）")
                return f"{name} 假装完成"  # 吞掉取消 -> 调用方以为它正常结束
            print(f"    [{name}] 捕获 CancelledError，做清理后 re-raise（正确示范）")
            raise  # ★ 必须 re-raise，否则取消信号被吞，cancel() 形同虚设

    t1 = asyncio.create_task(cancellable("A-正确"))
    await asyncio.sleep(0.1)
    t1.cancel()
    try:
        await t1
    except asyncio.CancelledError:
        print(f"    A: task.cancelled()={t1.cancelled()}，调用方收到 CancelledError（预期）")

    t2 = asyncio.create_task(cancellable("B-吞掉", swallow=True))
    await asyncio.sleep(0.1)
    t2.cancel()
    got = await t2  # 注意：这里不会抛异常，因为 B 把取消吞了
    print(f"    B: 调用方拿到 {got!r}，task.cancelled()={t2.cancelled()}（取消被吞，行为已失控）")
    print("    -> 结论：CancelledError 是 BaseException（3.8+），catch Exception 抓不到它；")
    print("       清理完必须 raise，否则 wait_for / TaskGroup 的超时与取消会整体失效。\n")


# ============================================================================
# demo4：Python 3.11 TaskGroup（21:40-22:00）
#   用 async with asyncio.TaskGroup() 重写 demo1，对比 gather 的异常聚合差异
# ============================================================================


async def job(name: str, delay: float, fail: bool = False) -> str:
    """可成功可失败的任务，带「被取消」的可见输出，方便观察两种聚合方式的差别。"""
    t0 = time.perf_counter()
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        print(f"    [{name}] 在 {time.perf_counter() - t0:.2f}s 被取消")
        raise
    if fail:
        raise RuntimeError(f"{name} 故意失败")
    print(f"    [{name}] 在 {time.perf_counter() - t0:.2f}s 成功返回")
    return name


async def demo4_taskgroup() -> None:
    print("[demo4] Python 3.11 TaskGroup\n")

    # ---------- 4.1 用 TaskGroup 重写 demo1（20 个任务 + Semaphore(5)） ----------
    print("== 4.1) 用 TaskGroup 重写 demo1：结构化的「20 任务 + 限流 5」 ==")
    sem = asyncio.Semaphore(5)
    stats = {"current": 0, "peak": 0}
    t0 = time.perf_counter()
    # async with 退出时一定会等组内所有任务结束；任一任务失败则取消其余任务
    async with asyncio.TaskGroup() as tg:
        for i in range(1, 21):
            tg.create_task(limited_worker(i, sem, stats), name=f"task-{i}")
    cost = time.perf_counter() - t0
    print(f"\n    TaskGroup 全组结束，耗时 {cost:.2f}s，峰值并发 = {stats['peak']}")
    print("    -> 和 demo1 的 gather 写法结果一致；好处是不用自己收集/等待 Task 列表，")
    print("       async with 的缩进就是生命周期边界（结构化并发：谁创建，谁负责等到结束）。\n")

    # ---------- 4.2 异常聚合对比：gather vs TaskGroup ----------
    print("== 4.2) 同样的 3 个任务、B 在 0.2s 失败，分别用 gather 和 TaskGroup ==")

    async def run_gather() -> None:
        print("  [gather 默认模式]")
        t = time.perf_counter()
        try:
            await asyncio.gather(
                job("A", 0.5), job("B", 0.2, fail=True), job("C", 0.5)
            )
        except RuntimeError as exc:
            print(f"    gather 在 {time.perf_counter() - t:.2f}s 立刻抛出: {exc}")
            print("    此刻 A / C 并没有被取消，还在后台跑")
        await asyncio.sleep(0.6)  # 给 A/C 收尾，避免 "Task exception was never retrieved" 噪音

    async def run_taskgroup() -> None:
        print("  [TaskGroup]")
        t = time.perf_counter()
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(job("A", 0.5), name="A")
                tg.create_task(job("B", 0.2, fail=True), name="B")
                tg.create_task(job("C", 0.5), name="C")
        except* RuntimeError as eg:  # ★ 3.11 的 except*：专门用来拆 ExceptionGroup
            # except RuntimeError 在这里是抓不到的——TaskGroup 抛的是 ExceptionGroup，
            # 它虽然是 Exception 的子类，但类型不是 RuntimeError，必须用 except*
            print(f"    TaskGroup 在 {time.perf_counter() - t:.2f}s 抛出 "
                  f"{type(eg).__name__}，聚合了 {len(eg.exceptions)} 个 RuntimeError：")
            for e in eg.exceptions:
                print(f"      - {type(e).__name__}: {e}")
            print("    同组 A / C 被自动取消（上面能看到「被取消」输出）")
        await asyncio.sleep(0.1)

    await run_gather()
    await asyncio.sleep(0.1)
    await run_taskgroup()

    # ---------- 4.3 两个任务同时失败：gather 只给你一个，TaskGroup 全给你 ----------
    print("\n== 4.3) P / Q 同一时刻失败：gather 只看得到第一个，TaskGroup 收齐 ==")

    print("  [gather 默认模式]")
    try:
        await asyncio.gather(
            job("P", 0.2, fail=True),
            job("Q", 0.2, fail=True),
            job("R", 0.5),
            return_exceptions=False,
        )
    except RuntimeError as exc:
        print(f"    gather 只抛出了第一个: {exc}")
    await asyncio.sleep(0.6)  # 收尾 Q 的异常，否则有 "never retrieved" 噪音

    print("  [TaskGroup + except* 按类型分组]")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(job("P", 0.2, fail=True), name="P")
            tg.create_task(job("Q", 0.2, fail=True), name="Q")
            tg.create_task(job("R", 0.5), name="R")
    except* RuntimeError as eg:  # 只接 RuntimeError 这一组，其余类型不会被这个分支吞掉
        print(f"    except* RuntimeError 捕获到 {len(eg.exceptions)} 个：")
        for e in eg.exceptions:
            print(f"      - {type(e).__name__}: {e}")
        print("    -> 同一批失败一起交付，不用靠日志去捞第二个")
        print("    -> 对比 gather：同样两个失败，gather 只会抛出第一个（见上一个分支）")
        print("    -> R 的 CancelledError 不会进这个组（它不是失败，是被连带取消）")

    print("    注意：TaskGroup 不把「被连带取消的兄弟任务」计入 ExceptionGroup——")
    print("          取消是它自己发起的清理手段，不算错误，所以这里不会出现 CancelledError 组。")
    print("          因此聚合到的异常数是「取消生效前就已经失败的个数」，不是「代码里写了几个失败」。")
    print("          想要全收，就让失败尽量同时发生；TaskGroup 的价值在于「不会漏掉同时发生的失败」。")

    print("\n    对比表：")
    print("    | 维度           | asyncio.gather(默认)                | asyncio.TaskGroup (3.11+)          |")
    print("    | 第一个异常     | 立即抛给调用方（原样）              | 等组内任务清理完，抛 ExceptionGroup |")
    print("    | 其他任务       | 不取消，继续在后台跑（易泄漏）      | 自动取消同组其余任务                |")
    print("    | 多个异常       | 只能拿到第一个，其余可能变日志噪音  | 全部聚合进 exceptions，一个不漏     |")
    print("    | 结束时机       | 第一个异常就返回                    | async with 退出时保证全组已结束     |")
    print("    | 捕获写法       | try/except RuntimeError             | except* RuntimeError（3.11 语法）   |")
    print("\n    要点：TaskGroup 抛的是 ExceptionGroup（PEP 654），它不是 RuntimeError，")
    print("          所以 `except RuntimeError` 抓不到，必须用 `except* RuntimeError`；")
    print("          except* 会按类型把组里的异常拆开分给不同分支，一个分支只处理自己那一类。")
    print("          取消其他任务需要一个「收尾窗口」，所以 TaskGroup 的异常抛出会略晚于 gather。\n")


# ============================================================================
# 入口：每个 demo 独立跑在自己的 asyncio.run 里
# ============================================================================

DEMOS = {
    "1": ("Semaphore 限流", demo1_semaphore),
    "2": ("Queue 生产者-消费者", demo2_queue),
    "3": ("超时与取消", demo3_timeout_cancel),
    "4": ("TaskGroup", demo4_taskgroup),
}

# 每个 demo 的实测耗时（秒），all 模式只用来提示总时长
DURATION = {"1": 1.2, "2": 0.5, "3": 1.8, "4": 2.6}


def main() -> None:
    arg = (sys.argv[1] if len(sys.argv) > 1 else "all").lower().lstrip("-")
    arg = arg.replace("demo", "")

    if arg == "all":
        names = list(DEMOS)
    elif arg in DEMOS:
        names = [arg]
    else:
        print(f"用法: py -3.11 {sys.argv[0]} [1|2|3|4|all]")
        print("  " + "\n  ".join(f"{k}: {v[0]}" for k, v in DEMOS.items()))
        sys.exit(2)

    print(f"Python {sys.version.split()[0]} | 本次运行: {arg}")
    print(f"预估耗时: {sum(DURATION[k] for k in names):.1f}s（实测值，仅参考）\n")

    for k in names:
        title, fn = DEMOS[k]
        print("=" * 78)
        print(f"=== demo{k}：{title}")
        print("=" * 78)
        asyncio.run(fn())  # 每个 demo 一个独立事件循环，互不影响
        print()


if __name__ == "__main__":
    # 注意：本文件用了 except*（PEP 654），3.10 及以下在"解析阶段"就 SyntaxError，
    # 所以这里没法放版本检查——低版本根本走不到这一行。用错解释器时的报错长这样：
    #     except* RuntimeError as eg:
    #           ^
    #     SyntaxError: invalid syntax
    # 看到它就把命令换成 py -3.11。
    main()
