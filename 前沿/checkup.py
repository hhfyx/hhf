import argparse
import json
from pathlib import Path
from typing import Dict, Any

import requests

MIRROR_BASE = "https://hf-mirror.com/api/datasets"
RAW_BASE = "https://hf-mirror.com/datasets"
TIMEOUT = 10
DOWNLOAD_CHUNK = 1024 * 1024          # 1MB 分块写入
DOWNLOAD_TIMEOUT = (10, 120)          # (连接, 读取) 超时，大文件给足读取时间
PAGE_SIZE_LIMIT = 1000                # tree api 单页上限，超过需用 Link 头翻页


def hf_list_files(repo: str, path: str, recursive: bool = False) -> list:
    """调用hf-mirror api列出仓库指定路径下文件；v3为嵌套分片，需recursive才能看到子目录里的文件"""
    url = f"{MIRROR_BASE}/{repo}/tree/main/{path}"
    if recursive:
        url += "?recursive=true"
    headers = {"Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def hf_get_json(repo: str, path: str) -> dict:
    """读取仓库内原始json文件（如 meta/info.json）"""
    url = f"{RAW_BASE}/{repo}/resolve/main/{path}"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return {}
        return resp.json()
    except Exception:
        return {}


def _next_link(link_header: str):
    """从响应 Link 头里解析 rel="next" 的分页地址"""
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part and "<" in part and ">" in part:
            return part[part.find("<") + 1: part.find(">")]
    return None


def hf_list_all_files(repo: str) -> list:
    """递归列出仓库全部文件，自动翻页；返回 [{path,size}, ...]"""
    files = []
    url = f"{MIRROR_BASE}/{repo}/tree/main/?recursive=true"
    headers = {"Accept": "application/json"}
    seen = set()
    while url and url not in seen:
        seen.add(url)
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        except Exception:
            break
        if resp.status_code != 200:
            break
        for item in resp.json():
            if item.get("type") == "file":
                files.append({"path": item["path"], "size": item.get("size", 0)})
        url = _next_link(resp.headers.get("Link"))
    return files


def hf_download_file(repo: str, path: str, dest: Path, force: bool = False) -> int:
    """下载单个文件到 dest；已存在且非空则跳过；用 .part 临时文件保证原子性"""
    url = f"{RAW_BASE}/{repo}/resolve/main/{path}"
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK):
                f.write(chunk)
    tmp.replace(dest)
    return dest.stat().st_size


def download_dataset(repo_id: str, out_dir: str = None, force: bool = False):
    """下载数据集全部分片（data/*.parquet、meta/、videos/ 等），禁止只取部分分片"""
    print(f"===== 开始下载数据集：{repo_id} =====")
    files = hf_list_all_files(repo_id)
    if not files:
        print("未列出任何文件：数据集名可能有误，或仓库不受镜像支持")
        return

    name = repo_id.split("/")[-1]
    base = (Path(out_dir) if out_dir else Path.cwd()) / name
    total_bytes = sum(f["size"] for f in files)
    print(f"共 {len(files)} 个文件，合计约 {total_bytes / 1024 / 1024:.1f} MB")
    print(f"下载目录：{base}")
    if total_bytes > 100 * 1024 * 1024:
        print("⚠️ 下载量超过 100MB，需要等待较长时间")

    done_bytes = 0
    failed = []
    for i, f in enumerate(files, 1):
        p = f["path"]
        dest = base / p
        try:
            size = hf_download_file(repo_id, p, dest, force=force)
            done_bytes += size
            print(f"[{i}/{len(files)}] {p}  ({size / 1024 / 1024:.2f} MB)")
        except Exception as e:
            failed.append(p)
            print(f"[{i}/{len(files)}] 失败 {p}: {e}")

    print("=" * 50)
    print(f"下载完成：{len(files) - len(failed)}/{len(files)} 个文件，累计 {done_bytes / 1024 / 1024:.1f} MB")
    if failed:
        print(f"⚠️ 有 {len(failed)} 个文件失败，重跑本命令会自动跳过已下好的文件：")
        for p in failed:
            print(" -", p)


