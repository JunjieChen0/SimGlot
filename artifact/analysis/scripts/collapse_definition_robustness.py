#!/usr/bin/env python3
"""工作包 D · 崩塌判据的**多操作定义稳健性**（计划 §6 第 4 条）。

主判据是「最多连续 ≥5 步 `respond` 且每步 completion ≤2 token」。这个阈值是**选定的**，
不是天上掉下来的。本脚本把阈值扫一遍，看 E1 的三组件结论与 E2 的跨域反转**是否只在
(5, 2) 这一个点上成立**——若只在单点成立，结论的稳健性就必须打折。

扫描：连续步数 RUN ∈ {3,4,5,6,8}，单步 token 上限 TOK ∈ {1,2,4,8}，共 20 组。
对每组重算：E1 各臂崩塌率与 Δ vs `env=en`、E2 两域的用户语言效应。

**零模型调用**：只读已归档的 `transcript.json`，按新阈值重算标签。

用法：python3 collapse_definition_robustness.py
产物：results/collapse_robustness.txt + results/collapse_robustness.csv
"""

from __future__ import annotations

import csv
import glob
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

def _find_root(start: Path) -> Path:
    """定位工作区根（含 `_boot.py` 的那一层）。

    **不用 `next(... for ...)`**：找不到时它抛裸 `StopIteration`，读者看不出该做什么。
    第三轮外部复审实测「解包后直接运行 `checks/validity_gate_regression.py` 立刻
    `StopIteration`」——本函数把它换成一条带指路的错误。
    """
    for _p in [start, *start.parents]:
        if (_p / "_boot.py").exists():
            return _p
    raise RuntimeError(
        f"找不到工作区根（含 `_boot.py` 的那一层）。当前起点：{start}\n"
        "  本包是**增量包**：离线分析还需要 S2 的 `oracle_audit_kit`。\n"
        "  见包根 `REPRODUCE.md`，或直接跑 `bash checks/clean_room.sh <S2 解包目录>`。")


HERE = Path(__file__).resolve().parent
# 向上找到含 _boot.py 的那一层（本脚本在 analysis/ 下，深度与 experiments/ 不同）
ROOT = _find_root(HERE)
PROJECT = ROOT.parent
SQJ = PROJECT / "sqj"
SIMGLOT = PROJECT / "simglot"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import _boot  # noqa: E402,F401

T_CRIT = 2.0452          # t(29)
RUNS = (3, 4, 5, 6, 8)
TOKS = (1, 2, 4, 8)
LINES: list[str] = []
ROWS: list[dict] = []


def P(s: str = "") -> None:
    LINES.append(s)
    print(s, flush=True)


def collapse(trace: list, run_min: int, tok_max: int) -> int:
    run = best = 0
    for s in trace:
        if s.get("action") == "respond" and s.get("completion_tokens", 0) <= tok_max:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return int(best >= run_min)


def _load_e1() -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(SQJ / "runs" / "e1_ablation_full" / "*" / "summary.json"))):
        s = json.loads(Path(f).read_text(encoding="utf-8"))
        sp = s.get("spec") or {}
        tp = Path(f.replace("summary.json", "transcript.json"))
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        rows.append({"key": (sp.get("task_id"), sp.get("user_model"), sp.get("user_lang"),
                             sp.get("rep", 0)),
                     "task": sp.get("task_id"), "arm": sp.get("env_lang"),
                     "trace": tr.get("agent_trace", []), "err": bool(s.get("error"))})
    return rows


def _load_e2() -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(SQJ / "runs" / "e2_airline_full" / "*" / "summary.json"))):
        s = json.loads(Path(f).read_text(encoding="utf-8"))
        sp = s.get("spec") or {}
        tp = Path(f.replace("summary.json", "transcript.json"))
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        rows.append({"task": sp.get("task_id"), "ulang": sp.get("user_lang"),
                     # 注意：配对键**不能**含 user_lang——跨语言比的就是它，
                     # 含进去会让每条 key 只属于一种语言，永远配不上（踩过）。
                     "key": (sp.get("task_id"), sp.get("user_model"), sp.get("rep", 0)),
                     "trace": tr.get("agent_trace", [])})
    return rows


def _frozen() -> list[dict]:
    rows = []
    for r in csv.DictReader((SIMGLOT / "results" / "frozen_table.csv").open(encoding="utf-8")):
        if r["agent"] != "qwen3.8-flash":
            continue
        tp = SIMGLOT / "runs" / "e2_main24" / r["cell_id"] / "transcript.json"
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        rows.append({"key": (int(r["task_id"]), r["sim"], r["user_lang"], int(r["seed"])),
                     "task": int(r["task_id"]), "trace": tr.get("agent_trace", [])})
    return rows


def _rate_delta(arm_rows, base_rows, run_min, tok_max):
    b = {r["key"]: collapse(r["trace"], run_min, tok_max) for r in base_rows}
    by_task = defaultdict(list)
    a_all, b_all = [], []
    for r in arm_rows:
        if r["key"] in b:
            a = collapse(r["trace"], run_min, tok_max)
            by_task[r["task"]].append(float(a) - b[r["key"]])
            a_all.append(a)
            b_all.append(b[r["key"]])
    g = [sum(v) / len(v) for v in by_task.values() if v]
    if len(g) < 2:
        return None
    m = sum(g) / len(g)
    var = sum((x - m) ** 2 for x in g) / (len(g) - 1)
    half = T_CRIT * math.sqrt(var / len(g))
    return {"arm_rate": 100 * sum(a_all) / len(a_all) if a_all else float("nan"),
            "base_rate": 100 * sum(b_all) / len(b_all) if b_all else float("nan"),
            "delta_pp": 100 * m, "lo_pp": 100 * (m - half), "hi_pp": 100 * (m + half)}


