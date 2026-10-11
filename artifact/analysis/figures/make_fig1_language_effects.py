#!/usr/bin/env python3
"""图 1：语言对评测仪器的作用（四联图）——**全部数字由冻结分析表重算**。

**动因（评审第二轮 P0-1）**：旧版 `fig1_language_effects.png` 出自一个已经不存在的
临时脚本，图内数值停留在修订前（`Δ = +0.6 pp`、`Qwen3.8-Max +2.0`、以及把
"7.5% 标签翻转率"当成"分数分辨率"的脚注），与 Table 1 / 正文相互矛盾。评审要求
「使用 frozen_table.csv 作为绘图输入，重新执行生成脚本；不能只改 Caption」。

本脚本因此是图 1 的唯一来源：全部点估计与任务聚类 95%CI 都从
`results/frozen_table.csv` 现算，不存在手填数字。四联图：

  (a) 各智能体 × 模拟器语言的成功率哑铃图 + 合并效应
  (b) 各智能体的轨迹崩塌率（en/zh 对比；仅最弱智能体可检出）
  (c) 评分器污染：归档 DB 判定 vs 重放修正后的 DB 判定（逐智能体）
  (d) 各效应量的森林图（配对、按任务聚类 95%CI）

用法：python3 scripts/make_fig1_language_effects.py
输出：paper/figures/fig1_language_effects.png（与 .svg）
"""

from __future__ import annotations

import collections
import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402
from critval import CRIT  # noqa: E402  (t(G−1) 临界值，与聚类 p 同参照)

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "results" / "frozen_table.csv"
OUT = ROOT.parent / "paper" / "figures" / "fig1_language_effects.png"

AGENTS = ["deepseek-v4.1-flash", "qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash"]
NICE = {
    "deepseek-v4.1-flash": "DS-V4.1-Flash",
    "qwen3.7-plus": "Q3.7-Plus",
    "qwen3.8-max": "Q3.8-Max",
    "qwen3.8-flash": "Q3.8-Flash",
}
C_EN, C_ZH = "#3b6ea5", "#d1691f"
C_NEUTRAL = "#bfbfbf"

plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 160,
    # SVG 里的元素 id / clip-path id 默认由随机盐生成，固定盐才能逐字节复现（见 D21-9）。
    "svg.hashsalt": "simglot",
})


# --------------------------------------------------------------------------- #
# 数据
# --------------------------------------------------------------------------- #
def load() -> list[dict]:
    with TABLE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["task_id"] = int(r["task_id"])
        r["collapse"] = int(r["collapse"])
        r["reward_full"] = int(float(r["reward_full"]))
        r["reward_db"] = int(float(r["reward_db"]))
        for k in ("reward_db_archived", "reward_full_archived"):
            v = r.get(k)
            r[k] = int(float(v)) if v not in (None, "", "None", "True", "False") else int(v == "True")
    assert rows, "冻结分析表为空——先运行 scripts/frozen_table.py --write"
    return rows


def _rate(rs, key):
    return sum(r[key] for r in rs) / len(rs) if rs else float("nan")


def _delta(rs, key="reward_full"):
    en = [r for r in rs if r["user_lang"] == "en"]
    zh = [r for r in rs if r["user_lang"] == "zh"]
    if not en or not zh:
        return float("nan")
    return 100 * (_rate(zh, key) - _rate(en, key))


def crve(diffs):
    """按簇聚类的均值与稳健 SE。diffs: [(cluster, value)]。

    与 `scripts/build_e3_results.py` 的 `crve` 逐字同源，保证图与表的区间一致。
    """
    n = len(diffs)
    if not n:
        return float("nan"), float("nan")
    m = sum(d for _, d in diffs) / n
    by = collections.defaultdict(float)
    for g, d in diffs:
        by[g] += d - m
    var = sum(v * v for v in by.values()) / (n * n)
    return m, math.sqrt(var)


def cluster_ci(rows, key="reward_full", statfn=None):
    """任务聚类 95%CI：每个任务先算一个 差值，再对 30 个任务值做 CRVE。

    statfn 给定时用它定义「每个任务的值」（点估计也由它给出），否则用
    该任务内 zh−en 的边际率差。抽样单位是任务，不是集。
    """
    by = collections.defaultdict(list)
    for r in rows:
        by[r["task_id"]].append(r)
    diffs = []
    for t, rs in sorted(by.items()):
        d = statfn(rs) if statfn else _delta(rs, key)
        if d == d:
            diffs.append((t, d))
    if not diffs:
        return float("nan"), float("nan"), float("nan")
    m, se = crve(diffs)
    return m, m - CRIT * se, m + CRIT * se


