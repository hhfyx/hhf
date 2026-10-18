"""从本地 lerobot/pusht 分片绘制数据曲线。

输出：
  pusht_curves.png        报告总览（6 面板）
  ep32_curve.png          §3 选定 episode 的 state/action/覆盖率
  three_class_curve.png   §2 三类样本（可以 / 存疑 / 不行 各 2 条）
  pusht_frames.png        视频抽帧（确认画面为 T 形方块 + 目标 + 推子）
"""
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).parent
ROOT = HERE / "pusht"
VIDEO = ROOT / "videos/observation.image/chunk-000/file-000.mp4"
FPS = 10

# pusht 的 2 维为平面坐标；按 lerobot/pusht 定义 state=推子位置、action=下一目标位置
DIM_CN = ["位置x", "位置y"]
C = {"x": "#4C78A8", "y": "#F58518", "r": "#888888"}

EPS3 = 32  # §3 选定 episode（终点覆盖率最高）


def load():
    d = pq.read_table(ROOT / "data/chunk-000/file-000.parquet").to_pandas()
    e = pq.read_table(ROOT / "meta/episodes/chunk-000/file-000.parquet").to_pandas()
    S = np.stack([np.asarray(v, float) for v in d["observation.state"]])
    A = np.stack([np.asarray(v, float) for v in d["action"]])
    return d, e, S, A


def seg(d, S, A, i):
    m = d["episode_index"].values == i
    return S[m], A[m], d["timestamp"].values[m], d["next.reward"].values[m].astype(float)


def overview(d, e, S, A):
    L = e["length"].astype(int).values
    EI = d["episode_index"].values
    fin = np.array([d["next.reward"].values[EI == i][-1] for i in range(len(e))])
    ic = np.array([int(np.asarray(v).reshape(-1)[0]) for v in e["stats/observation.image/count"]])

    fig, ax = plt.subplots(3, 2, figsize=(14, 12))
    fig.suptitle("lerobot/pusht 数据曲线（本地分片实测）", fontsize=15, fontweight="bold")

    # ① 长度分布
    a = ax[0, 0]
    a.hist(L, bins=30, color="#4C78A8", edgecolor="white")
    a.axvline(np.median(L), color="#E45756", ls="--", label=f"中位数 {int(np.median(L))}")
    a.axvline(L.mean(), color="#F58518", ls=":", label=f"均值 {L.mean():.0f}")
    a.set_title(f"① episode 长度分布（CV={L.std()/L.mean():.2f}，比 droid 集中得多）")
    a.set_xlabel("帧数"); a.set_ylabel("episode 数"); a.legend()

    # ② 长度排序
    a = ax[0, 1]
    a.plot(np.sort(L), color="#4C78A8", lw=2)
    a.axhline(200, color="#E45756", ls="--", label="200 帧（20s）")
    a.axhline(60, color="#54A24B", ls=":", label="60 帧（6s）")
    a.set_title("② episode 长度排序曲线（无极端长尾，49~246 帧）")
    a.set_xlabel("episode 序号（按长度升序）"); a.set_ylabel("帧数"); a.legend()

    s, act, t, r = seg(d, S, A, EPS3)
    # ③ state 2 维
    a = ax[1, 0]
    a.plot(t, s[:, 0], lw=1.4, color=C["x"], label=DIM_CN[0])
    a.plot(t, s[:, 1], lw=1.4, color=C["y"], label=DIM_CN[1])
    a.set_title(f"③ state 2 维时序（episode {EPS3}，{len(s)} 帧）— 平滑连续")
    a.set_xlabel("时间 (s)"); a.set_ylabel("state（像素）"); a.legend()

    # ④ action 2 维
    a = ax[1, 1]
    a.plot(t, act[:, 0], lw=1.4, color=C["x"], label=DIM_CN[0])
    a.plot(t, act[:, 1], lw=1.4, color=C["y"], label=DIM_CN[1])
    a.set_title("④ action 2 维时序 — 整数像素阶梯（量化到 1px）")
    a.set_xlabel("时间 (s)"); a.set_ylabel("action（像素，整数）"); a.legend()

    # ⑤ 终点覆盖率 vs 长度（问题A）
    a = ax[2, 0]
    a.scatter(L, fin, s=18, color="#54A24B", alpha=0.8, label="每条终点覆盖率")
    a.axhline(0.95, color="#E45756", ls="--", label="0.95 成功阈值（0 条达标）")
    a.set_ylim(0.78, 1.0)
    a.set_title("⑤ 终点覆盖率 0.813~0.949，全部低于 0.95（问题A）")
    a.set_xlabel("episode 长度（帧）"); a.set_ylabel("末帧 next.reward"); a.legend()

    # ⑥ 图像 stats count（问题C）
    a = ax[2, 1]
    a.scatter(L, ic, s=18, color="#4C78A8", alpha=0.8, label="逐段图像 count")
    a.plot([L.min(), L.max()], [L.min(), L.max()], color="#E45756", ls="--", label="若覆盖全部帧 (y=x)")
    a.axhline(100, color="#54A24B", ls=":", label="截样上限 100")
    a.set_title("⑥ 图像统计 count = min(长度,100)，仅覆盖 76.5% 帧（问题C）")
    a.set_xlabel("episode 长度（帧）"); a.set_ylabel("image stats count"); a.legend()

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = HERE / "pusht_curves.png"
    fig.savefig(out, dpi=130)
    print("已保存:", out)