def check_dataset(repo_id: str):
    """repo_id 格式 lerobot/xxx_dataset"""
    print(f"===== 开始校验数据集：{repo_id} =====")
    result = {
        "v3_layout": False,
        "has_meta_episodes": False,
        "has_stats_json": False,
        "has_parquet": False,
        "parquet_count": 0,
        "episode_count": 0,
        "has_video": False,
        "warnings": [],
        "verdict": "不可用"
    }

    # 1. 检查 meta/episodes 目录（v3布局标志；v3为chunk嵌套，需递归）
    meta_ep_list = hf_list_files(repo_id, "meta/episodes", recursive=True)
    if isinstance(meta_ep_list, list) and len(meta_ep_list) > 0:
        result["has_meta_episodes"] = True
        result["v3_layout"] = True
        # 统计episode数量：v3 episode元数据为 parquet 分片
        ep_files = [item["path"] for item in meta_ep_list if item["type"] == "file"]
        result["episode_count"] = len([f for f in ep_files if f.endswith(".parquet")])

    # 2. 检查 meta/stats.json
    stats_list = hf_list_files(repo_id, "meta")
    stats_exists = any(
        item["path"] == "meta/stats.json" and item["type"] == "file"
        for item in stats_list
    )
    result["has_stats_json"] = stats_exists

    # 3. 检查 data/ 下 parquet 文件（v3嵌套分片，需递归）
    data_list = hf_list_files(repo_id, "data", recursive=True)
    parquet_files = [
        item["path"] for item in data_list
        if item["type"] == "file" and item["path"].endswith(".parquet")
    ]
    result["parquet_count"] = len(parquet_files)
    if result["parquet_count"] > 0:
        result["has_parquet"] = True

    # 4. episode 总数以 meta/info.json 的 total_episodes 为权威值
    info = hf_get_json(repo_id, "meta/info.json")
    if isinstance(info.get("total_episodes"), int):
        result["episode_count"] = info["total_episodes"]

    # 5. 检查视频文件：v3视频存放在 videos/ 下，需递归
    video_list = hf_list_files(repo_id, "videos", recursive=True)
    video_exist = any(
        item["type"] == "file" and (item["path"].endswith(".mp4") or item["path"].endswith(".webm"))
        for item in video_list
    )
    result["has_video"] = video_exist

    # 判定规则：3条硬门槛
    hard_rules = [result["v3_layout"], result["has_stats_json"], result["has_parquet"]]
    if all(hard_rules):
        # 全部硬条件通过
        if result["parquet_count"] == 1 and result["episode_count"] <= 500:
            result["verdict"] = "可直接用"
        else:
            result["verdict"] = "可用，但要注意"
            if result["parquet_count"] > 1:
                result["warnings"].append(f"存在多个parquet分片：{result['parquet_count']}个，下载需要拉取全部分片")
            if result["episode_count"] > 500:
                result["warnings"].append(f"episode数量较多：{result['episode_count']}，数据集偏大")
    else:
        result["verdict"] = "不可用"
        if not result["v3_layout"]:
            result["warnings"].append("不是v3布局，缺少meta/episodes目录")
        if not result["has_stats_json"]:
            result["warnings"].append("缺少 meta/stats.json")
        if not result["has_parquet"]:
            result["warnings"].append("data目录下无parquet数据文件")

    # 输出报告
    print(f"v3布局: {result['v3_layout']}")
    print(f"meta/stats.json: {result['has_stats_json']}")
    print(f"data目录parquet文件数: {result['parquet_count']}")
    print(f"episode总数: {result['episode_count']}")
    print(f"附带视频: {result['has_video']}")
    print("\n【判定结果】", result["verdict"])
    if result["warnings"]:
        print("⚠️ 警告信息：")
        for w in result["warnings"]:
            print(" -", w)
    print("=" * 50)
    return result


def main():
    parser = argparse.ArgumentParser(description="Lerobot数据集v3预检查与下载工具")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    # check 子命令
    check_cmd = subparsers.add_parser("check", help="仅校验数据集结构，不下载数据")
    check_cmd.add_argument("dataset", help="数据集名，格式 lerobot/xxx")
    # download 子命令
    dl_cmd = subparsers.add_parser("download", help="下载数据集全部分片（含所有parquet分片）")
    dl_cmd.add_argument("dataset", help="数据集名，格式 lerobot/xxx")
    dl_cmd.add_argument("-o", "--out", default=None, help="下载根目录，默认当前目录")
    dl_cmd.add_argument("-f", "--force", action="store_true", help="强制重下已存在的文件")
    args = parser.parse_args()

    if args.cmd == "check":
        check_dataset(args.dataset)
    elif args.cmd == "download":
        download_dataset(args.dataset, out_dir=args.out, force=args.force)


if __name__ == "__main__":
    main()
