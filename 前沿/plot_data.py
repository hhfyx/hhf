"""从本地 droid_100 分片绘制数据曲线，直观呈现报告中的问题。
输出：droid_100_curves.png
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).parent / "droid_100"
OUT = Path(__file__).parent / "droid_100_curves.png"

# 7 维的中文图例（对应元数据 motor_0~motor_6；按取值范围推断为末端位姿 + 夹爪）
MOTOR_CN = ["位置x", "位置y", "位置z", "姿态rx", "姿态ry", "姿态rz", "夹爪"]


def main():
    frames = pq.read_table(ROOT / "data/chunk-000/file-000.parquet").to_pandas()
    eps = pq.read_table(ROOT / "meta/episodes/chunk-000/file-000.parquet").to_pandas()
    L = eps["length"].astype(int).values
    fps = 15

    fig, ax = plt.subplots(3, 2, figsize=(14, 12))
    fig.suptitle("droid_100 数据曲线（本地分片实测）", fontsize=15, fontweight="bold")

    # 1) episode 长度分布
    a = ax[0, 0]
    a.hist(L, bins=40, color="#4C78A8", edgecolor="white")
    a.axvline(np.median(L), color="#E45756", ls="--", label=f"中位数 {int(round(np.median(L)))}")
    a.axvline(L.mean(), color="#F58518", ls=":", label=f"均值 {L.mean():.0f}")
    a.set_title("① episode 长度分布（强右偏，CV=0.85）")
    a.set_xlabel("帧数")
    a.set_ylabel("episode 数")
    a.legend()

    # 2) episode 长度排序曲线（展示长尾）
    a = ax[0, 1]
    a.plot(np.sort(L), color="#4C78A8", lw=2)
    a.axhline(1000, color="#E45756", ls="--", label="1000 帧")
    a.set_title("② episode 长度排序曲线（长尾 5 条 > 1000 帧）")
    a.set_xlabel("episode 序号（按长度升序）")
    a.set_ylabel("帧数")
    a.legend()

    # 取一条长 episode 画时序
    long_idx = int(eps.loc[eps["length"].astype(int).idxmax(), "episode_index"])
    sub = frames[frames["episode_index"] == long_idx].sort_values("frame_index")
    S = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in sub["observation.state"]])
    A = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in sub["action"]])
    t = sub["timestamp"].values

    # 3) state 7 维时序
    a = ax[1, 0]
    for d in range(S.shape[1]):
        a.plot(t, S[:, d], lw=1.2, label=MOTOR_CN[d])
    a.set_title(f"③ state 7 维时序（episode {long_idx}，{len(sub)} 帧）")
    a.set_xlabel("时间 (s)")
    a.set_ylabel("state 原始值")
    a.legend(fontsize=7, ncol=2)

    # 4) action 7 维时序
    a = ax[1, 1]
    for d in range(A.shape[1]):
        a.plot(t, A[:, d], lw=1.2, label=MOTOR_CN[d])
    a.set_title("④ action 7 维时序（已归一化到约 [-1,1]）")
    a.set_xlabel("时间 (s)")
    a.set_ylabel("action 值")
    a.legend(fontsize=7, ncol=2)

    # 5) 图像 stats count 与 episode 长度散点（问题4）
    a = ax[2, 0]
    cam = "observation.images.wrist_image_left"
    cnt = eps[f"stats/{cam}/count"].apply(lambda v: int(np.asarray(v).reshape(-1)[0])).values
    a.scatter(L, cnt, s=18, color="#54A24B", alpha=0.8, label="逐段图像 count")
    a.plot([L.min(), L.max()], [L.min(), L.max()], color="#E45756", ls="--",
           label="若覆盖全部帧 (y=x)")
    a.set_title("⑤ 图像统计仅覆盖约 33% 帧（问题4）")
    a.set_xlabel("episode 长度（帧）")
    a.set_ylabel("图像 stats count")

    # 6) state vs action 各维取值范围（问题5）
    a = ax[2, 1]
    Sall = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in frames["observation.state"]])
    Aall = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in frames["action"]])
    dims = np.arange(Sall.shape[1])
    a.bar(dims - 0.2, Sall.max(0) - Sall.min(0), width=0.4, color="#4C78A8", label="state 跨度(max-min)")
    a.bar(dims + 0.2, Aall.max(0) - Aall.min(0), width=0.4, color="#F58518", label="action 跨度")
    a.set_title("⑥ state 与 action 各维尺度对比（问题5）")
    a.set_xlabel("维度")
    a.set_ylabel("取值范围跨度")
    a.set_xticks(dims)
    a.legend()

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT, dpi=130)
    print("已保存:", OUT)

    # 单独为报告 §3（曲线解读）出 ep77：state / action 双面板
    ep77 = 77
    s77 = frames[frames["episode_index"] == ep77].sort_values("frame_index")
    S77 = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in s77["observation.state"]])
    A77 = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in s77["action"]])
    t77 = s77["timestamp"].values
    fig2, ax2 = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for d in range(S77.shape[1]):
        ax2[0].plot(t77, S77[:, d], lw=1.3, label=MOTOR_CN[d])
    ax2[0].set_title(f"state 7 维时序（episode {ep77}，{len(s77)} 帧）— 整体平缓")
    ax2[0].set_ylabel("state 原始值")
    ax2[0].legend(fontsize=8, ncol=4)
    for d in range(A77.shape[1]):
        ax2[1].plot(t77, A77[:, d], lw=1.3, label=MOTOR_CN[d])
    ax2[1].set_title("action 7 维时序 — 全程剧烈震荡")
    ax2[1].set_xlabel("时间 (s)")
    ax2[1].set_ylabel("action 值")
    ax2[1].legend(fontsize=8, ncol=4)
    fig2.tight_layout()
    out77 = Path(__file__).parent / "ep77_curve.png"
    fig2.savefig(out77, dpi=130)
    print("已保存:", out77)

    # 三类样本（可以/不行/存疑 各 2 条）的 state/action 时序曲线，供报告 §2 使用
    picks = [(38, "可以"), (71, "可以"), (79, "不行"),
             (61, "不行"), (84, "存疑"), (27, "存疑")]
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    fig3, ax3 = plt.subplots(3, 2, figsize=(13, 11))
    fig3.suptitle("三类样本的 state（实线）/ action（虚线）7 维时序对比"
                  "（可以 / 不行 / 存疑 各 2 条）", fontsize=14, fontweight="bold")
    for k, (ep, cls) in enumerate(picks):
        a = ax3[k // 2, k % 2]
        s = frames[frames["episode_index"] == ep].sort_values("frame_index")
        S = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in s["observation.state"]])
        A = np.stack([np.asarray(v, dtype=float).reshape(-1) for v in s["action"]])
        t = s["timestamp"].values
        for d in range(S.shape[1]):
            c = colors[d % len(colors)]
            a.plot(t, S[:, d], color=c, lw=1.1, ls="-")
            a.plot(t, A[:, d], color=c, lw=0.9, ls="--", alpha=0.85)
        a.set_title(f"{cls} ｜ episode {ep} ｜ {len(s)} 帧 / {len(s) / fps:.1f}s")
        a.set_xlabel("时间 (s)")
        a.set_ylabel("数值")
        handles = [Line2D([], [], color=colors[d], lw=1.4, label=MOTOR_CN[d])
                   for d in range(S.shape[1])]
        handles += [Line2D([], [], color="k", ls="-", lw=1.2, label="实际状态（实线）"),
                    Line2D([], [], color="k", ls="--", lw=1.2, label="目标指令（虚线）")]
        a.legend(handles=handles, fontsize=6, ncol=5)
    fig3.tight_layout(rect=[0, 0, 1, 0.97])
    out3 = Path(__file__).parent / "six_episodes_curve.png"
    fig3.savefig(out3, dpi=130)
    print("已保存:", out3)


if __name__ == "__main__":
    main()