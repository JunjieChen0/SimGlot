#!/usr/bin/env python3
"""图 2：2×2 环境语言实验。

左图 崩塌率（四格），右图 通过率（全集口径，四格）。两张子图共享 x 轴分组
（用户语言），用颜色区分环境语言，并在每组上标出「环境 zh − 环境 en」的差
与任务聚类 95% 自助法区间。

数据来源与分析脚本同源（`analyze_2x2.py` 的 `load`），保证图与表中数字一致。
用法：python3 scripts/make_fig2_2x2.py
输出：paper/figures/fig2_env_lang_2x2.png（与 .svg）
"""

from __future__ import annotations

import collections
import random
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_2x2 import boot_ci, load, rate  # noqa: E402

AGENT = "qwen3.8-flash"
TAGS = ["e2_main24", "ez2_envzh"]
OUT = ROOT.parent / "paper" / "figures" / "fig2_env_lang_2x2.png"

C_EN, C_ZH = "#3b6ea5", "#c0504d"
LBL_ENV = {"en": "English environment", "zh": "Chinese environment"}
LBL_USER = {"en": "English user", "zh": "Chinese user"}


def collect() -> list[dict]:
    cells: dict = {}
    for tag in TAGS:
        for k, v in load(tag, AGENT).items():
            cells.setdefault(k, v)          # 先列出的批次为准（与分析脚本一致）
    # 只保留四格齐全的配对点
    grp = collections.defaultdict(dict)
    for k, v in cells.items():
        grp[(k[0], k[1], k[3])][(k[2], k[4])] = v
    out = []
    for d in grp.values():
        if len(d) == 4:
            out.extend(d.values())
    return out


def panel(ax, cells, key, title, ylabel):
    xs = [0, 1]
    w = 0.34
    tops = []
    for off, env in ((-w / 2, "en"), (+w / 2, "zh")):
        vals, los, his = [], [], []
        for u in ("en", "zh"):
            sub = [r for r in cells if r["user"] == u and r["env"] == env]
            sub = [r for r in sub if r.get(key) is not None]
            v = 100 * rate(sub, key)
            bt = collections.defaultdict(list)
            for r in sub:
                bt[r["task"]].append(r)
            lo, hi = boot_ci(bt, lambda s: 100 * rate(s, key))
            vals.append(v)
            los.append(max(0.0, v - lo))
            his.append(max(0.0, hi - v))
        ax.bar([x + off for x in xs], vals, w, yerr=[los, his],
               color=C_EN if env == "en" else C_ZH, edgecolor="black",
               linewidth=0.6, capsize=3, label=LBL_ENV[env], zorder=3)
        tops.append([vals[i] + his[i] for i in range(2)])
        for x, v in zip(xs, vals):
            ax.text(x + off, tops[-1][xs.index(x)] + 1.2, f"{v:.1f}",
                    ha="center", va="bottom", fontsize=8)
    top = max(max(a, b) for a, b in zip(tops[0], tops[1]))
    # 差值注释：每组一个，放在柱顶之上
    for x, u in zip(xs, ("en", "zh")):
        a = [r for r in cells if r["user"] == u and r["env"] == "zh"
             and r.get(key) is not None]
        b = [r for r in cells if r["user"] == u and r["env"] == "en"
             and r.get(key) is not None]
        d = 100 * (rate(a, key) - rate(b, key))
        bytask = collections.defaultdict(lambda: {"en": [], "zh": []})
        for r in cells:
            if r["user"] == u:
                bytask[r["task"]][r["env"]].append(r)
        tasks = sorted(bytask)
        rng = random.Random(20261008)
        draws = []
        for _ in range(2000):
            pick = [rng.choice(tasks) for _ in tasks]
            z = [r for t in pick for r in bytask[t]["zh"]]
            e = [r for t in pick for r in bytask[t]["en"]]
            z = [r for r in z if r.get(key) is not None]
            e = [r for r in e if r.get(key) is not None]
            if z and e:
                draws.append(100 * (rate(z, key) - rate(e, key)))
        lo, hi = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
        ax.text(x, -0.30, f"$\\Delta$ {d:+.1f} pp  [{lo:+.1f}, {hi:+.1f}]",
                transform=ax.get_xaxis_transform(), ha="center", va="top",
                fontsize=7.5, color="#333333")
    ax.set_ylim(0, (top + 3) * 1.18)
    ax.set_xticks(xs)
    ax.set_xticklabels([LBL_USER["en"], LBL_USER["zh"]])
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)


def main() -> int:
    cells = collect()
    if not cells:
        print("尚无可画的数据")
        return 1
    n = len(cells) // 4
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.6))
    # SVG 的元素 id 由随机盐生成、正文写一行 dc:date；两者都去掉才能逐字节复现（D21-9）
    plt.rcParams["svg.hashsalt"] = "simglot"
    panel(axes[0], cells, "col", "Trajectory collapse rate", "Collapse rate (%)")
    panel(axes[1], cells, "reward", "Pass rate", "Pass rate (%)")

    axes[0].legend(loc="upper left", fontsize=8, frameon=False)
    fig.suptitle(f"Environment language $\\times$ user language ($n = {n}$ paired "
                 f"triples per cell)", fontsize=10)
    fig.tight_layout(rect=(0, 0.10, 1, 0.94))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=220)
    fig.savefig(OUT.with_suffix(".svg"), metadata={"Date": None})
    print(f"写出 {OUT}（{n} 个配对点/格）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
