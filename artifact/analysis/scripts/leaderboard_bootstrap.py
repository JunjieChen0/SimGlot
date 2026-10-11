#!/usr/bin/env python3
"""排行榜稳定性：**成对**的任务聚类自助法，两臂同时覆盖（评审 P0-6）。

此前只报了英文臂的前两名差与（两语混合的）第一名频率。评审要求：用同一批任务重抽
同时驱动两臂（成对），并分语言给出——

  · 每臂各智能体成为第一名的概率；
  · 前两名差距的分布与 95%CI；
  · 两臂之间前两名**次序反转**的频率；
  · Kendall τ 的分布（而非单个点值）。

重抽单位是任务（30 条），每次重抽对**两臂用同一批任务**，以保留配对结构。

用法：python3 scripts/leaderboard_bootstrap.py
"""

from __future__ import annotations

import collections
import csv
import random
from pathlib import Path

import numpy as np
from critval import CRIT  # noqa: E402  (t(G−1) 临界值，与聚类 p 同参照)

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "results" / "frozen_table.csv"
NBOOT, SEED = 5000, 20261008
AGENTS = ["deepseek-v4.1-flash", "qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash"]
LABEL = {"deepseek-v4.1-flash": "DeepSeek-V4.1-Flash", "qwen3.7-plus": "Qwen3.7-Plus",
         "qwen3.8-max": "Qwen3.8-Max", "qwen3.8-flash": "Qwen3.8-Flash"}


def kendall_tau(a, b):
    """Kendall τ-a（无并列），4 个智能体的排名向量。"""
    n = len(a)
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            conc += s > 0
            disc += s < 0
    return (conc - disc) / (conc + disc) if conc + disc else float("nan")


def kendall_tau_b(x, y):
    """Kendall τ-b（并列校正），输入两臂各自的成功率向量。

    τ-a 把并列当作不构成任何一对，因而在并列多时会失真；τ-b 用
    τ_b = (C − D) / sqrt((n0 − n1)(n0 − n2)) 把两边的并列量从分母里扣除。
    本数据里并列确实存在（见第一名的并列率），故两个口径都给出。
    """
    n = len(x)
    n0 = n * (n - 1) / 2
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = x[i] - x[j], y[i] - y[j]
            if dx * dy > 0:
                conc += 1
            elif dx * dy < 0:
                disc += 1
    def tie_pairs(v):
        c = collections.Counter(v)
        return sum(t * (t - 1) / 2 for t in c.values())
    n1, n2 = tie_pairs(x), tie_pairs(y)
    den = ((n0 - n1) * (n0 - n2)) ** 0.5
    return (conc - disc) / den if den else float("nan")


def signed_pair_diff(by, tasks, lang, m, n):
    """逐任务配对的有符号差 S_m − S_n（pp），返回 [(task, diff)] 供聚类求区间。"""
    out = []
    for t in tasks:
        sub = [x for x in by[t] if x["user_lang"] == lang]
        rm = [x["reward_full"] for x in sub if x["agent"] == m]
        rn = [x["reward_full"] for x in sub if x["agent"] == n]
        if rm and rn:
            out.append((t, 100 * (sum(rm) / len(rm) - sum(rn) / len(rn))))
    return out


def crve_ci(diffs):
    """与 build_e3_results.crve 同源：按任务聚类的均值及其稳健 95%CI。"""
    n = len(diffs)
    mean = sum(d for _, d in diffs) / n
    by = collections.defaultdict(float)
    for g, d in diffs:
        by[g] += d - mean
    se = (sum(v * v for v in by.values()) / (n * n)) ** 0.5
    return mean, mean - CRIT * se, mean + CRIT * se


