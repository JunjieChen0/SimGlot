#!/usr/bin/env python3
"""跑通一集完整对话（命令行入口）。批量请用 harness.run_batch。

用法：
  cd simglot
  python3 -m harness.run_episode --task-id 0 \\
      --agent-model qwen3.8-flash --user-model qwen3.8-flash --user-lang en
"""

from __future__ import annotations

import argparse
import json
import time

from harness import env_lang as EL
from harness.episode import EpisodeSpec, run_episode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", type=int, default=0)
    ap.add_argument("--task-split", default="test", choices=["test", "dev", "train"])
    ap.add_argument("--agent-model", default="qwen3.8-flash")
    ap.add_argument("--user-model", default="qwen3.8-flash")
    ap.add_argument("--user-lang", default="en", choices=["en", "zh"])
    ap.add_argument("--env-lang", default="en", choices=list(EL.ENV_LANGS),
                    help="环境侧语言：系统提示 + 工具说明 + 工具错误串（2×2 第二因子）")
    ap.add_argument("--channel", default="token_plan")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    tag = args.tag or time.strftime("single_%Y%m%d_%H%M%S")
    spec = EpisodeSpec(
        task_id=args.task_id, agent_model=args.agent_model, user_model=args.user_model,
        user_lang=args.user_lang, env_lang=args.env_lang,
        task_split=args.task_split, channel=args.channel,
        max_steps=args.max_steps, seed=args.seed, tag=tag,
    )

    print("=" * 70)
    print(f"任务 #{spec.task_id}（{spec.task_split}）｜智能体 = {spec.agent_model}"
          f"｜模拟用户 = {spec.user_model}（{spec.user_lang}）"
          f"｜环境语言 = {spec.env_lang}")
    print("=" * 70)

    s = run_episode(spec)

    print(f"\ninstruction: {s['instruction'][:100]}...")
    at, ut = s["agent_totals"], s["user_totals"]
    print("\n── 结果 " + "─" * 61)
    print(f"  reward       = {s['reward']}   结束原因 = {s['stop_reason']}")
    print(f"  智能体步数   = {s['agent_steps']}｜用户发言 = {s['user_turns']} 轮")
    print(f"  墙钟         = {s['wall_clock_s']}s")
    print(f"  智能体调用   = {at['ok_calls']} 次 in={at['prompt_tokens']} out={at['completion_tokens']} 失败 {at['failed_calls']}")
    print(f"  模拟用户调用 = {ut['ok_calls']} 次 in={ut['prompt_tokens']} out={ut['completion_tokens']} 失败 {ut['failed_calls']}")
    print(f"  合计 token   = {at['total_tokens'] + ut['total_tokens']}")
    if s["error"]:
        print(f"  ⚠️ 错误      = {s['error']}")
    print(f"  产出         = {spec.run_dir().relative_to(spec.run_dir().parents[2])}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
