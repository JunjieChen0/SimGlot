#!/usr/bin/env python3
"""补齐 `env=zh` 臂的**修正后**分数，使 E1 的五个臂完全同口径。

## 为什么需要

E1 的三个单组件臂（`zh_p`/`zh_t`/`zh_e`）是**今天用已修补的评分器**跑的，`summary.json`
里的 `reward` 直接可用。而 `env=zh` 臂来自 v1.0 的 `ez2_envzh` 批次，**跑在修补之前**——
它的 `r_actions` 被 τ-bench 的状态污染**恒为 True**（见 `simglot/DEVIATIONS.md` D17）。

## 怎么修

`reward = r_actions ∧ r_outputs`，两个分量的受污染情况**不同**：
* `r_actions`（数据库终态）**被污染** ⇒ 用 `simglot/scripts/db_replay.py` 从
  `agent_trace` **独立重放**重建（与 v1.0 重建主矩阵标签的同一入口、同一缓存）；
* `r_outputs`（英文子串匹配）**不受污染**——它只读 `env.actions` 里的 respond 内容，
  与数据库无关 ⇒ 直接取归档 `summary.json` 的 `reward_detail.r_outputs`。

**保真度**：v1.0 已用主矩阵 33,402 个工具步逐字符核过重放（0 处不符）。

用法：cd sqj && python3 swe/score_envzh_corrected.py
产出：results/envzh_corrected.csv 与终端汇总
"""

from __future__ import annotations

import csv
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQJ = HERE.parent
SIMGLOT = SQJ.parent / "simglot"
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _bootstrap  # noqa: E402,F401  离线引导 + 重放缓存重定向

sys.path.insert(0, str(SIMGLOT / "scripts"))
sys.path.insert(0, str(SIMGLOT))
sys.path.insert(0, str(HERE))

from db_replay import replay_db  # noqa: E402  v1.0 的重放入口（带磁盘缓存）

TAGS = ("ez2_envzh", "ez2_lenmatch")      # env=zh 与 env=zhp（长度配平）
OUTDIR = SQJ / "results"


def run_tag(tag: str) -> int:
    OUT = OUTDIR / f"{'envzh' if tag=='ez2_envzh' else 'envzhp'}_corrected.csv"
    cells = sorted(glob.glob(str(SIMGLOT / "runs" / tag / "*" / "summary.json")))
    print(f"\n{tag}: {len(cells)} 格")

    rows, n_flip, n_err = [], 0, 0
    for f in cells:
        s = json.loads(Path(f).read_text(encoding="utf-8"))
        sp = s.get("spec") or {}
        if s.get("error"):
            n_err += 1
            continue
        tp = Path(f.replace("summary.json", "transcript.json"))
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        trace = tr.get("agent_trace", [])
        split = sp.get("task_split", "test")
        tid = sp.get("task_id")
        r_actions = bool(replay_db(split, tid, trace))
        r_out = (s.get("reward_detail") or {}).get("r_outputs")
        r_out = True if r_out is None else bool(r_out)
        corrected = 1.0 if (r_actions and r_out) else 0.0
        arch = s.get("reward")
        if arch is not None and float(arch) != corrected:
            n_flip += 1
        rows.append({
            "cell_id": s.get("cell_id"), "task_id": tid,
            "sim": sp.get("user_model"), "user_lang": sp.get("user_lang"),
            "rep": sp.get("seed", 0),
            "reward_archived": arch, "reward_corrected": corrected,
            "r_actions_corrected": int(r_actions), "r_outputs": int(r_out),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    arch_pass = sum(1 for r in rows if r["reward_archived"] == 1.0)
    corr_pass = sum(1 for r in rows if r["reward_corrected"] == 1.0)
    ra_arch = sum(1 for r in rows if r["r_actions_corrected"] == 1)
    print(f"有效格 {n}｜失败 {n_err}")
    print(f"归档（受污染）：DB 通过（= r_actions 恒真）⇒ 不能直接读；归档 reward 通过 {arch_pass}/{n}")
    print(f"**修正后**：DB 通过 {ra_arch}/{n}（{100*ra_arch/n:.1f}%）"
          f"｜Full 通过 {corr_pass}/{n}（{100*corr_pass/n:.1f}%）")
    print(f"标签翻转 {n_flip}/{n}（{100*n_flip/n:.1f}%）—— 与 v1.0 主矩阵的翻转量级一致即正常")
    print(f"已写 {OUT}")
    return 0


def main() -> int:
    for t in TAGS:
        run_tag(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
