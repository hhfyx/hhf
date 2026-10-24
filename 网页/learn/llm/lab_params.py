"""lab_params：LLM 采样参数的实测台（四组对照实验，产出 01_params.md 里的表）。

必答问题：temperature=0 是否等于「每次都一样」？
--------------------------------------------------------------------------
实验设计（同一 prompt、同一 model，只改一个参数）：

  E1  temperature 0 / 0.7 / 1.5 各跑 5 次 → 同温下 5 次的输出是否一致、相似度多少
  E2  seed 固定（seed=42 跑 3 次）→ 能否复现；再换 seed=43 看是否变了
  E3  max_tokens 设小 → finish_reason 与输出是否被截断
  E4  stop 序列 → 命中了是否提前停、停了还带不带 stop 串

为什么要用 difflib 算相似度而不是只数「完全一致」：
完全一致是一票否决的粗指标，只要差一个标点就归零，看不出「0.7 每次都不同但都像」
和「1.5 跑到别的主题去了」的区别。相似度能分出这两档，那才是温度真正的效果。

运行（Windows，UTF-8 写结果文件避免控制台编码问题）：
    python -X utf8 lab_params.py
结果落到 params_result.json，笔记里引用的数字都来自它。
"""

from __future__ import annotations

import difflib
import json
import os
import statistics
import time
from pathlib import Path

import httpx

# ---------------------------------------------------------------- 连接配置
# 用环境变量优先：这样以后换成真·云端，脚本一行不用改。
API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8326/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "deepseek-account/deepseek-flash")

ENDPOINT = f"{BASE_URL}/chat/completions"

# ⚠️ 本机上这个网关默认开「推理模式」，max_tokens 会被思维链吃光、content 返回 null。
# 这是接入层的坑，不是参数实验想测的东西，所以统一关掉推理只测采样参数。
# 千人千面的网关，这一行是最容易踩的一个。
EXTRA = {"reasoning_effort": "none"}

PROMPT = "用三句话介绍杭州，每句不超过 30 字。"
MAX_TOKENS = 200

RUNS = 5
TEMPERATURES = (0.0, 0.7, 1.5)


def chat_one(
    *,
    temperature: float | None = None,
    seed: int | None = None,
    max_tokens: int = MAX_TOKENS,
    stop: list[str] | None = None,
) -> dict:
    """打一次 chat/completions，返回统一结构的观测结果。

    只返回实验要用的字段：content、finish_reason、usage、latency。
    """
    body: dict = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        **EXTRA,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if seed is not None:
        body["seed"] = seed
    if stop is not None:
        body["stop"] = stop

    started = time.perf_counter()
    resp = httpx.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=body,
        timeout=120,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    if resp.status_code != 200:
        return {
            "ok": False,
            "status": resp.status_code,
            "error": resp.text[:400],
            "latency_ms": latency_ms,
        }

    data = resp.json()
    choice = data["choices"][0]
    return {
        "ok": True,
        "status": 200,
        "content": choice["message"].get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage", {}),
        "latency_ms": latency_ms,
    }


def similarity(a: str, b: str) -> float:
    """字符级相似度 0–1。中文按字切，difflib 直接可用。"""
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 4)


def experiment_temperature() -> dict:
    """E1：同 prompt，三个温度各 5 次。"""
    print("\n== E1 temperature 稳定性 ==")
    out: dict = {}
    for temp in TEMPERATURES:
        runs = [chat_one(temperature=temp) for _ in range(RUNS)]
        ok = [r for r in runs if r["ok"]]
        texts = [r["content"] for r in ok]
        distinct = len(set(texts))
        # 每轮都和第一轮比，再取平均：衡量「漂移幅度」而不是两两全比
        sims = [similarity(texts[0], t) for t in texts[1:]] if len(texts) > 1 else []
        out[f"{temp}"] = {
            "runs": len(ok),
            "distinct_texts": distinct,
            "identical": distinct == 1,
            "mean_similarity_to_first": round(statistics.mean(sims), 4)
            if sims
            else None,
            "min_similarity_to_first": round(min(sims), 4) if sims else None,
            "texts": texts,
            "finish_reasons": [r["finish_reason"] for r in ok],
            "completion_tokens": [r["usage"].get("completion_tokens") for r in ok],
            "mean_latency_ms": round(statistics.mean(r["latency_ms"] for r in ok)),
            "errors": [r for r in runs if not r["ok"]],
        }
        row = out[f"{temp}"]
        print(
            f"  temp={temp:<4} distinct={row['distinct_texts']}/{row['runs']}"
            f"  sim(first)={row['mean_similarity_to_first']}"
            f"  lat={row['mean_latency_ms']}ms"
        )
    return out


