#!/usr/bin/env python3
"""整数计数总账：把论文里出现的**每一个整数计数**从冻结表重算并核对（第三轮评审 P0-1）。

评审要求「从原始冻结数据生成一份统一的整数计数审计表，逐一核对每种
Agent / Simulator / Language / Scoring Rule 的成功数及分母」。本脚本输出：

  1. 每个 (Agent, Language, Scoring Rule) 的 成功数/分母
  2. 每个 (Agent, Simulator, Language) 的分母（用于核查 540 vs 539 这类）
  3. 论文正文引用到的整数的清单与重算值对照
  4. 断言：full == (db AND sub)、db ≥ full、每 (agent,lang) 分母为 540

用法：python3 scripts/audit_counts.py            # 打印总账
      python3 scripts/audit_counts.py --check    # 只跑断言，失败即非零退出
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "results" / "frozen_table.csv"
OUT = ROOT / "results" / "count_audit.txt"

AGENTS = ["deepseek-v4.1-flash", "qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash"]


def as01(v) -> int:
    return 1 if str(v) in ("1", "1.0", "True", "true") else 0


def load() -> list[dict]:
    with TABLE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["task_id"] = int(r["task_id"])
        for k in ("reward_full", "reward_db", "reward_sub", "collapse",
                  "reward_full_archived", "reward_db_archived"):
            r[k] = as01(r[k])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    rows = load()
    out: list[str] = []

    def P(line: str = "") -> None:
        out.append(line)
        print(line)

    P("=" * 78)
    P("整数计数总账 · 全部重算自 results/frozen_table.csv")
    P("=" * 78)
    P(f"\n  总评分记录 n = {len(rows)}")

    # ── 断言 ──────────────────────────────────────────────────────────────
    viol1 = sum(1 for r in rows if int(r["reward_db"] and r["reward_sub"]) != r["reward_full"])
    viol2 = sum(1 for r in rows if r["reward_db"] < r["reward_full"])
    P(f"\n  [断言] full == (db AND sub) 违例 {viol1}｜db ≥ full 违例 {viol2}")
    per = collections.Counter((r["agent"], r["user_lang"]) for r in rows)
    bad = {k: v for k, v in per.items() if v != 540}
    P(f"  [断言] 每 (agent, lang) 分母均为 540：{'是' if not bad else bad}")
    if viol1 or viol2 or bad:
        return 1
    if a.check:
        return 0

    # ── 1. Agent × Language × Rule ────────────────────────────────────────
    P("\n── 1. 每 (Agent, Language, Scoring Rule) 的成功数 / 分母 ──")
    P(f"  {'agent':<22}{'lang':<6}{'full':>10}{'db':>10}{'sub':>10}{'n':>7}")
    for ag in AGENTS:
        for lg in ("en", "zh"):
            sub = [r for r in rows if r["agent"] == ag and r["user_lang"] == lg]
            P(f"  {ag:<22}{lg:<6}{sum(r['reward_full'] for r in sub):>10}"
              f"{sum(r['reward_db'] for r in sub):>10}{sum(r['reward_sub'] for r in sub):>10}"
              f"{len(sub):>7}")
    for lg in ("en", "zh"):
        sub = [r for r in rows if r["user_lang"] == lg]
        P(f"  {'POOLED':<22}{lg:<6}{sum(r['reward_full'] for r in sub):>10}"
          f"{sum(r['reward_db'] for r in sub):>10}{sum(r['reward_sub'] for r in sub):>10}"
          f"{len(sub):>7}")

    # ── 2. Agent × Simulator × Language 分母 ──────────────────────────────
    P("\n── 2. 每 (Agent, Simulator, Language) 的分母（核查 540 vs 539 类不一致）──")
    sims = sorted({r["sim"] for r in rows})
    P("  " + "agent".ljust(22) + "".join(s[:10].rjust(12) for s in sims))
    for ag in AGENTS:
        for lg in ("en", "zh"):
            line = f"  {(ag + ' / ' + lg).ljust(22)}"
            for sm in sims:
                n = sum(1 for r in rows
                        if r["agent"] == ag and r["user_lang"] == lg and r["sim"] == sm)
                line += str(n).rjust(12)
            P(line)

    # ── 3. 论文引用的整数 ─────────────────────────────────────────────────
    P("\n── 3. 正文引用的整数 · 重算对照 ──")
    en = [r for r in rows if r["user_lang"] == "en"]
    zh = [r for r in rows if r["user_lang"] == "zh"]
    checks = [
        ("§3.6 主矩阵有效评分记录", 4320, len(rows)),
        ("全表 full 成功（en）", None, sum(r["reward_full"] for r in en)),
        ("全表 full 成功（zh）", None, sum(r["reward_full"] for r in zh)),
        ("§4.11 DB 通过格中 substring 失败（en）", 38,
         sum(1 for r in en if r["reward_db"] and not r["reward_sub"])),
        ("§4.11 DB 通过格中 substring 失败（zh）", 16,
         sum(1 for r in zh if r["reward_db"] and not r["reward_sub"])),
        ("§4.11 DB 通过格数（en）", 1421, sum(r["reward_db"] for r in en)),
        ("§4.11 DB 通过格数（zh）", 1462, sum(r["reward_db"] for r in zh)),
        ("§4.5 崩塌集（全部四个智能体）", 106, sum(r["collapse"] for r in rows)),
        ("§4.5 非崩塌集（qwen3.8-flash，n=1080）", 974,
         sum(1 for r in rows if r["agent"] == "qwen3.8-flash" and not r["collapse"])),
        ("Table 15 崩塌（qwen3.8-flash en）", 35,
         sum(r["collapse"] for r in rows
             if r["agent"] == "qwen3.8-flash" and r["user_lang"] == "en")),
        ("Table 15 崩塌（qwen3.8-flash zh）", 71,
         sum(r["collapse"] for r in rows
             if r["agent"] == "qwen3.8-flash" and r["user_lang"] == "zh")),
        ("§4.11 修正 DB 通过（全表）", 2883, sum(r["reward_db"] for r in rows)),
        ("§4.11 修正 Full 通过（全表）", 2829, sum(r["reward_full"] for r in rows)),
        ("§4.11 归档 DB 通过（全表）", 4194,
         sum(r["reward_db_archived"] for r in rows)),
        ("§4.11 归档 Full 通过（全表）", 4073,
         sum(r["reward_full_archived"] for r in rows)),
    ]
    # §4.1 配对符号检验的整数（同任务/模拟器/种子，只差语言）
    cell: dict = {}
    for r in rows:
        cell.setdefault((r["agent"], r["task_id"], r["sim"], r["seed"]), {})[r["user_lang"]] = r["reward_full"]
    paired = [v for v in cell.values() if "en" in v and "zh" in v]
    checks += [
        ("§4.1 配对格数", 2160, len(paired)),
        ("§4.1 偏向中文的配对", 312, sum(1 for v in paired if v["zh"] > v["en"])),
        ("§4.1 偏向英文的配对", 249, sum(1 for v in paired if v["zh"] < v["en"])),
        ("§4.1 并列配对", 1599, sum(1 for v in paired if v["zh"] == v["en"])),
    ]
    ok = True
    for label, quoted, got in checks:
        flag = "" if quoted is None else ("  ✓" if quoted == got else f"  ✗ 引用 {quoted}")
        if quoted is not None and quoted != got:
            ok = False
        P(f"  {label:<42}{got:>7}{flag}")

    # ── 4. §3.6 第二种退化模式（重复工具调用）的统一口径 ──────────────────
    # 第六轮复核指出正文把这一组的分子与分母混用了（英文臂与等长臂都写成
    # 「6 of 1,080」，而 6/1080 = 0.56% 与所标的 1.11% 矛盾）。现与
    # degeneration_modes.py 同源重算，三臂一律以 1,080 为分母。
    P("\n── 4. §3.6 重复工具调用 ≥3（qwen3.8-flash，两用户臂合并，每臂 1080）──")
    import degeneration_modes as dm  # noqa: E402

    main_rows = dm.load("e2_main24", "en")
    envzh = [r for r in dm.load("ez2_envzh", None) if r["env"] == "zh"]
    lenmatch = dm.load("ez2_lenmatch", None)
    arms = {"主矩阵(全部智能体)": main_rows,
            "英文环境": [r for r in main_rows if r["agent"] == "qwen3.8-flash"
                         and r["env"] == "en"],
            "中文环境": [r for r in envzh if r["agent"] == "qwen3.8-flash"],
            "等长中文": [r for r in lenmatch if r["agent"] == "qwen3.8-flash"]}
    extra = [
        ("§3.6 主矩阵 重复 ≥3（4,320）", 17, sum(r["rep"] for r in main_rows)),
        ("§3.6 英文环境 重复 ≥3（1,080）", 12,
         sum(r["rep"] for r in arms["英文环境"])),
        ("§3.6 中文环境 重复 ≥3（1,080）", 28,
         sum(r["rep"] for r in arms["中文环境"])),
        ("§3.6 等长中文 重复 ≥3（1,080）", 13,
         sum(r["rep"] for r in arms["等长中文"])),
        ("§3.6 三臂合并：同时崩塌+重复", 0,
         sum(r["col"] and r["rep"] for rs in arms.values() for r in rs)),
    ]
    for label, quoted, got in extra:
        flag = "  ✓" if quoted == got else f"  ✗ 引用 {quoted}"
        if quoted != got:
            ok = False
        P(f"  {label:<42}{got:>7}{flag}")

    for name, rs in arms.items():
        n_ = len(rs)
        P(f"    {name:<22}{n_:>6} 集｜重复 {sum(r['rep'] for r in rs):>3}"
          f"｜崩塌 {sum(r['col'] for r in rs):>3}")
    P(f"\n  {'全部引用一致。' if ok else '**存在不一致，见上表 ✗**'}")

    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    P(f"\n  已写 {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
