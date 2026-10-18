"""最小数据加载 / 清洗示例 + 报告问题复核
仅用本地已下载的 droid_100 分片（pandas + pyarrow，不依赖 lerobot 包）。
逐条用实测数据验证 droid_100_report.md 里列出的 8 个问题。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).parent / "droid_100"
DATA = ROOT / "data/chunk-000/file-000.parquet"
EPISODES = ROOT / "meta/episodes/chunk-000/file-000.parquet"
TASKS = ROOT / "meta/tasks.parquet"
INFO = ROOT / "meta/info.json"
STATS = ROOT / "meta/stats.json"


def load_frames() -> pd.DataFrame:
    """逐帧数据：state/action 为 7 维向量，展开成列便于计算"""
    df = pq.read_table(DATA).to_pandas()
    df["state_vec"] = df["observation.state"].apply(lambda v: np.asarray(v, dtype=np.float64))
    df["action_vec"] = df["action"].apply(lambda v: np.asarray(v, dtype=np.float64))
    return df


def load_episodes() -> pd.DataFrame:
    return pq.read_table(EPISODES).to_pandas()


def load_tasks() -> pd.DataFrame:
    df = pq.read_table(TASKS).to_pandas()
    # tasks.parquet 的文本存在 __index_level_0__，pyarrow 会把它读成 pandas 索引（无名）
    df = df.reset_index().rename(columns={"index": "task_text"})
    return df[["task_index", "task_text"]]


def sec(frames: float, fps: float) -> float:
    return frames / fps


def bullet(title: str):
    print("\n" + "-" * 60)
    print(title)
    print("-" * 60)


def main():
    info = json.loads(INFO.read_text(encoding="utf-8"))
    stats = json.loads(STATS.read_text(encoding="utf-8"))
    fmt = info.get("features", {})
    fps = info["fps"]
    total_frames = info["total_frames"]

    frames = load_frames()
    eps = load_episodes()
    tasks = load_tasks()

    print("=" * 60)
    print("droid_100 本地分片加载 / 清洗示例")
    print("=" * 60)
    print(f"逐帧表: {frames.shape}   episode 表: {eps.shape}   task 表: {tasks.shape}")
    print(f"info.json: total_episodes={info['total_episodes']}  total_frames={total_frames}  fps={fps}")

    # ---------- 问题1：空语言指令 ----------
    bullet("问题1  空语言指令")
    empty_tasks = tasks[tasks["task_text"].astype(str).str.strip() == ""]
    empty_idx = set(empty_tasks["task_index"].tolist())
    print(f"tasks.parquet 共 {len(tasks)} 条任务，其中空文本 {len(empty_tasks)} 条 -> task_index={sorted(empty_idx)}")
    eps["has_task"] = eps["tasks"].apply(
        lambda lst: any(str(t).strip() != "" for t in (lst if lst is not None else []))
    )
    n_empty_ep = int((~eps["has_task"]).sum())
    print(f"引用空任务的 episode：{n_empty_ep}/{len(eps)}  ({n_empty_ep / len(eps):.0%})")
    if len(empty_idx):
        # 用逐帧表交叉验证：task_index 落在空集合里的帧数
        n_empty_frames = int(frames["task_index"].isin(empty_idx).sum())
        print(f"交叉验证：task_index 为空任务的帧数 {n_empty_frames}/{total_frames} ({n_empty_frames/total_frames:.0%})")

    # ---------- 问题2：极端短样本 ----------
    bullet("问题2  极端短样本")
    L = eps["length"].astype(int)
    shortest = eps.loc[L.idxmin(), ["episode_index", "length"]]
    print(f"最短 episode: idx={int(shortest['episode_index'])}  {int(shortest['length'])} 帧 ({sec(int(shortest['length']), fps):.2f}s)")
    for thr in (30, 60, 100):
        c = int((L < thr).sum())
        print(f"  <{thr} 帧: {c} 条")

    # ---------- 问题3：长度分布偏斜 ----------
    bullet("问题3  长度分布偏斜")
    print(f"min={L.min()}  max={L.max()}  mean={L.mean():.0f}  median={L.median():.0f}  "
          f"std={L.std():.0f}  CV={L.std()/L.mean():.2f}  p95={np.percentile(L, 95):.0f}")
    top3 = eps.nlargest(3, "length")[["episode_index", "length"]]
    print("最长 3 条: " + ", ".join(f"idx={int(r.episode_index)}:{int(r.length)}帧" for r in top3.itertuples()))
    print(f"最长约 {sec(int(L.max()), fps):.1f}s，与最短相差 {L.max()/L.min():.0f} 倍")
    print(f">1000 帧的长尾 episode: {int((L > 1000).sum())} 条")

    # ---------- 问题4：图像统计口径 ----------
    bullet("问题4  图像统计口径与数值特征不一致")
    cam_keys_img = [k for k in fmt if k.startswith("observation.images")]
    for cam in cam_keys_img:
        col = f"stats/{cam}/count"
        if col in eps.columns:
            vals = eps[col].apply(lambda v: int(np.asarray(v).ravel()[0]) if v is not None else -1)
            print(f"  {cam}: 逐段 count min={int(vals.min())} max={int(vals.max())} sum={int(vals.sum())}")
    wrist_key = "observation.images.wrist_image_left"
    g_count = int(np.asarray(stats[wrist_key]["count"]).ravel()[0])
    per_seg_sum = int(eps[f"stats/{wrist_key}/count"].apply(lambda v: int(np.asarray(v).ravel()[0])).sum())
    print(f"  全局 stats.json {wrist_key}.count = {g_count}，逐段相加 = {per_seg_sum} -> 自洽: {g_count == per_seg_sum}")
    print(f"  数值特征(observation.state/action/timestamp).count = {total_frames}(=total_frames)")
    print(f"  即图像归一化统计只覆盖 {g_count}/{total_frames} = {g_count/total_frames:.0%} 的帧，"
          f"而 state/action 覆盖全部帧 -> 图像与非图像统计口径不一致")

    # ---------- 问题5：state / action 尺度 ----------
    bullet("问题5  state 与 action 尺度不一致")
    S = np.stack(frames["state_vec"].values)   # (N,7)
    A = np.stack(frames["action_vec"].values)
    print("state 各维 min :", np.round(S.min(0), 3))
    print("state 各维 max :", np.round(S.max(0), 3))
    print("action 各维 min:", np.round(A.min(0), 3))
    print("action 各维 max:", np.round(A.max(0), 3))
    print(f"action 整体落在约 [{A.min():.2f}, {A.max():.2f}]（已归一化），"
          f"state 各维跨度不一（含 ±3.14 弧度维）-> 尺度不一致")

    # ---------- 问题6：外部相机冗余 ----------
    bullet("问题6  两路外部相机视角冗余")
    cam_mean = {}
    for cam in cam_keys_img:
        key = f"stats/{cam}/mean"
        if key in eps.columns:
            # 各段 3 通道均值 -> (100, 3)
            cam_mean[cam] = np.stack([np.asarray(v, dtype=float).reshape(-1)[:3] for v in eps[key]])
    ext1 = "observation.images.exterior_image_1_left"
    ext2 = "observation.images.exterior_image_2_left"
    wri = "observation.images.wrist_image_left"
    if {ext1, ext2, wri} <= cam_mean.keys():
        def l1(a, b):
            d = np.abs(cam_mean[a] - cam_mean[b]).reshape(len(eps), -1).mean(1)  # 逐段 L1
            return d
        for a, b, tag in [(ext1, ext2, "exterior_1 vs exterior_2"),
                          (ext1, wri, "exterior_1 vs wrist"),
                          (ext2, wri, "exterior_2 vs wrist")]:
            d = l1(a, b)
            print(f"  L1({tag}): mean={d.mean():.3f} median={np.median(d):.3f} min={d.min():.3f} max={d.max():.3f}")
        d_ext, d_w = l1(ext1, ext2), l1(ext1, wri)
        print(f"  外部相机间差异明显小于与腕部差异: {d_ext.mean() < d_w.mean()}")

    # ---------- 问题7：robot_type 缺失 ----------
    bullet("问题7  元数据缺失 robot_type")
    print(f"  info.json robot_type = {info.get('robot_type')!r}")

    # ---------- 问题8：奖励 / 终止稀疏 ----------
    bullet("问题8  奖励/终止信号稀疏")
    r = frames["next.reward"].astype(float)
    d = frames["next.done"].astype(bool)
    print(f"  next.reward: mean={r.mean():.4f}  max={r.max():.4f}  非零帧={int((r != 0).sum())}/{len(r)}")
    print(f"  next.done True 帧数 = {int(d.sum())}（episode 数 = {info['total_episodes']}）")

    # ---------- 清洗示例 ----------
    bullet("清洗示例（基于上述问题）")
    keep_ep = eps[(eps["length"] >= 60) & eps["has_task"]]["episode_index"].tolist()
    print(f"过滤规则: length>=60 且含有效指令 -> 保留 {len(keep_ep)}/{len(eps)} 条 episode")
    clean = frames[frames["episode_index"].isin(keep_ep)].copy()
    print(f"清洗后逐帧样本: {len(clean)}/{len(frames)} 帧 ({len(clean)/len(frames):.0%})")
    # 对 state 做 z-score（action 已近似 [-1,1] 不动）
    S_clean = np.stack(clean["state_vec"].values)
    mu, sd = S_clean.mean(0), S_clean.std(0) + 1e-6
    Sn = (S_clean - mu) / sd
    print(f"state z-score 后 各维均值~0: {np.allclose(Sn.mean(0), 0, atol=1e-6)}，"
          f"标准差~1: {np.allclose(Sn.std(0), 1, atol=1e-6)}")
    print("清洗逻辑跑通。")
    print("=" * 60)


if __name__ == "__main__":
    main()