def ep_curve(d, S, A):
    s, act, t, r = seg(d, S, A, EPS3)
    fig = plt.figure(figsize=(11, 9))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.25, 1])

    a = fig.add_subplot(gs[0, :])
    a.plot(t, s[:, 0], lw=1.6, color=C["x"], ls="-")
    a.plot(t, act[:, 0], lw=1.3, color=C["x"], ls="--", alpha=0.85)
    a.plot(t, s[:, 1], lw=1.6, color=C["y"], ls="-")
    a.plot(t, act[:, 1], lw=1.3, color=C["y"], ls="--", alpha=0.85)
    a.set_title(f"episode {EPS3}：state（实线）/ action（虚线）2 维时序（{len(s)} 帧，{len(s)/FPS:.1f}s）")
    a.set_xlabel("时间 (s)"); a.set_ylabel("像素坐标")
    h = [Line2D([], [], color=C["x"], lw=2, label="位置x"),
         Line2D([], [], color=C["y"], lw=2, label="位置y"),
         Line2D([], [], color="k", ls="-", lw=1.4, label="实际状态（实线）"),
         Line2D([], [], color="k", ls="--", lw=1.4, label="目标指令（虚线）")]
    a.legend(handles=h, fontsize=9, ncol=4)

    a = fig.add_subplot(gs[1, 0])
    a.plot(t, r, lw=1.8, color="#54A24B")
    a.set_title("任务进度：next.reward（覆盖率）随时间升高")
    a.set_xlabel("时间 (s)"); a.set_ylabel("覆盖率"); a.set_ylim(0, 1)

    a = fig.add_subplot(gs[1, 1])
    sc = a.scatter(s[:, 0], s[:, 1], c=r, cmap="viridis", s=22)
    a.plot(s[0, 0], s[0, 1], "o", color="#E45756", ms=9, label="起点")
    a.plot(s[-1, 0], s[-1, 1], "*", color="#E45756", ms=14, label="终点")
    a.set_xlim(0, 512); a.set_ylim(512, 0)
    a.set_title("推子轨迹（颜色=同一帧的覆盖率）")
    a.set_xlabel("位置x"); a.set_ylabel("位置y"); a.legend(fontsize=8)
    fig.colorbar(sc, ax=a, fraction=0.046, label="覆盖率")

    fig.tight_layout()
    out = HERE / "ep32_curve.png"
    fig.savefig(out, dpi=130)
    print("已保存:", out)


def three_class(d, S, A):
    # 各类取"类内中位覆盖率"附近样本作代表（而非类内极值），避免以端点代表整类
    picks = [(33, "可以"), (160, "可以"), (90, "存疑"),
             (178, "存疑"), (45, "不行"), (113, "不行")]
    fig, ax = plt.subplots(3, 2, figsize=(13, 11))
    fig.suptitle("三类样本的 state（实线）/ action（虚线）2 维时序 + 覆盖率"
                 "（各类取类内中位覆盖率附近的代表样本，各 2 条，本地实测）", fontsize=13, fontweight="bold")
    for k, (ep, cls) in enumerate(picks):
        a = ax[k // 2, k % 2]
        s, act, t, r = seg(d, S, A, ep)
        a.plot(t, s[:, 0], lw=1.4, color=C["x"], ls="-")
        a.plot(t, act[:, 0], lw=1.1, color=C["x"], ls="--", alpha=0.8)
        a.plot(t, s[:, 1], lw=1.4, color=C["y"], ls="-")
        a.plot(t, act[:, 1], lw=1.1, color=C["y"], ls="--", alpha=0.8)
        a.set_title(f"{cls} ｜ episode {ep} ｜ {len(s)} 帧 / {len(s)/FPS:.1f}s ｜ 终点覆盖率 {r[-1]:.3f}")
        a.set_xlabel("时间 (s)"); a.set_ylabel("像素坐标")
        a2 = a.twinx()
        a2.plot(t, r, color=C["r"], lw=1.6, ls=":")
        a2.set_ylabel("覆盖率", color=C["r"], fontsize=8)
        a2.set_ylim(0, 1)
        a2.tick_params(axis="y", colors=C["r"], labelsize=7)
        if k == 0:
            h = [Line2D([], [], color=C["x"], lw=2, label="位置x"),
                 Line2D([], [], color=C["y"], lw=2, label="位置y"),
                 Line2D([], [], color="k", ls="-", lw=1.4, label="实际状态（实线）"),
                 Line2D([], [], color="k", ls="--", lw=1.4, label="目标指令（虚线）"),
                 Line2D([], [], color=C["r"], ls=":", lw=1.6, label="覆盖率（右轴）")]
            a.legend(handles=h, fontsize=7, loc="lower right")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = HERE / "three_class_curve.png"
    fig.savefig(out, dpi=130)
    print("已保存:", out)


def frames():
    cap = cv2.VideoCapture(str(VIDEO))
    idxs = [0, 40, 80, 120, 160]
    imgs = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if ok:
            imgs.append(cv2.resize(fr, (256, 256), interpolation=cv2.INTER_NEAREST))
    cap.release()
    if imgs:
        strip = np.hstack(imgs)
        cv2.putText(strip, "ep0  t=0s -> 16s", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        # cv2.imwrite 不支持非 ASCII 路径，改用 imencode + tofile
        ok, buf = cv2.imencode(".png", strip[:, :, ::-1])
        if ok:
            buf.tofile(str(HERE / "pusht_frames.png"))
            print("已保存:", HERE / "pusht_frames.png")


def main():
    d, e, S, A = load()
    overview(d, e, S, A)
    ep_curve(d, S, A)
    three_class(d, S, A)
    frames()


if __name__ == "__main__":
    main()