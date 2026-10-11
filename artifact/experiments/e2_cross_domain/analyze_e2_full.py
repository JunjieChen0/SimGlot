#!/usr/bin/env python3
"""E2 分析：跨任务域的**用户语言效应**检验（RQ3 核心）。

预注册（S2 补充 A3）**预先写死**的读数规则：
  * 若 airline 的 Δ(zh − en) 与 v1.0 retail **同号** ⇒ 报告为跨域复现；
  * 若**反号** ⇒ 报告为**适用范围边界**，并把 v1.0 的效应限定为「retail 配置下的语言效应」；
  * **两种结果都写入论文。**

主推断口径同 E1：逐格配对（同任务、同模拟器、同重复、只换用户语言）→ 任务聚类 95% 区间，
参照 t(G−1 = 49)（airline 50 条任务 ⇒ G=50）。
**同时报告崩塌基线的绝对水平**——这是 v1.0「检测依赖任务集」那条局限的直接答案。

用法：cd sqj && python3 swe/analyze_e2_full.py
产出：results/e2_full_analysis.txt
"""

from __future__ import annotations

import glob
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQJ = HERE.parent
SIMGLOT = SQJ.parent / "simglot"
sys.path.insert(0, str(HERE))

import csv  # noqa: E402
from analyze_pilots import degeneracy, wilson  # noqa: E402

SIMGLOT_RES = SIMGLOT / "results" / "frozen_table.csv"

LINES: list[str] = []
T50 = 2.0096          # t(49) 双尾 95%


def P(s: str = "") -> None:
    LINES.append(s)
    print(s)


def load(tag: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(SQJ / "runs" / tag / "*" / "summary.json"))):
        s = json.loads(Path(f).read_text(encoding="utf-8"))
        sp = s.get("spec") or {}
        if s.get("error"):
            continue
        tp = Path(f.replace("summary.json", "transcript.json"))
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        _, col = degeneracy(tr.get("agent_trace", []))
        rows.append({
            "key": (sp.get("task_id"), sp.get("user_model"), sp.get("rep", 0)),
            "task": sp.get("task_id"), "ulang": sp.get("user_lang"),
            "sim": sp.get("user_model"), "collapse": int(col),
            "reward": float(s.get("reward") or 0.0),
        })
    return rows


def retail_user_lang_effect() -> tuple[float, float, int, int]:
    """retail 域的用户语言效应，用**同一套步骤**算（配对 → 任务聚类）。

    数据取自 v1.0 主矩阵的冻结表（**修正后**的崩塌列；该表全部为 env=en）。
    v1.0 曾报 +6.67 pp，本函数应复现同一量级。
    """
    rows = [r for r in csv.DictReader(SIMGLOT_RES.open(encoding="utf-8"))
            if r["agent"] == "qwen3.8-flash"]
    for r in rows:
        r["collapse"] = int(r["collapse"])
        r["key"] = (int(r["task_id"]), r["sim"], int(r["seed"]))
    en = {r["key"]: r for r in rows if r["user_lang"] == "en"}
    zh = {r["key"]: r for r in rows if r["user_lang"] == "zh"}
    by_task: dict[int, list[float]] = defaultdict(list)
    for k, r in zh.items():
        if k in en:
            by_task[r["task_id"]].append(float(r["collapse"]) - float(en[k]["collapse"]))
    g = [sum(v) / len(v) for v in by_task.values() if v]
    n = len(g)
    mean = sum(g) / n
    var = sum((x - mean) ** 2 for x in g) / (n - 1)
    se = math.sqrt(var / n)
    return (mean, se, n, sum(len(v) for v in by_task.values()))


def clustered(by_task: dict) -> tuple[float, float, float, int]:
    g = [sum(v) / len(v) for v in by_task.values() if v]
    n = len(g)
    if n < 2:
        return (float("nan"),) * 3 + (n,)
    mean = sum(g) / n
    var = sum((x - mean) ** 2 for x in g) / (n - 1)
    h = T50 * math.sqrt(var / n)
    return (mean, mean - h, mean + h, n)