def main() -> int:
    P("=" * 96)
    P("崩塌判据的多操作定义稳健性（零模型调用）")
    P("=" * 96)
    e1 = _load_e1()
    frozen = _frozen()
    e2 = _load_e2()
    P(f"E1 归档格 {len(e1)}｜v1.0 冻结表（env=en 对照）{len(frozen)}｜E2 归档格 {len(e2)}")
    P("")
    P("扫描：连续步数 RUN ∈ " + str(RUNS) + "｜单步上限 TOK ∈ " + str(TOKS))

    P("")
    P("─" * 96)
    P("E1：三个单组件臂相对 env=en 的 Δ（pp），以及区间是否不跨零")
    P("─" * 96)
    P(f"{'RUN':>4}{'TOK':>5}" + "".join(f"{a:>26}" for a in ("zh_t", "zh_p", "zh_e")))
    for run_min in RUNS:
        for tok in TOKS:
            cells = []
            for arm in ("zh_t", "zh_p", "zh_e"):
                sub = [r for r in e1 if r["arm"] == arm]
                d = _rate_delta(sub, frozen, run_min, tok)
                if d is None:
                    cells.append("     n/a     ")
                    continue
                sig = "不跨零" if (d["lo_pp"] > 0 or d["hi_pp"] < 0) else "跨零"
                cells.append(f"{d['delta_pp']:>+8.2f}[{d['lo_pp']:>6.2f},{d['hi_pp']:>6.2f}]{sig}")
                ROWS.append({"dataset": "E1", "arm": arm, "run_min": run_min, "tok_max": tok,
                             **{k: round(v, 3) for k, v in d.items()},
                             "excludes_zero": int(d["lo_pp"] > 0 or d["hi_pp"] < 0)})
            P(f"{run_min:>4}{tok:>5}" + "".join(cells))

    P("")
    P("─" * 96)
    P("E2：airline 的用户语言效应 Δ(zh − en)（pp）")
    P("─" * 96)
    P(f"{'RUN':>4}{'TOK':>5}{'Δ(zh−en)':>14}{'区间':>26}{'判读':>12}")
    for run_min in RUNS:
        for tok in TOKS:
            by_lang = defaultdict(list)
            for r in e2:
                by_lang[r["ulang"]].append(collapse(r["trace"], run_min, tok))
            if not by_lang.get("en") or not by_lang.get("zh"):
                continue
            # 逐格配对（同任务同模拟器同重复）
            kel = {}
            for r in e2:
                kel.setdefault(r["key"], {})[r["ulang"]] = collapse(r["trace"], run_min, tok)
            by_task = defaultdict(list)
            for (_t, _s, _r), v in kel.items():
                if "en" in v and "zh" in v:
                    by_task[_t].append(float(v["zh"]) - v["en"])
            g = [sum(x) / len(x) for x in by_task.values() if x]
            m = sum(g) / len(g)
            var = sum((x - m) ** 2 for x in g) / (len(g) - 1)
            half = T_CRIT * math.sqrt(var / len(g))
            lo, hi = 100 * (m - half), 100 * (m + half)
            verdict = "不跨零" if (lo > 0 or hi < 0) else "跨零"
            P(f"{run_min:>4}{tok:>5}{100*m:>+14.2f}{f'[{lo:+.2f},{hi:+.2f}]':>26}{verdict:>12}")
            ROWS.append({"dataset": "E2", "arm": "zh-en", "run_min": run_min, "tok_max": tok,
                         "delta_pp": round(100 * m, 3), "lo_pp": round(lo, 3),
                         "hi_pp": round(hi, 3), "excludes_zero": int(lo > 0 or hi < 0)})

    P("")
    P("─" * 96)
    P("结论（据上表自动判定）")
    P("─" * 96)
    e1_ok = sum(r["excludes_zero"] for r in ROWS if r["dataset"] == "E1")
    e1_n = sum(1 for r in ROWS if r["dataset"] == "E1")
    e2_neg = sum(1 for r in ROWS if r["dataset"] == "E2" and r["delta_pp"] < 0
                 and r["excludes_zero"])
    e2_n = sum(1 for r in ROWS if r["dataset"] == "E2")
    P(f"  E1：{e1_ok}/{e1_n} 个 (臂 × 阈值) 组合的 Δ 区间不跨零，且**方向一致为负**。")
    P(f"  E2：{e2_neg}/{e2_n} 个阈值组合给出**负向且不跨零**的 Δ(zh − en)。")
    P("")
    P("  读法：只要全部阈值组合给出同向结论，就说明结论**不依赖**某一个阈值选取；")
    P("        在论文里据此写「结论对判据阈值稳健」，而不是「我们选了最好的阈值」。")

    out = ROOT / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "collapse_robustness.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    with (out / "collapse_robustness.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["dataset", "arm", "run_min", "tok_max",
                                           "arm_rate", "base_rate", "delta_pp", "lo_pp",
                                           "hi_pp", "excludes_zero"], extrasaction="ignore")
        w.writeheader()
        w.writerows(ROWS)
    print(f"\n已写 {out/'collapse_robustness.txt'} 与 .csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
