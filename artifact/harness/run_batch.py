#!/usr/bin/env python3
"""批量驱动：一个实验格网格并发跑完，汇总成 batch_summary.json。

这是 E2 主矩阵的主力工具——支持并发、逐集落盘、失败不中断、可续跑
（已存在 summary.json 的格默认跳过，用 --no-resume 覆盖）。

用法：
  cd simglot
  python3 -m harness.run_batch --task-ids 0 1 2 3 4 --concurrency 4 --tag pilot_en_5
  python3 -m harness.run_batch --task-range 0-24 --agent-models qwen3.8-flash qwen3.7-plus \\
      --user-models qwen3.8-flash --user-langs en zh --seeds 0 1 2 --concurrency 8
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics as st
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness import env_lang as EL  # noqa: E402
from harness.episode import EpisodeSpec, run_episode  # noqa: E402


def parse_task_ids(args) -> list[int]:
    if args.task_ids:
        return list(args.task_ids)
    a, b = args.task_range.split("-")
    return list(range(int(a), int(b) + 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-ids", type=int, nargs="+")
    ap.add_argument("--task-range", type=str, default="0-4", help="形如 0-24")
    ap.add_argument("--task-split", default="test", choices=["test", "dev", "train"])
    ap.add_argument("--agent-models", nargs="+", default=["qwen3.8-flash"])
    ap.add_argument("--user-models", nargs="+", default=["qwen3.8-flash"])
    ap.add_argument("--user-langs", nargs="+", default=["en"], choices=["en", "zh"])
    ap.add_argument("--env-langs", nargs="+", default=["en"],
                    choices=list(EL.ENV_LANGS),
                    help="环境侧语言（2×2 第二因子）：系统提示 + 工具说明 + 工具错误串")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--channel", default="token_plan")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--agent-thinking", choices=["default", "on", "off"], default="default",
                    help="对照实验用：强制智能体侧思考模式；正式矩阵保持 default")
    ap.add_argument("--agent-channel", default=None,
                    help="智能体单独走另一条通道（如 dmxapi）；默认与 --channel 相同")
    ap.add_argument("--no-resume", action="store_true", help="已有结果的格也重跑")
    args = ap.parse_args()

    tag = args.tag or time.strftime("batch_%Y%m%d_%H%M%S")
    out_root = ROOT / "runs" / tag
    out_root.mkdir(parents=True, exist_ok=True)

    specs = [
        EpisodeSpec(
            task_id=t, agent_model=am, user_model=um, user_lang=lang, env_lang=elang,
            task_split=args.task_split, channel=args.channel,
            max_steps=args.max_steps, seed=s, tag=tag, out_root=out_root,
            agent_thinking=(None if args.agent_thinking == "default"
                            else args.agent_thinking == "on"),
            agent_channel=args.agent_channel,
        )
        for t, am, um, lang, elang, s in itertools.product(
            parse_task_ids(args), args.agent_models, args.user_models,
            args.user_langs, args.env_langs, args.seeds,
        )
    ]

    todo = specs if args.no_resume else [
        sp for sp in specs if not (sp.run_dir() / "summary.json").exists()
    ]
    skipped = len(specs) - len(todo)

    print("=" * 78)
    print(f"批次 {tag}｜格数 {len(specs)}（跳过已完成 {skipped}）｜并发 {args.concurrency}")
    print(f"任务 {min(parse_task_ids(args))}–{max(parse_task_ids(args))}"
          f"｜语言(用户) {args.user_langs}｜语言(环境) {args.env_langs}｜种子 {args.seeds}")
    print("=" * 78)

    t0 = time.time()
    results, failures = [], []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_episode, sp): sp for sp in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            sp = futures[fut]
            try:
                s = fut.result()
            except Exception as e:  # noqa: BLE001
                failures.append({"cell_id": sp.cell_id(), "error": f"{type(e).__name__}: {e}"})
                print(f"  [{i:>3}/{len(todo)}] {sp.cell_id():<58} ✗ {type(e).__name__}")
                continue
            results.append(s)
            tok = s["agent_totals"]["total_tokens"] + s["user_totals"]["total_tokens"]
            flag = "✓" if s["reward"] == 1.0 else "·"
            print(f"  [{i:>3}/{len(todo)}] {s['cell_id']:<58} {flag} reward={s['reward']:.0f} "
                  f"{s['wall_clock_s']:>5.1f}s tok={tok:>7}")

    elapsed = time.time() - t0
    # 汇总时把已完成格也纳入（续跑场景）
    for sp in specs:
        p = sp.run_dir() / "summary.json"
        if p.exists() and not any(r["cell_id"] == sp.cell_id() for r in results):
            results.append(json.loads(p.read_text(encoding="utf-8")))

    def agg(key: str, sub: str = "total_tokens") -> float:
        vals = [r[key][sub] for r in results if r.get(key)]
        return sum(vals) / len(vals) if vals else 0.0

    summary = {
        "tag": tag,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "grid": {
            "n_cells": len(specs), "ran": len(todo), "skipped": skipped,
            "failed": len(failures),
            "task_ids": parse_task_ids(args), "agent_models": args.agent_models,
            "user_models": args.user_models, "user_langs": args.user_langs,
            "env_langs": args.env_langs, "seeds": args.seeds,
            "concurrency": args.concurrency,
        },
        "wall_clock_s": round(elapsed, 1),
        "reward_mean": (sum(r["reward"] for r in results) / len(results)) if results else 0.0,
        "reward_pass": sum(1 for r in results if r["reward"] == 1.0),
        "tokens_per_episode_mean": agg("agent_totals") + agg("user_totals"),
        "agent_tokens_mean": agg("agent_totals"),
        "user_tokens_mean": agg("user_totals"),
        "agent_calls_mean": agg("agent_totals", "ok_calls"),
        "user_calls_mean": agg("user_totals", "ok_calls"),
        "wall_per_episode_mean": (sum(r["wall_clock_s"] for r in results) / len(results)) if results else 0.0,
        "failures": failures,
        "episodes": [
            {k: r[k] for k in ("cell_id", "reward", "wall_clock_s", "agent_steps",
                               "user_turns", "agent_totals", "user_totals", "error")}
            for r in sorted(results, key=lambda x: x["cell_id"])
        ],
    }
    (out_root / "batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print("── 批次汇总 " + "─" * 64)
    print(f"  完成 {len(results)}/{len(specs)} 格（失败 {len(failures)}）｜墙钟 {elapsed:.1f}s")
    print(f"  成功率            = {summary['reward_pass']}/{len(results)}")
    print(f"  每集 token 均值   = {summary['tokens_per_episode_mean']:.0f}"
          f"  （智能体 {summary['agent_tokens_mean']:.0f} + 用户 {summary['user_tokens_mean']:.0f}）")
    print(f"  每集调用数均值    = 智能体 {summary['agent_calls_mean']:.1f} + 用户 {summary['user_calls_mean']:.1f}")
    print(f"  每集墙钟均值      = {summary['wall_per_episode_mean']:.1f}s（并发 {args.concurrency}）")
    print(f"  汇总              = runs/{tag}/batch_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
