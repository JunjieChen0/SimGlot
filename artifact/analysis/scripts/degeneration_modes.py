#!/usr/bin/env python3
"""退化的**模式账**：预注册崩塌判据漏掉了什么，服务端又拦掉了什么。

独立复核（P0）指出两件事，本脚本把它们量化并分开陈述：

  ① **终止后不再调用工具** 不是预注册崩塌判据的一部分。判据只说「存在长度 ≥5 的
     短回复段」，达到阈值之后是否恢复工具调用是另一个问题。故分列
     `Collapse`（预注册）与 `Terminal no-resumption`（附加指标）。

  ② 存在**第二种退化**：智能体反复发出**完全相同**的工具调用（名与参数逐字相同），
     每一轮回复都不短，故长度判据看不见它。长度配平臂里就有一格因此被服务端
     以 HTTP 400（`Repetitive tool calls detected`）中断，归档为一次失败。

本脚本只用既有 `agent_trace`，不调用任何模型。逐格给出：

  · col      —— 预注册崩塌（≥5 连 `respond` 且每步 ≤2 token）
  · nores    —— 达到阈值后不再出现工具调用（只在崩塌集内有定义）
  · rep      —— 最长连续「逐字相同工具调用」段长度 ≥3
  · rep_max  —— 该格的最长重复段长度分布
  · err      —— 该格是否以服务端错误终止（`stop_reason == 'error'`）

用法：python3 scripts/degeneration_modes.py
输出：results/degeneration_modes.txt
"""

from __future__ import annotations

import collections
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "degeneration_modes.txt"

RUN_NEED, TOK_MAX = 5, 2
REP_NEED = 3

BATCHES = [
    ("主矩阵（en 环境）", [("e2_main24", "en"), ("e2_main", "en")]),
    ("环境中文（ez2_envzh）", [("ez2_envzh", None)]),
    ("等长中文（ez2_lenmatch）", [("ez2_lenmatch", None)]),
]

L: list[str] = []


def p(s: str = "") -> None:
    L.append(s)


def collapse_threshold(trace: list[dict]) -> int | None:
    run = 0
    for i, st in enumerate(trace):
        if st.get("action") == "respond" and (st.get("completion_tokens") or 0) <= TOK_MAX:
            run += 1
            if run >= RUN_NEED:
                return i
        else:
            run = 0
    return None


def max_repeat_run(trace: list[dict]) -> int:
    """最长连续「同名同参数」工具调用段的长度（respond 步打断该段）。"""
    best = run = 0
    prev = None
    for st in trace:
        name = st.get("action")
        if not name or name == "respond":
            run, prev = 0, None
            continue
        key = (name, json.dumps(st.get("kwargs") or {}, sort_keys=True, default=str))
        run = run + 1 if key == prev else 1
        prev = key
        best = max(best, run)
    return best