def main() -> int:
    P("=" * 96)
    P("E2 分析 · 跨任务域检验（τ-bench airline，50 任务 × 6 模拟器 × 2 用户语言 × 2 重复）")
    P("=" * 96)
    P(f"主推断：逐格配对 → 任务聚类 95% 区间，参照 t(49) = {T50}")

    rows = load("e2_airline_full")
    P(f"\n可用格：{len(rows)}（已剔除失败格）｜任务 {len({r['task'] for r in rows})} 条"
      f"｜模拟器 {len({r['sim'] for r in rows})}")

    for lang in ("en", "zh"):
        sub = [r for r in rows if r["ulang"] == lang]
        k = sum(r["collapse"] for r in sub)
        lo, hi = wilson(k, len(sub))
        P(f"  用户 {lang}: 崩塌 {k}/{len(sub)} = {100*k/len(sub):.2f}%  [{100*lo:.1f}, {100*hi:.1f}]"
          f"｜成功率 {sum(1 for r in sub if r['reward']==1.0)}/{len(sub)}"
          f" = {100*sum(1 for r in sub if r['reward']==1.0)/len(sub):.1f}%")

    # ── 主推断：用户语言效应（配对） ───────────────────────────────────────────
    for field, label in (("collapse", "崩塌率"), ("reward", "成功率")):
        by_key = {r["key"]: r for r in rows if r["ulang"] == "zh"}
        en_by_key = {r["key"]: r for r in rows if r["ulang"] == "en"}
        by_task: dict[int, list[float]] = defaultdict(list)
        for k, r in by_key.items():
            if k in en_by_key:
                by_task[r["task"]].append(float(r[field]) - float(en_by_key[k][field]))
        m, lo, hi, G = clustered(by_task)
        n_pair = sum(len(v) for v in by_task.values())
        P(f"\n  **{label}的用户语言效应 Δ(zh − en)**：{100*m:+.2f} pp  "
          f"95%CI [{100*lo:+.2f}, {100*hi:+.2f}]  G={G} 配对={n_pair}  "
          f"{'跨零' if lo <= 0 <= hi else '**不跨零**'}")

    # ── 跨域**直接**对比（评审 P1：只分别报两个域的区间不够） ──────────────────
    P("")
    P("── 跨域直接对比：airline 效应 − retail 效应 ──")
    air_by_task: dict[int, list[float]] = defaultdict(list)
    zh_rows = {r["key"]: r for r in rows if r["ulang"] == "zh"}
    en_rows = {r["key"]: r for r in rows if r["ulang"] == "en"}
    for k, r in zh_rows.items():
        if k in en_rows:
            air_by_task[r["task"]].append(float(r["collapse"]) - float(en_rows[k]["collapse"]))
    a_mean, a_lo, a_hi, a_G = clustered(air_by_task)
    a_se = (a_hi - a_mean) / T50
    r_mean, r_se, r_G, r_n = retail_user_lang_effect()
    diff = a_mean - r_mean
    se_d = math.sqrt(a_se ** 2 + r_se ** 2)
    # Welch–Satterthwaite 自由度（两个域的样本量与方差都不同）
    df = (a_se ** 2 + r_se ** 2) ** 2 / (
        (a_se ** 2) ** 2 / (a_G - 1) + (r_se ** 2) ** 2 / (r_G - 1))
    # **精确** Welch–Satterthwaite 分位数：不再用「df 落在 29~49 之间就取 2.0452」的分段近似
    # （独立复核方指出该近似；它不会翻掉远非零的差异，但正式稿应按实际自由度取值）。
    from scipy import stats as _st
    t_crit = float(_st.t.ppf(0.975, df))
    h = t_crit * se_d
    P(f"  airline（G={a_G}，{sum(len(v) for v in air_by_task.values())} 配对）："
      f"{100*a_mean:+.2f} pp，SE {100*a_se:.2f}")
    P(f"  retail （G={r_G}，{r_n} 配对）：{100*r_mean:+.2f} pp，SE {100*r_se:.2f}")
    P(f"  **差值（airline − retail）= {100*diff:+.2f} pp，95%CI "
      f"[{100*(diff-h):+.2f}, {100*(diff+h):+.2f}]，Welch df={df:.2f}，"
      f"t(0.975, df)={t_crit:.4f}（scipy 精确分位数）**")
    P(f"  ⇒ {'不跨零：两域效应可分辨' if (diff-h) * (diff+h) > 0 else '跨零：两域效应之差异未检测到'}")

    P("")
    P("── 按预注册（S2 补充 A3）的读数规则 ──")
    P("  airline 的 Δ 为**负号**而 retail 为**正号** ⇒ **跨域符号相反** ⇒ 报为**适用范围边界**，")
    P("    把 v1.0 的效应限定为「**retail 配置下的语言效应**」，不得称其为普遍的语言效应。")

    P("")
    P("── 崩塌基线的绝对水平（v1.0「检测依赖任务集」这条局限的直接答案） ──")
    P("  v1.0 曾报告：崩塌只在 4 个智能体中的 1 个（`qwen3.8-flash`）上可检出，其余三个两臂 0%。")
    for lang in ("en", "zh"):
        sub = [r for r in rows if r["ulang"] == lang]
        k = sum(r["collapse"] for r in sub)
        P(f"  airline · 用户 {lang}：`qwen3.8-flash` 基线 {100*k/len(sub):.2f}%（{k}/{len(sub)}）")

    out = SQJ / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "e2_full_analysis.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    P(f"\n已写 {out/'e2_full_analysis.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