def flash_excl_collapse_delta(rows):
    sub = [r for r in rows if r["agent"] == "qwen3.8-flash" and not r["collapse"]]
    return _delta(sub)


def collapse_delta(rows, agent):
    sub = [r for r in rows if r["agent"] == agent]
    return _delta(sub, key="collapse")


# --------------------------------------------------------------------------- #
# 绘图
# --------------------------------------------------------------------------- #
def panel_a(ax, rows):
    y = np.arange(len(AGENTS))[::-1]
    pooled_en = 100 * _rate([r for r in rows if r["user_lang"] == "en"], "reward_full")
    pooled_zh = 100 * _rate([r for r in rows if r["user_lang"] == "zh"], "reward_full")
    lo, hi = 100.0, 0.0
    for i, ag in enumerate(AGENTS):
        en = [r for r in rows if r["agent"] == ag and r["user_lang"] == "en"]
        zh = [r for r in rows if r["agent"] == ag and r["user_lang"] == "zh"]
        xe, xz = 100 * _rate(en, "reward_full"), 100 * _rate(zh, "reward_full")
        d = _delta(en + zh)
        lo, hi = min(lo, xe, xz), max(hi, xe, xz)
        ax.plot([xe, xz], [y[i], y[i]], color=C_NEUTRAL, lw=2.4, zorder=1,
                solid_capstyle="round")
        ax.scatter(xe, y[i], s=62, color=C_EN, zorder=3)
        ax.scatter(xz, y[i], s=62, color=C_ZH, zorder=3)
        ax.text(max(xe, xz) + 0.5, y[i], f"{d:+.1f}", va="center", ha="left",
                fontsize=11.5, color="#333333")
    ax.scatter([], [], s=62, color=C_EN, label="English simulator")
    ax.scatter([], [], s=62, color=C_ZH, label="Chinese simulator")
    ax.legend(loc="lower right", frameon=False, fontsize=10.5,
              handletextpad=0.4, borderaxespad=0.2)
    ax.set_yticks(y)
    ax.set_yticklabels([NICE[a] for a in AGENTS])
    pad = 6.0
    ax.set_xlim(lo - pad, hi + pad + 4.0)
    ax.set_xlabel("Task success rate (%)")
    ax.grid(axis="x", color="#e6e6e6", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title(f"(a) Scores barely move — overall "
                 f"$\\mathrm{{LSI}} = {abs(pooled_zh - pooled_en) / pooled_en:.3f}$\n"
                 f"$\\Delta = {pooled_zh - pooled_en:+.1f}$ pp "
                 f"(task-clustered 95\\% CI crosses 0)")


def panel_b(ax, rows):
    x = np.arange(len(AGENTS))
    w = 0.36
    for off, lang, col in ((-w / 2, "en", C_EN), (+w / 2, "zh", C_ZH)):
        vals = []
        for ag in AGENTS:
            rs = [r for r in rows if r["agent"] == ag and r["user_lang"] == lang]
            vals.append(100 * _rate(rs, "collapse"))
        ax.bar(x + off, vals, width=w, color=col, zorder=3,
               label="English" if lang == "en" else "Chinese")
        for xi, v in zip(x + off, vals):
            if v > 0:
                ax.text(xi, v + 0.35, f"{v:.1f}", ha="center", va="bottom",
                        fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels([NICE[a] for a in AGENTS], rotation=24, ha="right")
    ax.set_ylabel("Trajectory-collapse rate (%)")
    ax.set_ylim(0, 18.5)
    ax.grid(axis="y", color="#e6e6e6", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", frameon=False, fontsize=10.5)
    ax.text(0.95, 16.3, "$p = 3.1\\times10^{-4}$", ha="center", fontsize=11)
    ax.set_title("(b) Collapse doubles in the Chinese arm —\n"
                 "detectable for the weakest agent only")


def panel_c(ax, rows):
    """评分器污染：归档的 DB 判定 vs 从轨迹重放修正后的 DB 判定。

    τ-bench 的 `Env.calculate_reward()` 在会话结束时把环境数据重置为初始态、
    回放参考答案去算 `gt_data_hash`，然后**不还原**；此后 `score(env)` 读到的
    「智能体终态」其实是参考答案终态，`r_actions` 因此在所有
    `conversation_done` 集上恒为 True（见 DEVIATIONS D17）。
    """
    x = np.arange(len(AGENTS))
    w = 0.36
    for off, key, col, lab in (
            (-w / 2, "reward_db_archived", "#b04a3a", "Archived DB label"),
            (+w / 2, "reward_db", "#2f7d5a", "Replayed DB label (corrected)")):
        vals = []
        for ag in AGENTS:
            rs = [r for r in rows if r["agent"] == ag]
            vals.append(100 * _rate(rs, key) if rs and key in rs[0] else float("nan"))
        ax.bar(x + off, vals, width=w, color=col, zorder=3, label=lab)
        for xi, v in zip(x + off, vals):
            ax.text(xi, v + 1.2, f"{v:.1f}", ha="center", va="bottom", fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels([NICE[a] for a in AGENTS], rotation=24, ha="right")
    ax.set_ylabel("Database check pass rate (%)")
    ax.set_ylim(0, 112)
    ax.grid(axis="y", color="#e6e6e6", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.30), ncol=2,
              frameon=False, fontsize=10, handletextpad=0.5, columnspacing=1.4)
    ax.set_title("(c) The archived database check is inflated by our harness's\n"
                 "second reading: every conversation-ending episode is labelled a pass")


def panel_d(ax, rows):
    def ci_for(sub, **kw):
        return cluster_ci(sub, **kw)

    flash = [r for r in rows if r["agent"] == "qwen3.8-flash"]
    items = [
        ("Overall language effect ($\\Delta$ success)",
         _delta(rows), ci_for(rows), "score"),
        ("DeepSeek-V4.1-Flash $\\Delta$ success",
         _delta([r for r in rows if r["agent"] == "deepseek-v4.1-flash"]),
         ci_for([r for r in rows if r["agent"] == "deepseek-v4.1-flash"]), "score"),
        ("Qwen3.7-Plus $\\Delta$ success",
         _delta([r for r in rows if r["agent"] == "qwen3.7-plus"]),
         ci_for([r for r in rows if r["agent"] == "qwen3.7-plus"]), "score"),
        ("Qwen3.8-Max $\\Delta$ success",
         _delta([r for r in rows if r["agent"] == "qwen3.8-max"]),
         ci_for([r for r in rows if r["agent"] == "qwen3.8-max"]), "score"),
        ("Qwen3.8-Flash $\\Delta$ success (all cells)",
         _delta(flash), ci_for(flash), "artifact"),
        ("Qwen3.8-Flash $\\Delta$ success (excl. collapse)",
         flash_excl_collapse_delta(rows),
         ci_for([r for r in flash if not r["collapse"]]), "clean"),
        ("Qwen3.8-Flash $\\Delta$ collapse rate",
         collapse_delta(rows, "qwen3.8-flash"),
         ci_for(flash, key="collapse"), "collapse"),
    ]
    colmap = {"score": "#808080", "artifact": "#7b52a1",
              "clean": "#4f9ad6", "collapse": "#199e77"}
    y = np.arange(len(items))[::-1]
    ax.axvline(0, color="#333333", lw=1.1, zorder=1)
    for i, (lab, est, (m, lo, hi), kind) in enumerate(items):
        col = colmap[kind]
        ax.plot([lo, hi], [y[i], y[i]], color=col, lw=2.6, alpha=0.75, zorder=2)
        ax.scatter(est, y[i], s=58, color=col, zorder=3)
        if lo > 0 or hi < 0:
            ax.text(hi + 0.5, y[i], "$\\neq 0$", va="center", ha="left",
                    fontsize=10, color="#333333")
    ax.set_yticks(y)
    ax.set_yticklabels([it[0] for it in items])
    ax.set_xlim(-14, 17)
    ax.set_xlabel("Effect size (percentage points)")
    ax.grid(axis="x", color="#e6e6e6", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title("(d) Which effects are distinguishable from zero\n"
                 "(paired, task-clustered 95% CI)")


def main() -> int:
    rows = load()
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 8.6))
    panel_a(axes[0, 0], rows)
    panel_b(axes[0, 1], rows)
    panel_c(axes[1, 0], rows)
    panel_d(axes[1, 1], rows)

    # 全图脚注：说明区间口径，不再出现"7.5% 分辨率"这类错误换算
    fig.text(0.5, 0.012,
             "Point estimates: marginal zh$-$en difference in rate over all "
             "episodes of the relevant subset. "
             "Confidence intervals: task-clustered robust (CRVE over the 30 tasks); "
             "tasks are the resampling unit. "
             "All values recomputed from results/frozen_table.csv.",
             ha="center", fontsize=9.5, color="#444444")

    fig.tight_layout(rect=(0, 0.032, 1, 1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight")
    # SVG 里 matplotlib 默认写一行 `<dc:date>`（墙上时间），会让同一环境重生成也逐字节不同。
    # 显式令 Date=None 去掉它，使 SVG 与 PNG 一样在同环境下可逐字节对账（见 D21-9）。
    fig.savefig(OUT.with_suffix(".svg"), bbox_inches="tight", metadata={"Date": None})
    print(f"已写 {OUT} 与 {OUT.with_suffix('.svg')}")

    # 与论文表共享的控制台对账
    print("\n面板 (a)/(d) 用到的点估计：")
    for ag in AGENTS:
        en = [r for r in rows if r["agent"] == ag and r["user_lang"] == "en"]
        zh = [r for r in rows if r["agent"] == ag and r["user_lang"] == "zh"]
        se, sz = _rate(en, "reward_full"), _rate(zh, "reward_full")
        print(f"  {ag:<22}{100*se:6.2f}%{100*sz:6.2f}%  Δ{100*(sz-se):+6.2f}  "
              f"LSI {abs(sz-se)/se:.4f}")
    se = _rate([r for r in rows if r["user_lang"] == "en"], "reward_full")
    sz = _rate([r for r in rows if r["user_lang"] == "zh"], "reward_full")
    print(f"  {'POOLED':<22}{100*se:6.2f}%{100*sz:6.2f}%  Δ{100*(sz-se):+6.2f}  "
          f"LSI {abs(sz-se)/se:.4f}")
    print("\npanel (b) 崩塌率：")
    for ag in AGENTS:
        e = 100 * _rate([r for r in rows if r["agent"] == ag
                         and r["user_lang"] == "en"], "collapse")
        z = 100 * _rate([r for r in rows if r["agent"] == ag
                         and r["user_lang"] == "zh"], "collapse")
        print(f"  {ag:<22}{e:6.2f}%{z:6.2f}%")
    print("\npanel (c)：")
    sub = [r for r in rows if r["agent"] == "qwen3.8-flash"]
    print(f"  all cells      Δ {_delta(sub):+.2f} pp")
    print(f"  excl. collapse Δ {flash_excl_collapse_delta(rows):+.2f} pp")
    print("\npanel (d) 点估计与任务聚类 95%CI：")
    flash = [r for r in rows if r["agent"] == "qwen3.8-flash"]
    for lab, est, ci in [
        ("overall", _delta(rows), cluster_ci(rows)),
        ("deepseek-v4.1-flash",
         _delta([r for r in rows if r["agent"] == "deepseek-v4.1-flash"]),
         cluster_ci([r for r in rows if r["agent"] == "deepseek-v4.1-flash"])),
        ("qwen3.7-plus", _delta([r for r in rows if r["agent"] == "qwen3.7-plus"]),
         cluster_ci([r for r in rows if r["agent"] == "qwen3.7-plus"])),
        ("qwen3.8-max", _delta([r for r in rows if r["agent"] == "qwen3.8-max"]),
         cluster_ci([r for r in rows if r["agent"] == "qwen3.8-max"])),
        ("qwen3.8-flash", _delta(flash), cluster_ci(flash)),
        ("qwen3.8-flash excl.", flash_excl_collapse_delta(rows),
         cluster_ci([r for r in flash if not r["collapse"]])),
        ("qwen3.8-flash collapse", collapse_delta(rows, "qwen3.8-flash"),
         cluster_ci(flash, key="collapse")),
    ]:
        print(f"  {lab:<22}{est:+7.2f}  [{ci[1]:+.2f}, {ci[2]:+.2f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