def load(tag: str, env: str | None):
    rows = []
    for sp in sorted(glob.glob(str(ROOT / "runs" / tag / "*" / "summary.json"))):
        try:
            s = json.loads(Path(sp).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        spc = s.get("spec") or {}
        if env is not None and spc.get("env_lang", "en") != env:
            continue
        tp = Path(sp.replace("summary.json", "transcript.json"))
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        trace = tr.get("agent_trace", [])
        th = collapse_threshold(trace)
        rows.append({
            "cell": s.get("cell_id"),
            "agent": spc.get("agent_model"),
            "user": spc.get("user_lang"),
            "env": spc.get("env_lang", "en"),
            "col": th is not None,
            "nores": (th is not None and not any(
                st.get("action") not in ("respond", None) for st in trace[th + 1:])),
            "rep": max_repeat_run(trace) >= REP_NEED,
            "rep_max": max_repeat_run(trace),
            "err": s.get("stop_reason") == "error",
        })
    return rows


def main() -> int:
    p("=" * 84)
    p("退化的模式账：预注册判据漏掉的、以及服务端拦掉的")
    p("=" * 84)
    p()
    p(f"  预注册崩塌：连续 ≥{RUN_NEED} 个 `respond` 步且每步 completion_tokens ≤{TOK_MAX}")
    p(f"  重复工具调用：连续 ≥{REP_NEED} 次**逐字相同**的工具调用（名与参数都相同）")
    p()

    allrows = {}
    for label, tags in BATCHES:
        # 与 frozen_table.py 同口径：主矩阵以 e2_main24 为准，只有**在该批失败**的
        # cell_id 才用 e2_main 的补跑结果替换；e2_main 里其余目录不属于主矩阵。
        base = {r["cell"]: r for r in load(tags[0][0], tags[0][1])} if tags else {}
        for tag, env in tags[1:]:
            for r in load(tag, env):
                if base.get(r["cell"], {}).get("err"):
                    base[r["cell"]] = r
        rows = list(base.values())
        allrows[label] = rows
        if not rows:
            p(f"── {label}：无数据")
            continue
        n = len(rows)
        col = sum(r["col"] for r in rows)
        rep = sum(r["rep"] for r in rows)
        both = sum(r["col"] and r["rep"] for r in rows)
        err = sum(r["err"] for r in rows)
        nores = sum(r["nores"] for r in rows)
        p(f"── {label}（{n} 集）")
        p(f"     崩塌（预注册）      {col:>5}  {col / n:>7.2%}")
        p(f"     重复工具调用 ≥{REP_NEED}      {rep:>5}  {rep / n:>7.2%}")
        p(f"     两者都有            {both:>5}  {both / n:>7.2%}")
        p(f"     崩塌但无工具恢复    {nores:>5}")
        p(f"     以服务端错误终止    {err:>5}")
        p()

    # ── 主矩阵：逐智能体 × 臂 ──────────────────────────────────────────────
    rows = allrows["主矩阵（en 环境）"]
    p("── 主矩阵 · 逐智能体 × 用户语言 ──")
    p()
    p(f"  {'agent':<22}{'arm':<5}{'n':>5}{'崩塌':>7}{'重复≥3':>9}{'错':>5}")
    for ag in sorted({r["agent"] for r in rows}):
        for arm in ("en", "zh"):
            sub = [r for r in rows if r["agent"] == ag and r["user"] == arm]
            if not sub:
                continue
            p(f"  {ag:<22}{arm:<5}{len(sub):>5}{sum(r['col'] for r in sub):>7}"
              f"{sum(r['rep'] for r in sub):>9}{sum(r['err'] for r in sub):>5}")
        p()

    # ── 重复段长度分布（只列 ≥2 的格） ─────────────────────────────────────
    p("── 主矩阵 · 最长重复工具调用段的长度分布（只列 ≥2 的格） ──")
    dist = collections.Counter(r["rep_max"] for r in rows if r["rep_max"] >= 2)
    p("     " + "｜".join(f"{k}: {v}" for k, v in sorted(dist.items())))
    p()

    # ── 三种退化是否同向：逐模拟器 ────────────────────────────────────────
    p("── 主矩阵 · 重复工具调用段的语言差（只对 qwen3.8-flash，与崩塌同一对象）──")
    qf = [r for r in rows if r["agent"] == "qwen3.8-flash"]
    for arm in ("en", "zh"):
        sub = [r for r in qf if r["user"] == arm]
        reps = sum(r["rep"] for r in sub)
        p(f"   {arm}: {reps}/{len(sub)} = {reps / len(sub):.2%}｜最长段均值 "
          f"{sum(r['rep_max'] for r in sub) / len(sub):.2f}")
    p()

    # ── 2×2 四格（智能体固定为 qwen3.8-flash，环境语言为第二因子）──────────
    p("── 2×2 四格 · 崩塌与重复工具调用并列（智能体 qwen3.8-flash）──")
    p()
    p(f"  {'用户':<6}{'环境':<6}{'n':>6}{'崩塌':>8}{'崩塌率':>9}{'重复≥3':>9}{'重复率':>9}")
    for user, env, label in (("en", "en", "主矩阵"), ("zh", "en", "主矩阵"),
                             ("en", "zh", "ez2_envzh"), ("zh", "zh", "ez2_envzh"),
                             ("en", "zhp", "ez2_lenmatch"), ("zh", "zhp", "ez2_lenmatch")):
        src = (rows if label == "主矩阵"
               else allrows["环境中文（ez2_envzh）"] if label == "ez2_envzh"
               else allrows["等长中文（ez2_lenmatch）"])
        sub = [r for r in src if r["agent"] == "qwen3.8-flash"
               and r["user"] == user and r["env"] == env]
        if not sub:
            continue
        c, rp = sum(r["col"] for r in sub), sum(r["rep"] for r in sub)
        p(f"  {user:<6}{env:<6}{len(sub):>6}{c:>8}{c / len(sub):>9.2%}"
          f"{rp:>9}{rp / len(sub):>9.2%}")
    p()

    # ── 环境实验三臂：论文 §3.6 引用的统一口径（qwen3.8-flash，两用户臂合并）──
    # 独立复核（第六轮 P0）指出正文把这组数字的分母与分子混用了：
    # 英文环境写成 6/1080、等长臂也写成 6/1080，但 6/1080 = 0.56%，与正文标的
    # 1.11% 自相矛盾。三个臂一律按「该臂全部 1,080 集」计，逐格数由本块输出。
    p("── 环境实验 · 重复工具调用率（统一口径：qwen3.8-flash，两用户臂合并，每臂 1,080）──")
    p()
    p(f"  {'环境臂':<8}{'n':>6}{'重复≥3':>9}{'比例':>9}   {'崩塌':>6}{'崩塌率':>9}")
    for lab, src, env in (("英文", allrows["主矩阵（en 环境）"], "en"),
                          ("中文", allrows["环境中文（ez2_envzh）"], "zh"),
                          ("等长", allrows["等长中文（ez2_lenmatch）"], "zhp")):
        sub = [r for r in src if r["agent"] == "qwen3.8-flash" and r["env"] == env]
        if not sub:
            continue
        n, rp, c = len(sub), sum(r["rep"] for r in sub), sum(r["col"] for r in sub)
        p(f"  {lab:<8}{n:>6}{rp:>9}{rp / n:>9.2%}   {c:>6}{c / n:>9.2%}")
    p()

    # ── 互斥性：按三臂合并断言（论文写「0 of 4,320」，现给出全量口径）────────
    tot_n = tot_col = tot_rep = tot_both = 0
    for src in allrows.values():
        tot_n += len(src)
        tot_col += sum(r["col"] for r in src)
        tot_rep += sum(r["rep"] for r in src)
        tot_both += sum(r["col"] and r["rep"] for r in src)
    p(f"── 互斥性（三臂合并，{tot_n} 集）：崩塌 {tot_col}｜重复≥3 {tot_rep}"
      f"｜两者都有 {tot_both} ──")
    assert tot_both == 0, "崩塌与重复工具调用在本数据上应互不重叠"
    p()

    p("── 0. 读法 ──")
    p("  1. 预注册判据量的是「短回复连段」，重复工具调用**不在其中**；两者可以互不覆盖。")
    p("  2. 以 `stop_reason == 'error'` 终止的格，服务端在请求层就拒绝了继续对话，")
    p("     故其退化段在归档里**不完整**——任何退化率都是下界。")
    p("  3. 这两件事都必须写进论文的方法与限制，不能并入崩塌率一起报。")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
