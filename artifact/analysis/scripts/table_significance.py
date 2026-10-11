#!/usr/bin/env python3
"""统一显著性表：每「智能体 × 评分口径」给出点估计、任务聚类 95%CI、精确检验 p、
以及「聚类区间是否排除零」的判定——供正文表格与论断共用（评审 P0-3）。

动因：此前正文各处把 Fisher / McNemar（把每集当独立观测，是**更宽松**的检验）与
任务聚类区间混着用，出现「按 Fisher 显著、按聚类区间跨零」仍被称作 resolved 的
情况。本脚本把两种口径并排印出，并规定**判定一律以聚类区间为准**，精确检验只作
参考；凡聚类区间跨零者，正文不得称其为已解决。

用法：python3 scripts/table_significance.py
"""

from __future__ import annotations

import collections
import csv
import math
from pathlib import Path
from critval import CRIT  # noqa: E402  (t(G−1) 临界值，与聚类 p 同参照)
from _tee import RESULTS, run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "results" / "frozen_table.csv"
AGENTS = ["deepseek-v4.1-flash", "qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash"]
LABEL = {
    "deepseek-v4.1-flash": "DeepSeek-V4.1-Flash",
    "qwen3.7-plus": "Qwen3.7-Plus",
    "qwen3.8-max": "Qwen3.8-Max",
    "qwen3.8-flash": "Qwen3.8-Flash",
}


def fisher_exact(a, b, c, d):
    """2×2 表 [[a,b],[c,d]] 的双尾 Fisher 精确检验。"""
    from math import comb

    n = a + b + c + d
    r1, c1 = a + b, a + c

    def pr(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)

    p0 = pr(a)
    tot = 0.0
    for x in range(max(0, c1 - (n - r1)), min(r1, c1) + 1):
        if pr(x) <= p0 + 1e-12:
            tot += pr(x)
    return min(1.0, tot)


def crve(diffs):
    n = len(diffs)
    if not n:
        return float("nan"), float("nan")
    m = sum(d for _, d in diffs) / n
    by = collections.defaultdict(float)
    for g, d in diffs:
        by[g] += d - m
    return m, math.sqrt(sum(v * v for v in by.values()) / (n * n))


def delta_and_ci(rows, key):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["task_id"]].append(r)
    diffs = []
    for t, rs in sorted(by.items()):
        en = [r for r in rs if r["user_lang"] == "en"]
        zh = [r for r in rs if r["user_lang"] == "zh"]
        if en and zh:
            diffs.append((t, 100 * (sum(r[key] for r in zh) / len(zh)
                                    - sum(r[key] for r in en) / len(en))))
    m, se = crve(diffs)
    return m, m - CRIT * se, m + CRIT * se


def counts(rows, key):
    en = [r for r in rows if r["user_lang"] == "en"]
    zh = [r for r in rows if r["user_lang"] == "zh"]
    return sum(r[key] for r in en), len(en), sum(r[key] for r in zh), len(zh)


def main() -> int:
    with TABLE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    def as01(v):
        return int(v in ("1", "1.0", "True", "true"))

    for r in rows:
        r["task_id"] = int(r["task_id"])
        for k in ("reward_full", "reward_db", "collapse"):
            r[k] = as01(r[k])

    print("%-22s %-6s %8s %20s %11s %6s" %
          ("agent", "rule", "Δ(pp)", "clustered 95% CI", "exact p", "resolved"))
    for name, key in (("full", "reward_full"), ("db", "reward_db")):
        for ag in AGENTS + [None]:
            sub = rows if ag is None else [r for r in rows if r["agent"] == ag]
            m, lo, hi = delta_and_ci(sub, key)
            k1, n1, k2, n2 = counts(sub, key)
            p = fisher_exact(k2, n2 - k2, k1, n1 - k1)
            res = "yes" if (lo > 0 or hi < 0) else "no"
            print("%-22s %-6s %+8.2f   [%+7.2f, %+7.2f]  %10.3g %6s" %
                  (LABEL.get(ag, "Overall"), name, m, lo, hi, p, res))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(RESULTS / "significance_table.txt", main))
