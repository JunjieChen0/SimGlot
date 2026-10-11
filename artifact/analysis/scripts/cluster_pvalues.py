#!/usr/bin/env python3
"""任务聚类的 **p 值**：把多重比较校正统一放在聚类口径上（第三轮评审 P0-5）。

**问题**：正文一边引用未聚类的精确检验 p 值（Fisher / McNemar）去过 Bonferroni 阈值
（0.05/4 = 0.0125），一边用任务聚类的 95%CI 说「区间不跨零」。两者口径不同，
不能用未聚类 p 值做校正、再用聚类区间宣称校正后的显著性。

**本脚本**：与 `build_e3_results.crve` 同源地算每个 (agent, rule) 的聚类均值与标准误，
再用 (a) 正态、(b) t(G−1 = 29) 两种参照给出**聚类 p 值**，并同时打印
Bonferroni 阈值下的判定，以及未校正的判定，供正文一次性对齐口径。

用法：python3 scripts/cluster_pvalues.py
"""

from __future__ import annotations

import collections
import csv
import math
from pathlib import Path

from scipy.stats import norm, t as tdist

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "results" / "frozen_table.csv"
OUT = ROOT / "results" / "cluster_pvalues.txt"

AGENTS = ["deepseek-v4.1-flash", "qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash"]
LABEL = {"deepseek-v4.1-flash": "DeepSeek-V4.1-Flash", "qwen3.7-plus": "Qwen3.7-Plus",
         "qwen3.8-max": "Qwen3.8-Max", "qwen3.8-flash": "Qwen3.8-Flash"}


def as01(v) -> int:
    return 1 if str(v) in ("1", "1.0", "True", "true") else 0


def load() -> list[dict]:
    with TABLE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["task_id"] = int(r["task_id"])
        for k in ("reward_full", "reward_db"):
            r[k] = as01(r[k])
    return rows


def clustered(rows, key, agent=None):
    """按任务聚类的 (mean, se, G)。agent=None 时为整体。"""
    sub = [r for r in rows if agent is None or r["agent"] == agent]
    by = collections.defaultdict(lambda: {"en": [], "zh": []})
    for r in sub:
        by[r["task_id"]][r["user_lang"]].append(r[key])
    diffs = []
    for tid, d in sorted(by.items()):
        if d["en"] and d["zh"]:
            diffs.append((tid, 100 * (sum(d["zh"]) / len(d["zh"]) - sum(d["en"]) / len(d["en"]))))
    n = len(diffs)
    m = sum(v for _, v in diffs) / n
    acc = collections.defaultdict(float)
    for g, v in diffs:
        acc[g] += v - m
    se = math.sqrt(sum(x * x for x in acc.values()) / (n * n))
    return m, se, n


def main() -> int:
    rows = load()
    out = []

    def P(s=""):
        out.append(s)
        print(s)

    P("=" * 84)
    P("任务聚类的 p 值（口径统一用聚类；多重比较校正也放在聚类口径上）")
    P("=" * 84)
    P("\n  参照分布：正态（z）与 t(G−1)，G = 任务数 = 30 ⇒ df = 29")
    P("  Bonferroni：4 个智能体 ⇒ α = 0.05/4 = 0.0125\n")

    for key, name in (("reward_full", "full reward"), ("reward_db", "database-only")):
        P(f"── 评分口径：{name} ──")
        P(f"  {'agent':<22}{'Δ(pp)':>9}{'SE':>8}{'p(z)':>11}{'p(t29)':>11}"
          f"{'≤.0125?':>10}{'≤.05?':>9}")
        for ag in AGENTS:
            m, se, n = clustered(rows, key, ag)
            z = m / se
            pz = 2 * norm.sf(abs(z))
            pt = 2 * tdist.sf(abs(z), df=n - 1)
            P(f"  {LABEL[ag]:<22}{m:>+9.2f}{se:>8.2f}{pz:>11.3g}{pt:>11.3g}"
              f"{('yes' if pt <= 0.0125 else 'no'):>10}{('yes' if pt <= 0.05 else 'no'):>9}")
        m, se, n = clustered(rows, key)
        z = m / se
        P(f"  {'POOLED':<22}{m:>+9.2f}{se:>8.2f}{2*norm.sf(abs(z)):>11.3g}"
          f"{2*tdist.sf(abs(z), df=n-1):>11.3g}{'---':>10}{'---':>9}")
        P("")

    P("  与精确检验的对照（见 results/significance_table.txt）：Qwen3.7-Plus full 的")
    P("  Fisher p = 1.3e−4、Qwen3.8-Flash DB 的 Fisher p = 1.8e−3 都是**未聚类**口径，")
    P("  偏小；聚类口径下同一效应的 p 值见上表。正文一律引用上表的聚类 p 值。")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    P(f"\n  已写 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
