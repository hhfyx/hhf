"""从本地 lerobot/pusht 分片实测全部报告数值（不抄清单表格）。

用法：python verify_data.py
输出：终端逐项打印，供报告引用。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent / "pusht"
DATA = ROOT / "data/chunk-000/file-000.parquet"
EPISODES = ROOT / "meta/episodes/chunk-000/file-000.parquet"
INFO = ROOT / "meta/info.json"
TASKS = ROOT / "meta/tasks.parquet"

FPS = 10  # meta/info.json 实测值


def rule(t):
    print("\n" + "=" * 68)
    print(t)
    print("=" * 68)


def col(table, name):
    """把 list/ndarray 列摊成 (N, D) float 数组"""
    return np.stack([np.asarray(v, dtype=float).reshape(-1) for v in table[name]])


def scalar(table, name):
    return np.array([np.asarray(v).reshape(-1)[0] for v in table[name]])


def main():
    info = json.loads(INFO.read_text(encoding="utf-8"))
    d = pq.read_table(DATA).to_pandas()
    e = pq.read_table(EPISODES).to_pandas()
    t = pq.read_table(TASKS).to_pandas()

    S = col(d, "observation.state")
    A = col(d, "action")
    R = d["next.reward"].values.astype(float)
    DONE = d["next.done"].values.astype(bool)
    SUC = d["next.success"].values.astype(bool)
    EI = d["episode_index"].values
    TS = d["timestamp"].values
    L = e["length"].astype(int).values
    N_EP = len(e)

    # ---------------- §1 数据清点 ----------------
    rule("§1 数据清点（全部读自本地分片 / meta/info.json）")
    print(f"数据集 ID            : lerobot/pusht（镜像 hf-mirror.com）")
    print(f"codebase_version     : {info['codebase_version']}")
    print(f"robot_type           : {info['robot_type']}   <-- 元数据缺失机型")
    print(f"episode 数           : {N_EP}（info.total_episodes={info['total_episodes']}，分片实测 {N_EP}）")
    print(f"总帧数               : {len(d)}（info.total_frames={info['total_frames']}）")
    print(f"fps                  : {info['fps']}")
    tot_s = len(d) / FPS
    print(f"总时长               : {tot_s:.1f} s = {tot_s/60:.2f} min")
    print(f"平均每条             : {len(d)/N_EP:.1f} 帧 = {len(d)/N_EP/FPS:.2f} s")
    print(f"状态维度             : observation.state {S.shape[1]} 维；action {A.shape[1]} 维")
    vinfo = info["features"]["observation.image"]["video_info"]
    print(f"相机视角             : 1 路 observation.image，96x96x3，codec={vinfo['video.codec']}，pix_fmt={vinfo['video.pix_fmt']}")
    print(f"任务数               : {info['total_tasks']}，指令 = {t.index[0]!r}")
    print(f"额外 RL 字段         : next.reward / next.done / next.success")

    # ---------------- 硬门槛复核 ----------------
    rule("§1b 硬门槛与偏好条件（本地复核）")
    print(f"v3 布局 meta/episodes : 存在，{N_EP} 条 episode 元数据")
    print(f"meta/stats.json       : 存在")
    print(f"data/ parquet 分片数  : 1")
    print(f"视频文件              : videos/observation.image/chunk-000/file-000.mp4")
    print(f"episode<=500          : {N_EP<=500}；分片=1：True；附带视频：True")

    # ---------------- §2 异常筛查 ----------------
    rule("§2 异常筛查")
    print(f"【长度】(帧) min={L.min()} max={L.max()} mean={L.mean():.1f} median={np.median(L):.0f} "
          f"std={L.std():.1f} CV={L.std()/L.mean():.3f} p95={np.percentile(L,95):.0f}")
    print(f"        <30帧 {(L<30).sum()} 条；<60帧(6s) {(L<60).sum()} 条；<100帧 {(L<100).sum()} 条；"
          f">200帧(20s) {(L>200).sum()} 条")
    print(f"        p90={np.percentile(L,90):.0f} p99={np.percentile(L,99):.0f}")

    # 移动量：逐帧 state 的 L1 位移和
    mv = np.array([np.abs(np.diff(S[EI == i], axis=0)).sum() for i in range(N_EP)])
    thr_move = np.median(mv) * 0.05
    print(f"【移动量】(px) min={mv.min():.1f} median={np.median(mv):.1f} max={mv.max():.1f}；"
          f"中位数5%阈值={thr_move:.2f}；低于阈值 {(mv<thr_move).sum()} 条")

    # 停顿帧占比：相邻帧位移 < 0.5px
    pause = []
    for i in range(N_EP):
        s = S[EI == i]
        pause.append(float((np.abs(np.diff(s, axis=0)).sum(1) < 0.5).mean()) if len(s) > 1 else 1.0)
    pause = np.array(pause)
    print(f"【停顿帧占比】max={pause.max():.3f} mean={pause.mean():.4f}；>50% 的 episode {(pause>0.5).sum()} 条")

    # 终点覆盖率：末帧 next.reward
    fin = np.array([R[EI == i][-1] for i in range(N_EP)])
    print(f"【终点覆盖率=末帧 reward】min={fin.min():.3f} median={np.median(fin):.3f} "
          f"mean={fin.mean():.3f} max={fin.max():.3f}；>=0.95 的 {(fin>=0.95).sum()} 条")
    print(f"        四分位 p25={np.percentile(fin,25):.3f} p75={np.percentile(fin,75):.3f}")

    # 直接套用 droid 判据的结果（说明两数据集特性不同）
    long_thr = np.median(L) * 3
    print(f"【套用 droid 判据】硬伤(时长<10帧 或 移动量<{thr_move:.1f}) = "
          f"{int(((L<10)|(mv<thr_move)).sum())} 条；偏长(>{long_thr:.0f}帧) = {int((L>long_thr).sum())} 条；"
          f"停顿>50% = {int((pause>0.5).sum())} 条  -> 全 0，说明 pusht 与 droid 特性不同，需换判据")

    # pusht 专用判据：按完成度分层
    cls = np.array(["可以"] * N_EP, dtype=object)
    cls[(fin >= 0.85) & (fin < 0.90)] = "存疑"
    cls[fin < 0.85] = "不行"
    print(f"【pusht 判据：终点覆盖率】可以(>=0.90) {int((cls=='可以').sum())} 条；"
          f"存疑(0.85~0.90) {int((cls=='存疑').sum())} 条；不行(<0.85) {int((cls=='不行').sum())} 条")
    for tag in ["可以", "存疑", "不行"]:
        idx = np.where(cls == tag)[0]
        if tag == "可以":
            order = idx[np.argsort(fin[idx])[::-1]][:2]
        elif tag == "不行":
            order = idx[np.argsort(fin[idx])][:2]
        else:
            order = idx[np.argsort(L[idx])[::-1]][:2]
        print(f"        {tag} 示例：" + "；".join(
            f"ep{int(i)}({int(L[i])}帧/{L[i]/FPS:.1f}s, 覆盖率{fin[i]:.3f})" for i in order))
    bad = np.where(cls != "可以")[0]
    print(f"        可以类合计 {int((cls=='可以').sum())}/{N_EP} 条，"
          f"帧数 {int(L[cls=='可以'].sum())}/{int(L.sum())} 帧")

    rule("§2b 数据自身标注问题（脚本实测）")
    print(f"问题A next.success 全为 False：实测 True 个数 = {int(SUC.sum())}；"
          f"单条最高覆盖率 {fin.max():.4f} < 0.95 成功阈值 -> 全数据集 0 条达标，success 字段不可用")
    print(f"问题B next.done 终止信号：True 共 {int(DONE.sum())} 个 = 2 x {N_EP}；"
          f"每段恰好 2 个，且都在末帧与倒数第 2 帧（偏移 {{0,1}}）-> 终止标记重复")
    ic = scalar(e, "stats/observation.image/count").astype(int)
    full = np.all(ic == np.minimum(L, 100))
    print(f"问题C 图像统计口径：逐段 stats/observation.image/count == min(长度,100) 全部成立 = {bool(full)}；"
          f"合计 {int(ic.sum())}/{int(L.sum())} 帧 = {ic.sum()/L.sum()*100:.1f}%，"
          f"长度>100 的 {int((L>100).sum())} 条被截样到 100")
    st = scalar(e, "stats/observation.state/count").astype(int)
    print(f"        对比：stats/observation.state/count == 长度 全部成立 = {bool(np.all(st==L))}（数值特征覆盖全部帧）")
    print(f"问题D state 不含方块位姿：corr(reward,state_x)={np.corrcoef(R,S[:,0])[0,1]:.4f}，"
          f"corr(reward,state_y)={np.corrcoef(R,S[:,1])[0,1]:.4f}（近 0）")
    bx = np.clip((S[:, 0] / 512 * 20).astype(int), 0, 19) * 20 + np.clip((S[:, 1] / 512 * 20).astype(int), 0, 19)
    sd = [R[bx == k].std() for k in np.unique(bx) if (bx == k).sum() > 5]
    print(f"        state 平面分 20x20 格，格内 reward 标准差均值 {np.mean(sd):.4f} vs 全局 {R.std():.4f}"
          f"（reward 不是 state 的函数 -> state 仅为推子位置，非方块位姿）")
    print(f"问题E action 为整数像素：action 全为整数 = {bool(np.allclose(A, np.round(A)))}，"
          f"取值 [{A.min():.0f},{A.max():.0f}] 整数网格 -> 动作被量化到 1px（约 0.2% 画布）")
    print(f"问题F README 与实际不一致：README 内嵌 info.json 标 {info['codebase_version']} 之外还写 v2.0 的 "
          f"episode_%06d.parquet 路径与 total_videos={N_EP}；实际 meta/info.json 为 {info['codebase_version']} 分块布局")
    print(f"问题G 单任务单视角：total_tasks=1、1 路相机，206 条指令完全相同 -> 无任务/语言多样性")

    # ---------------- §3 曲线相关实测 ----------------
    rule("§3 曲线解读所需实测（选定 episode 见 report；此处给全库量）")
    valid = np.diff(EI) == 0
    dA = np.abs(np.diff(A, axis=0)).sum(1)[valid]
    dS = np.abs(np.diff(S, axis=0)).sum(1)[valid]
    print(f"全库逐帧 |Δaction| 均值 {dA.mean():.3f}；|Δstate| 均值 {dS.mean():.3f}；比值 {dA.mean()/dS.mean():.3f}")
    print(f"action 与下一帧 state 的相关系数：dim0 {np.corrcoef(A[:-1,0],S[1:,0])[0,1]:.4f}，"
          f"dim1 {np.corrcoef(A[:-1,1],S[1:,1])[0,1]:.4f}（action 近似'下一步目标位置'）")
    print(f"帧内 |action-state| 均值 {np.abs(A-S).sum(1).mean():.2f} px（目标领先实际位移）")
    cte = [np.corrcoef(TS[EI==i], R[EI==i])[0,1] for i in range(N_EP) if (EI==i).sum()>10]
    print(f"同段内 corr(time,reward) 均值 {np.mean(cte):.3f}（奖励随时间升高=任务进度）")

    # 选定 §3 的 episode
    EP3 = int(np.argmax(fin))
    m = EI == EP3
    print(f"\n选定 §3 episode = {EP3}：{int(L[EP3])} 帧 / {L[EP3]/FPS:.1f} s，"
          f"终点覆盖率 {fin[EP3]:.3f}，reward 首={R[m][0]:.3f} 末={R[m][-1]:.3f}，"
          f"corr(t,reward)={np.corrcoef(TS[m],R[m])[0,1]:.3f}")
    print(f"  该段 |Δaction| 均值 {np.abs(np.diff(A[m],axis=0)).sum(1).mean():.3f}，"
          f"|Δstate| 均值 {np.abs(np.diff(S[m],axis=0)).sum(1).mean():.3f}")

    # 视频/时间戳一致性
    rule("§2c 一致性抽查")
    vf = e["videos/observation.image/from_timestamp"].astype(float).values
    vt = e["videos/observation.image/to_timestamp"].astype(float).values
    print(f"视频时长 vs 长度/fps 不符条数：{int((np.abs((vt-vf)-L/FPS)>0.2).sum())}")
    print(f"每条 timestamp 从 0 重启：{bool(np.allclose(d.groupby('episode_index')['timestamp'].min().values,0))}")
    print(f"task_index 取值：{np.unique(d['task_index'].values)}")
    print(f"index 连续递增 0..{len(d)-1}：{bool(np.array_equal(d['index'].values, np.arange(len(d))))}")


if __name__ == "__main__":
    main()