def main() -> int:
    with TABLE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["task_id"] = int(r["task_id"])
        r["reward_full"] = int(r["reward_full"] in ("1", "1.0", "True", "true"))

    by = collections.defaultdict(list)
    for r in rows:
        by[r["task_id"]].append(r)
    tasks = sorted(by)
    rng = random.Random(SEED)

    # 观测值
    def rates(sub):
        return {a: sum(x["reward_full"] for x in sub if x["agent"] == a)
                / max(1, sum(1 for x in sub if x["agent"] == a)) for a in AGENTS}

    def rank_of(sub):
        r = rates(sub)
        order = sorted(AGENTS, key=lambda a: -r[a])
        return order, r

    obs_en = [x for x in rows if x["user_lang"] == "en"]
    obs_zh = [x for x in rows if x["user_lang"] == "zh"]
    ord_en, rr_en = rank_of(obs_en)
    ord_zh, rr_zh = rank_of(obs_zh)

    print("=" * 74)
    print("排行榜稳定性 · 成对任务聚类自助法（两臂同批重抽）")
    print("=" * 74)
    print("\n  观测排名：")
    for i, (a, b) in enumerate(zip(ord_en, ord_zh), 1):
        print(f"    #{i}  en {LABEL[a]:<20}{100*rr_en[a]:5.1f}%  |  "
              f"zh {LABEL[b]:<20}{100*rr_zh[b]:5.1f}%")

    first_en = collections.Counter()
    first_zh = collections.Counter()
    gaps_en, gaps_zh = [], []
    flips = 0
    taus = []
    taus_b = []
    tie_en = tie_zh = 0
    first_en_tw = collections.Counter()
    first_zh_tw = collections.Counter()
    for _ in range(NBOOT):
        pick = [rng.choice(tasks) for _ in tasks]
        s_en = [x for t in pick for x in by[t] if x["user_lang"] == "en"]
        s_zh = [x for t in pick for x in by[t] if x["user_lang"] == "zh"]
        oe, re_ = rank_of(s_en)
        oz, rz = rank_of(s_zh)
        first_en[oe[0]] += 1
        first_zh[oz[0]] += 1
        gaps_en.append(100 * (re_[oe[0]] - re_[oe[1]]))
        gaps_zh.append(100 * (rz[oz[0]] - rz[oz[1]]))
        flips += (oe[:2] != oz[:2])          # 前两名的集合/次序不同
        taus.append(kendall_tau([oe.index(a) for a in AGENTS],
                                [oz.index(a) for a in AGENTS]))
        taus_b.append(kendall_tau_b([re_[a] for a in AGENTS], [rz[a] for a in AGENTS]))
        # 第一名并列：最高成功率与次高相等
        se_ = sorted((re_[a] for a in AGENTS), reverse=True)
        sz_ = sorted((rz[a] for a in AGENTS), reverse=True)
        te = se_[0] == se_[1]
        tz = sz_[0] == sz_[1]
        tie_en += te
        tie_zh += tz
        # 并列均分：并列者各记 1/k
        top_e = [a for a in AGENTS if re_[a] == se_[0]]
        top_z = [a for a in AGENTS if rz[a] == sz_[0]]
        for a in top_e:
            first_en_tw[a] += 1 / len(top_e)
        for a in top_z:
            first_zh_tw[a] += 1 / len(top_z)

    def ci(v):
        v = np.array(v)
        return float(np.mean(v)), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))

    print("\n  第一名频率（自助）:")
    print(f"    {'agent':<22}{'English arm':>14}{'Chinese arm':>14}")
    for a in AGENTS:
        print(f"    {LABEL[a]:<22}{100*first_en[a]/NBOOT:13.1f}%{100*first_zh[a]/NBOOT:13.1f}%")

    print("\n  第一名并列（最高与次高成功率相等）:")
    print(f"    en {tie_en}/{NBOOT} = {100*tie_en/NBOOT:.2f}%"
          f"｜zh {tie_zh}/{NBOOT} = {100*tie_zh/NBOOT:.2f}%")
    print("    破并列规则：按脚本内 AGENTS 常量顺序取靠前者（固定且可复现，但不对称）")
    print("    并列均分后的第一名概率（与上表对照）:")
    for a in AGENTS:
        print(f"      {LABEL[a]:<22}{100*first_en_tw[a]/NBOOT:13.2f}%"
              f"{100*first_zh_tw[a]/NBOOT:13.2f}%")

    m, lo, hi = ci(gaps_en)
    print(f"\n  [动态] 前两名差距（每次重抽重排后取 #1−#2，天然非负）")
    print(f"    en 臂: {m:.2f} pp，95%CI [{lo:+.2f}, {hi:+.2f}]")
    m, lo, hi = ci(gaps_zh)
    print(f"    zh 臂: {m:.2f} pp，95%CI [{lo:+.2f}, {hi:+.2f}]")
    print("    → 该量下界天然 ≥0，**不能**当作两模型差异的显著性检验（评审 P0-4）")

    # ── 固定模型差（有符号）：S_m − S_n，逐任务配对后按任务聚类 ──────────────
    print("\n  [固定] 两模型差（有符号，配对的 S_m − S_n，任务聚类 95%CI）:")
    PAIRS = [("deepseek-v4.1-flash", "qwen3.7-plus"),
             ("deepseek-v4.1-flash", "qwen3.8-max"),
             ("qwen3.7-plus", "qwen3.8-max")]
    fixed = {}
    for lang, arm in (("en", "English arm"), ("zh", "Chinese arm")):
        print(f"    {arm}:")
        for a, b_ in PAIRS:
            d = signed_pair_diff(by, tasks, lang, a, b_)
            mean, lo, hi = crve_ci(d)
            fixed[(lang, a, b_)] = (mean, lo, hi)
            cross = "跨零" if lo <= 0 <= hi else "不跨零"
            print(f"      {LABEL[a]:<20} − {LABEL[b_]:<20}"
                  f"{mean:+6.2f} pp  [{lo:+6.2f}, {hi:+6.2f}]  {cross}")

    print(f"\n  两臂前两名次序反转频率: {100*flips/NBOOT:.1f}%")
    m, lo, hi = ci(taus)
    print(f"  Kendall τ-a（无并列校正）: 均值 {m:.3f}，95%CI [{lo:.3f}, {hi:.3f}]，"
          f"P(τ<1) = {100*sum(1 for t in taus if t < 0.999)/NBOOT:.1f}%")
    mb, lob, hib = ci(taus_b)
    print(f"  Kendall τ-b（并列校正）  : 均值 {mb:.3f}，95%CI [{lob:.3f}, {hib:.3f}]，"
          f"P(τ<1) = {100*sum(1 for t in taus_b if t < 0.999)/NBOOT:.1f}%")
    print("    （观测排名无并列，故点值 τ-a = τ-b = 0.667；差别只在重抽分布上。）")
    print("\n  读法：动态前两名差（天然非负）看排行榜稳定性；固定模型差（有符号）")
    print("        才回答「两个模型在这些数据上是否有可分辨的差异」。两者互补，不可互替。")
    return 0


if __name__ == "__main__":
    # 本脚本原先只打印不落盘，于是 results/leaderboard_bootstrap.txt 停留在一份
    # **修正前**的旧输出（D17 之后未重生成），而论文引用的已是修正值。现改为
    # stdout 与产物文件同源，二者不可能再分叉。
    import contextlib
    import io

    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        _rc = main()
    _text = _buf.getvalue()
    (ROOT / "results" / "leaderboard_bootstrap.txt").write_text(_text, encoding="utf-8")
    print(_text, end="")
    raise SystemExit(_rc)
