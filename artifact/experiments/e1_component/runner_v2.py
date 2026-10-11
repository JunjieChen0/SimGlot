#!/usr/bin/env python3
"""SimGlot **v2** 实验运行器（E1 / E2 用）。

**为什么是派生而不是改 v1.0**：`simglot/` 已冻结（`RELEASE_FREEZE_v1.0.md`），E1/E2 需要两样
v1.0 没有的东西——① **任务域可选**（E2 要 τ-bench **airline**）；② **组件级环境语言**
（E1 的三个单组件臂，见 `env_lang_v2.py`）。故在 `sqj/swe/` 内派生一份运行器，
**只读复用** v1.0 的 `harness.agent / client / user_sim / scoring`，绝不写入 `simglot/`。

与 `harness/episode.py` 的差异**只有四处**，其余逐字相同（便于对照审阅）：
  1. `domain` 字段：`retail` → `MockRetailDomainEnv`，`airline` → `MockAirlineDomainEnv`；
  2. 环境语言走 `env_lang_v2`（组件级）；
  3. 中文任务套件按域选择（retail 复用 v1.0 的 `data/tasks_zh.json`；airline 在 `sqj/data/`）；
  4. `seed` 改名 **`rep`**（重复编号）——v1.0 已查明它只是重复序号而非受控随机种子，
     见 [[simglot-scorer-and-seed-facts]]；改名是为了让调用方不再误读。

用法（批量）：
    cd sqj && python3 swe/runner_v2.py --domain airline --task-range 0-49 \
        --agent-models qwen3.8-flash deepseek-v4.1-flash --user-models qwen3.8-flash \
        --user-langs en zh --env-langs en --reps 0 1 --concurrency 6 --tag ez_airline_pilot
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent          # sqj/swe
SQJ = HERE.parent
SIMGLOT = SQJ.parent / "simglot"
for _p in (str(SQJ), str(HERE), str(SIMGLOT), str(SIMGLOT / "vendor" / "tau-bench")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _bootstrap  # noqa: E402,F401  离线引导：必须在 tau_bench / harness 之前

from tau_bench.envs.retail.env import MockRetailDomainEnv   # noqa: E402
from tau_bench.envs.airline.env import MockAirlineDomainEnv  # noqa: E402

from harness.agent import ToolCallingAgent      # noqa: E402
from harness.client import BailianClient, now_utc  # noqa: E402
from harness.scoring import load_aliases, score  # noqa: E402
from harness.user_sim import OurUserSim          # noqa: E402
import env_lang_v2 as EL2                        # noqa: E402

# `harness/agent.py` 在 `solve()` 里调 `EL.observation(...)`，而它绑的是 **v1.0** 的
# `harness.env_lang`——那个模块只认 en / zh / zhp，遇到 E1 的三个单组件档位会直接抛
# `ValueError`（实测踩过：格子 3.4 秒就 error 结束、只花了 5k token）。故在本**进程内**
# 把该模块级引用改指 EL2。这是唯一一处对 v1.0 模块的运行时改写：**不改磁盘上的任何文件**，
# 且 runner_v2 是 v2 实验的唯一入口。
import harness.agent as _HA                      # noqa: E402
_HA.EL = EL2
assert _HA.EL is EL2, "v2 运行器必须把 harness.agent 的观察翻译指向 EL2"

ENV_CLASSES = {"retail": MockRetailDomainEnv, "airline": MockAirlineDomainEnv}
_ALIASES = None
_ZH_SUITES: Dict[str, Dict[int, str]] = {}


def _aliases():
    """输出同义表是 **retail 专属**的（airline 无 outputs 别名），airline 上返回空表。"""
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = load_aliases()
    return _ALIASES


def _zh_suite(domain: str) -> Dict[int, str]:
    """中文任务套件：{task_id: 中文指令}。缺失即报错——绝不静默回退到英文。"""
    if domain in _ZH_SUITES:
        return _ZH_SUITES[domain]
    path = (SIMGLOT / "data" / "tasks_zh.json" if domain == "retail"
            else SQJ / "data" / f"tasks_zh_{domain}.json")
    if not path.exists():
        raise FileNotFoundError(
            f"域 {domain} 的中文条件需要 {path}，但它不存在。"
            f"（airline 需先跑 scripts/build_zh_suite_airline.py 生成并通过保真校验。）")
    payload = json.loads(path.read_text(encoding="utf-8"))
    suite = {int(r["task_id"]): r["zh"] for r in payload["tasks"]}
    _ZH_SUITES[domain] = suite
    return suite


@dataclass
class EpisodeSpecV2:
    task_id: int
    domain: str = "retail"
    agent_model: str = "qwen3.8-flash"
    user_model: str = "qwen3.8-flash"
    user_lang: str = "en"
    env_lang: str = "en"
    task_split: str = "test"
    channel: str = "token_plan"
    max_steps: int = 30
    rep: int = 0                       # 重复编号（不是受控随机种子）
    tag: str = "adhoc"
    out_root: Optional[Path] = None
    agent_channel: Optional[str] = None

    def cell_id(self) -> str:
        d = "" if self.domain == "retail" else f"d{self.domain}_"
        e = "" if self.env_lang == "en" else f"_e{self.env_lang}"
        return (f"{d}t{self.task_id}_{self.agent_model}_u-{self.user_model}"
                f"_{self.user_lang}_s{self.rep}{e}")

    def run_dir(self) -> Path:
        root = Path(self.out_root) if self.out_root else (SQJ / "runs" / self.tag)
        return root / self.cell_id()


def run_episode(spec: EpisodeSpecV2) -> Dict[str, Any]:
    run_dir = spec.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    calls_log = run_dir / "calls.jsonl"
    started = time.time()

    agent_client = BailianClient(channel=spec.agent_channel or spec.channel,
                                 role="agent", log_path=calls_log)
    user_client = BailianClient(channel=spec.channel, role="user", log_path=calls_log)

    env = ENV_CLASSES[spec.domain](user_strategy="human", task_split=spec.task_split,
                                   task_index=spec.task_id)

    instruction_lang = "en"
    if spec.user_lang == "zh":
        zh = _zh_suite(spec.domain).get(spec.task_id)
        if zh is None:
            raise KeyError(f"域 {spec.domain} 的任务 #{spec.task_id} 不在中文套件内。")
        env.tasks = list(env.tasks)
        env.tasks[spec.task_id] = env.tasks[spec.task_id].model_copy(update={"instruction": zh})
        instruction_lang = "zh"

    task = env.tasks[spec.task_id]
    env.user = OurUserSim(user_client, spec.user_model, lang=spec.user_lang)

    agent_system_prompt = EL2.wiki(spec.env_lang)
    agent_tools_info = EL2.tools_info(env.tools_info, spec.env_lang)

    agent = ToolCallingAgent(
        client=agent_client, model=spec.agent_model, tools_info=agent_tools_info,
        system_prompt=agent_system_prompt, temperature=0.0,
        max_num_steps=spec.max_steps, obs_lang=spec.env_lang,
    )

    error = ""
    result: Dict[str, Any] = {"reward": 0.0, "messages": [], "trace": [],
                              "stop_reason": "error", "steps": 0}
    score_detail: Dict[str, Any] = {}
    try:
        result = agent.solve(env, task_index=spec.task_id)
        score_detail = score(env, aliases=_aliases(), task_id=spec.task_id)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"

    at, ut = agent_client.totals(), user_client.totals()
    summary = {
        "spec": {**asdict(spec), "out_root": str(spec.out_root) if spec.out_root else None},
        "runner": "sqj/swe/runner_v2.py",
        "cell_id": spec.cell_id(),
        "started_utc": now_utc(),
        "wall_clock_s": round(time.time() - started, 2),
        "domain": spec.domain,
        "instruction": task.instruction,
        "instruction_lang": instruction_lang,
        "instruction_source": (f"sqj/data/tasks_zh_{spec.domain}.json（v2 重建）"
                               if instruction_lang == "zh" else "tau-bench 原指令"),
        "env_lang": spec.env_lang,
        "env_lang_design": EL2.design(spec.env_lang),
        "env_impl_sha": EL2.fingerprint(spec.env_lang),
        "reward": score_detail.get("reward", result["reward"]),
        "stop_reason": result["stop_reason"],
        "agent_steps": result["steps"],
        "user_turns": len(env.user.turns),
        "score": score_detail,
        "reward_detail": {
            "r_actions": score_detail.get("r_actions"),
            "r_outputs": score_detail.get("r_outputs"),
            "failure_mode": score_detail.get("failure_mode"),
        },
        "agent_totals": at,
        "user_totals": ut,
        "error": error,
    }

    (run_dir / "transcript.json").write_text(json.dumps({
        "agent_messages": result["messages"],
        "user_messages": env.user.messages,
        "agent_trace": result["trace"],
        "user_turns": env.user.turns,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_task_ids(args) -> list[int]:
    if args.task_ids:
        return list(args.task_ids)
    a, b = args.task_range.split("-")
    return list(range(int(a), int(b) + 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="retail", choices=list(ENV_CLASSES))
    ap.add_argument("--task-ids", type=int, nargs="+")
    ap.add_argument("--task-range", type=str, default="0-4")
    ap.add_argument("--agent-models", nargs="+", default=["qwen3.8-flash"])
    ap.add_argument("--user-models", nargs="+", default=["qwen3.8-flash"])
    ap.add_argument("--user-langs", nargs="+", default=["en"], choices=["en", "zh"])
    ap.add_argument("--env-langs", nargs="+", default=["en"], choices=list(EL2.ENV_LANGS))
    ap.add_argument("--reps", type=int, nargs="+", default=[0])
    ap.add_argument("--channel", default="token_plan")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    tag = args.tag or time.strftime("v2_%Y%m%d_%H%M%S")
    out_root = SQJ / "runs" / tag
    out_root.mkdir(parents=True, exist_ok=True)

    specs = [EpisodeSpecV2(task_id=t, domain=args.domain, agent_model=am, user_model=um,
                           user_lang=lang, env_lang=el, task_split="test",
                           channel=args.channel, max_steps=args.max_steps, rep=r,
                           tag=tag, out_root=out_root)
             for t, am, um, lang, el, r in itertools.product(
                 parse_task_ids(args), args.agent_models, args.user_models,
                 args.user_langs, args.env_langs, args.reps)]

    todo = specs if args.no_resume else [
        sp for sp in specs if not (sp.run_dir() / "summary.json").exists()]
    skipped = len(specs) - len(todo)

    print("=" * 84)
    print(f"批次 {tag}｜域 {args.domain}｜格数 {len(specs)}（跳过已完成 {skipped}）｜并发 {args.concurrency}")
    print(f"任务 {min(parse_task_ids(args))}–{max(parse_task_ids(args))}｜用户语言 {args.user_langs}"
          f"｜环境语言 {args.env_langs}｜重复 {args.reps}")
    print("=" * 84)

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
                print(f"  [{i:>3}/{len(todo)}] {sp.cell_id():<56} ✗ {type(e).__name__}", flush=True)
                continue
            results.append(s)
            tok = s["agent_totals"]["total_tokens"] + s["user_totals"]["total_tokens"]
            print(f"  [{i:>3}/{len(todo)}] {s['cell_id']:<56} reward={s['reward']:.0f} "
                  f"{s['wall_clock_s']:>5.1f}s tok={tok:>7}", flush=True)

    elapsed = time.time() - t0
    for sp in specs:
        p = sp.run_dir() / "summary.json"
        if p.exists() and not any(r["cell_id"] == sp.cell_id() for r in results):
            results.append(json.loads(p.read_text(encoding="utf-8")))

    def agg(key: str, sub: str = "total_tokens") -> float:
        vals = [r[key][sub] for r in results if r.get(key)]
        return sum(vals) / len(vals) if vals else 0.0

    summary = {
        "tag": tag, "runner": "sqj/swe/runner_v2.py", "domain": args.domain,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "grid": {"n_cells": len(specs), "ran": len(todo), "skipped": skipped,
                 "failed": len(failures), "task_ids": parse_task_ids(args),
                 "agent_models": args.agent_models, "user_models": args.user_models,
                 "user_langs": args.user_langs, "env_langs": args.env_langs,
                 "reps": args.reps, "concurrency": args.concurrency},
        "wall_clock_s": round(elapsed, 1),
        "reward_mean": (sum(r["reward"] for r in results) / len(results)) if results else 0.0,
        "reward_pass": sum(1 for r in results if r["reward"] == 1.0),
        "tokens_per_episode_mean": agg("agent_totals") + agg("user_totals"),
        "agent_tokens_mean": agg("agent_totals"),
        "user_tokens_mean": agg("user_totals"),
        "tokens_total": sum(r["agent_totals"]["total_tokens"] + r["user_totals"]["total_tokens"]
                            for r in results),
        "failures": failures,
        "episodes": [{k: r[k] for k in ("cell_id", "reward", "wall_clock_s", "agent_steps",
                                        "user_turns", "agent_totals", "user_totals", "error")}
                     for r in sorted(results, key=lambda x: x["cell_id"])],
    }
    (out_root / "batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("── 批次汇总 " + "─" * 60)
    print(f"  完成 {len(results)}/{len(specs)} 格（失败 {len(failures)}）｜墙钟 {elapsed:.1f}s")
    print(f"  成功率 = {summary['reward_pass']}/{len(results)}"
          f"｜每集 token 均值 = {summary['tokens_per_episode_mean']:.0f}"
          f"｜本批合计 = {summary['tokens_total']:,}")
    print(f"  汇总 = {out_root/'batch_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