def experiment_seed() -> dict:
    """E2：seed 能否复现。**要三组对照才说明问题。**

    A) temp=0 + 同 seed 跑 5 次 —— 这是"最该复现"的配置，必答题的实证依据
    B) 同 temp 换 seed（42 vs 7）—— 若结果完全一样，说明 seed 根本没被上游采用
    C) 不传 seed 跑 2 次 —— 基准组

    只做 A 会得出错误的因果：看到不重复就归咎于 seed 无效；
    只做 B 也不够：temp=0.7 下换 seed 本来就该变，无法区分"seed 生效"和"随机漂移"。
    B 必须配 temp=0 才有判别力。
    """
    print("\n== E2 seed 复现（temp=0）==")

    # A) 最该复现的配置
    a_runs = [chat_one(temperature=0.0, seed=42) for _ in range(5)]
    a_texts = [r["content"] for r in a_runs if r["ok"]]

    # B) 换 seed：temp=0 下若仍完全相同，说明 seed 被静默忽略
    b42 = chat_one(temperature=0.0, seed=42)
    b7 = chat_one(temperature=0.0, seed=7)
    b42_text, b7_text = b42.get("content", ""), b7.get("content", "")

    # C) 基准组：不传 seed
    c_runs = [chat_one(temperature=0.0) for _ in range(2)]
    c_texts = [r["content"] for r in c_runs if r["ok"]]

    result = {
        "temp0_seed42_runs": len(a_texts),
        "temp0_seed42_distinct": len(set(a_texts)),
        "temp0_seed42_identical": len(set(a_texts)) == 1,
        "temp0_seed42_mean_similarity_to_first": round(
            statistics.mean(similarity(a_texts[0], t) for t in a_texts[1:]), 4
        )
        if len(a_texts) > 1
        else None,
        "temp0_seed42_texts": a_texts,
        "temp0_seed42_vs_seed7_identical": b42_text == b7_text,
        "temp0_seed42_vs_seed7_similarity": similarity(b42_text, b7_text)
        if b42_text and b7_text
        else None,
        "temp0_no_seed_distinct": len(set(c_texts)),
        "temp0_no_seed_texts": c_texts,
    }
    print(
        f"  A) temp=0 seed=42 x5 -> distinct={result['temp0_seed42_distinct']}/5"
        f"  sim(first)={result['temp0_seed42_mean_similarity_to_first']}"
    )
    print(
        f"  B) temp=0 seed=42 vs seed=7 -> identical={result['temp0_seed42_vs_seed7_identical']}"
        f"  sim={result['temp0_seed42_vs_seed7_similarity']}"
    )
    print(f"  C) temp=0 不传 seed x2 -> distinct={result['temp0_no_seed_distinct']}")
    return result


def experiment_max_tokens() -> dict:
    """E3：max_tokens 设小，看截断长相（finish_reason 就是判据）。"""
    print("\n== E3 max_tokens 截断 ==")
    out: dict = {}
    for mt in (20, 60, MAX_TOKENS):
        r = chat_one(temperature=0.0, max_tokens=mt)
        row = {
            "ok": r["ok"],
            "finish_reason": r.get("finish_reason"),
            "completion_tokens": (r.get("usage") or {}).get("completion_tokens"),
            "content_len": len(r.get("content") or ""),
            "content": (r.get("content") or "")[:120],
            "error": r.get("error"),
        }
        out[str(mt)] = row
        print(
            f"  max_tokens={mt:<4} finish={row['finish_reason']!s:<8}"
            f" compl={row['completion_tokens']} len={row['content_len']}"
        )
    return out


def experiment_stop() -> dict:
    """E4：stop 序列。命中即停，且**返回文本里不含 stop 串**。"""
    print("\n== E4 stop 序列 ==")
    plain = chat_one(temperature=0.0, max_tokens=MAX_TOKENS)
    stopped = chat_one(temperature=0.0, max_tokens=MAX_TOKENS, stop=["。"])
    out = {
        "plain": {
            "finish_reason": plain.get("finish_reason"),
            "completion_tokens": (plain.get("usage") or {}).get("completion_tokens"),
            "content": (plain.get("content") or "")[:160],
            "period_count": (plain.get("content") or "").count("。"),
        },
        "stop_after_full_stop": {
            "finish_reason": stopped.get("finish_reason"),
            "completion_tokens": (stopped.get("usage") or {}).get("completion_tokens"),
            "content": (stopped.get("content") or "")[:160],
            "period_count": (stopped.get("content") or "").count("。"),
            "content_len": len(stopped.get("content") or ""),
        },
    }
    print(
        f"  无限停 -> finish={out['plain']['finish_reason']} 句号数={out['plain']['period_count']}"
    )
    print(
        f"  stop=['。'] -> finish={out['stop_after_full_stop']['finish_reason']}"
        f" 句号数={out['stop_after_full_stop']['period_count']}"
        f" 长度={out['stop_after_full_stop']['content_len']}"
    )
    return out


def main() -> None:
    if not API_KEY:
        raise SystemExit(
            "缺 LLM_API_KEY。先设环境变量或把 .env 里的值导出，例如：\n"
            '  $env:LLM_API_KEY="..."'
        )

    print(f"endpoint={ENDPOINT}\nmodel={MODEL}\nprompt={PROMPT!r}\nruns/temp={RUNS}")

    result = {
        "meta": {
            "endpoint": ENDPOINT,
            "model": MODEL,
            "prompt": PROMPT,
            "runs_for_temperature": RUNS,
            "max_tokens": MAX_TOKENS,
            "extra": EXTRA,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        "E1_temperature": experiment_temperature(),
        "E2_seed": experiment_seed(),
        "E3_max_tokens": experiment_max_tokens(),
        "E4_stop": experiment_stop(),
    }

    out_path = Path(__file__).with_name("params_result.json")
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[done] 结果写入 {out_path.name}")


if __name__ == "__main__":
    main()
