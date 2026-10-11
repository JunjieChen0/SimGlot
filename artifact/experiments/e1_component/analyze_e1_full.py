#!/usr/bin/env python3
"""E1 正式分析：三个单组件中文臂的**独立效应**，含任务聚类区间。

**主推断**：每个单组件臂 vs `env=en`（v1.0 主矩阵，逐格配对）的**崩塌率差**，
按**任务聚类**给 95% 区间，参照分布 `t(G-1 = 29)`（口径同 v1.0 的 `critval.py`）。

**为什么必须配对**：单组件臂与对照共用同一批 (任务, 模拟器, 用户语言, 重复)，
故只能用配对差；不配对会把任务间的巨大异质性算进方差，区间会宽到什么都说不出来。

**次要输出**：成功率差（E1 臂的分数取自 v2 的 `summary.json`——那里的 harness 评分器
已带 v1.0 的 try/finally 修补；对照取自 v1.0 `frozen_table.csv` 的**修正后**列
`reward_full`，**不是**归档列）。

用法：cd sqj && python3 swe/analyze_e1_full.py
产出：results/e1_full_analysis.txt
"""

from __future__ import annotations

import csv
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

from analyze_pilots import degeneracy, wilson  # noqa: E402

ARMS = ("zh_p", "zh_t", "zh_e", "zh", "zhp")
T_CRIT = 2.0452           # t(29) 双尾 95%，G=30 任务（同 v1.0 critval）
LINES: list[str] = []


def P(s: str = "") -> None:
    LINES.append(s)
    print(s)


def load_dir(root: Path) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(root / "*" / "summary.json"))):
        s = json.loads(Path(f).read_text(encoding="utf-8"))
        sp = s.get("spec") or {}
        tp = Path(f.replace("summary.json", "transcript.json"))
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        _, col = degeneracy(tr.get("agent_trace", []))
        rows.append({
            "key": (sp.get("task_id"), sp.get("user_model"), sp.get("user_lang"),
                    sp.get("rep", 0)),
            "task": sp.get("task_id"), "elang": sp.get("env_lang") or "en",
            "collapse": int(col), "err": bool(s.get("error")),
            "reward": float(s.get("reward") or 0.0),
        })
    return rows


def load_frozen(agent: str) -> list[dict]:
    """v1.0 主矩阵（env=en）对照：**修正后**的崩塌与分数列（`frozen_table.csv`）。"""
    rows = []
    for r in csv.DictReader((SIMGLOT / "results" / "frozen_table.csv").open(encoding="utf-8")):
        if r["agent"] != agent:
            continue
        rows.append({
            "key": (int(r["task_id"]), r["sim"], r["user_lang"], int(r["seed"])),
            "task": int(r["task_id"]), "collapse": int(r["collapse"]),
            "reward": float(r["reward_full"]), "reward_ok": True,
        })
    return rows


def load_corrected(kind: str) -> list[dict]:
    """`env=zh` / `env=zhp` 臂：分数取自 `score_envzh_corrected.py` 的 db_replay 重建结果。"""
    tag = "ez2_envzh" if kind == "zh" else "ez2_lenmatch"
    csvp = SQJ / "results" / ("envzh_corrected.csv" if kind == "zh" else "envzhp_corrected.csv")
    if not csvp.exists():
        raise FileNotFoundError(f"缺 {csvp}；请先跑 swe/score_envzh_corrected.py")
    rows = []
    for r in csv.DictReader(csvp.open(encoding="utf-8")):
        f = SIMGLOT / "runs" / tag / r["cell_id"] / "transcript.json"
        tr = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        _, col = degeneracy(tr.get("agent_trace", []))
        rows.append({
            "key": (int(r["task_id"]), r["sim"], r["user_lang"], int(r["rep"])),
            "task": int(r["task_id"]), "collapse": int(col),
            "reward": float(r["reward_corrected"]), "reward_ok": True,
        })
    return rows


def load_envzh_corrected() -> list[dict]:
    """`env=zh` 臂：**修正后**的分数来自 `score_envzh_corrected.py`（db_replay 重建 DB 分量）。

    崩塌同样按判据现算（轨迹级、与评分器无关）。
    """
    rows = []
    csvp = SQJ / "results" / "envzh_corrected.csv"
    if not csvp.exists():
        raise FileNotFoundError(f"缺 {csvp}；请先跑 swe/score_envzh_corrected.py")
    for r in csv.DictReader(csvp.open(encoding="utf-8")):
        f = SIMGLOT / "runs" / "ez2_envzh" / r["cell_id"] / "transcript.json"
        tr = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        _, col = degeneracy(tr.get("agent_trace", []))
        rows.append({
            "key": (int(r["task_id"]), r["sim"], r["user_lang"], int(r["rep"])),
            "task": int(r["task_id"]), "collapse": int(col),
            "reward": float(r["reward_corrected"]), "reward_ok": True,
        })
    return rows


def load_archived(agent: str, tag: str) -> list[dict]:
    """v1.0 的 2×2 批次（`ez2_envzh`）：**不**在 `frozen_table.csv` 里（那张表只含主矩阵）。

    崩塌从官方转录按同一判据现算（轨迹级，与评分器无关，可直接比）；
    **分数留空**——该批次的修正标签需要 `db_replay` 重建，本分析不做，如实标注。
    """
    rows = []
    for f in sorted(glob.glob(str(SIMGLOT / "runs" / tag / "*" / "summary.json"))):
        s = json.loads(Path(f).read_text(encoding="utf-8"))
        sp = s.get("spec") or {}
        if sp.get("agent_model") != agent:
            continue
        tp = Path(f.replace("summary.json", "transcript.json"))
        tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        _, col = degeneracy(tr.get("agent_trace", []))
        rows.append({
            "key": (sp.get("task_id"), sp.get("user_model"), sp.get("user_lang"),
                    sp.get("seed", 0)),
            "task": sp.get("task_id"), "collapse": int(col),
            "reward": float("nan"), "reward_ok": False,
        })
    return rows


def clustered(deltas_by_task: dict) -> tuple[float, float, float, int]:
    """任务聚类的点估计与 95% 区间。返回 (mean, lo, hi, G)。"""
    g = [sum(v) / len(v) for v in deltas_by_task.values() if v]
    n = len(g)
    if n < 2:
        return (float("nan"), float("nan"), float("nan"), n)
    mean = sum(g) / n
    var = sum((x - mean) ** 2 for x in g) / (n - 1)
    se = math.sqrt(var / n)
    h = T_CRIT * se
    return (mean, mean - h, mean + h, n)


def paired_vs_base(arm_rows: list[dict], base_rows: list[dict], field: str):
    """逐格配对（同一 key）后按任务聚合。"""
    b = {r["key"]: r[field] for r in base_rows}
    by_task: dict[int, list[float]] = defaultdict(list)
    n_pair = 0
    for r in arm_rows:
        if r["key"] in b:
            d = float(r[field]) - float(b[r["key"]])
            if d == d:                      # 跳过 NaN
                by_task[r["task"]].append(d)
                n_pair += 1
    return by_task, n_pair


def main() -> int:
    P("=" * 96)
    P("E1 正式分析 · 环境本地化的组件级消融（retail，30 任务 × 6 模拟器 × 2 用户语言 × 3 重复）")
    P("=" * 96)
    P(f"主推断口径：逐格配对差 → 任务聚类 95% 区间，参照 t(G−1={T_CRIT/2.0452*29:.0f}) ≈ t(29)={T_CRIT}")

    arm_rows = {a: load_dir(SQJ / "runs" / "e1_ablation_full") for a in ()} or {}
    all_new = load_dir(SQJ / "runs" / "e1_ablation_full")
    for a in ARMS:
        arm_rows[a] = [r for r in all_new if r["elang"] == a]
    P(f"\nE1 各臂格数：" + "｜".join(f"{a}={len(arm_rows[a])}" for a in ARMS)
      + f"｜失败格 {sum(1 for r in all_new if r['err'])}"
      + "（已补跑的格会体现在格数上）")

    base_en = load_frozen("qwen3.8-flash")
    base_zh = load_corrected("zh")
    arm_rows["zh"] = base_zh
    arm_rows["zhp"] = load_corrected("zhp")
    P(f"对照（v1.0 归档）：env=en {len(base_en)} 格（frozen_table 修正口径）"
      f"｜env=zh {len(base_zh)} 格（崩塌现算；分数经 `db_replay` 重建修正，见 score_envzh_corrected.py）")

    P("")
    P("── 1. 崩塌率（轨迹级，与评分器无关） ──")
    P(f"  {'臂':<8}{'崩塌率':>18}{'n':>7}   说明")
    desc = {"en": "全英文基线（v1.0 主矩阵）", "zh_p": "仅政策 wiki 中文",
            "zh_t": "仅工具说明中文", "zh_e": "仅错误串中文",
            "zh": "全中文（v1.0 的 2×2 臂）", "zhp": "全中文+长度配平（长度对照）"}
    for a, rows in (("en", base_en), ("zh_p", arm_rows["zh_p"]), ("zh_t", arm_rows["zh_t"]),
                    ("zh_e", arm_rows["zh_e"]), ("zh", arm_rows["zh"]), ("zhp", arm_rows["zhp"])):
        k = sum(r["collapse"] for r in rows); n = len(rows)
        lo, hi = wilson(k, n)
        P(f"  {a:<8}{100*k/n:>11.2f}% ({k:>3}/{n:<4}){n:>7}   {desc[a]}")

    P("")
    P("── 2. 相对 env=en 的崩塌率差（**主推断**：逐格配对 → 任务聚类） ──")
    P("     （点估计单位为 pp；区间为任务聚类 95%，跨零 = 该组件的独立效应未检测到）")
    for a in ("zh_p", "zh_t", "zh_e", "zh", "zhp"):
        rows = arm_rows[a] if a != "zh" else base_zh
        bt, n_pair = paired_vs_base(rows, base_en, "collapse")
        m, lo, hi, G = clustered(bt)
        lo_p, hi_p = 100 * lo, 100 * hi
        flag = "跨零" if lo_p <= 0 <= hi_p else "**不跨零**"
        se = (hi - m) / T_CRIT
        P(f"  {a:<6} Δ = {100*m:+6.2f} pp   95%CI [{lo_p:+6.2f}, {hi_p:+6.2f}]  "
          f"SE={100*se:.2f}  G={G} 配对={n_pair}  {flag}")

    P("")
    P("── 3. 组件之间的比较（同一批配对格，直接相减） ──")
    P("     ⚠ 这是**探索性**的：预注册没有为组件两两之差设假设，故只报点估计与区间，不作显著性宣称。")
    kg = lambda rows: {r["key"]: r["collapse"] for r in rows}
    # 含与全中文臂的对比：这是「单组件是否达到完整处理」的可检验形式
    for x, y in (("zh_t", "zh_e"), ("zh_t", "zh_p"), ("zh_p", "zh_e"),
                 ("zh_t", "zh"), ("zh_p", "zh"), ("zh_e", "zh"), ("zhp", "zh")):
        kx, ky = kg(arm_rows[x]), kg(arm_rows[y])
        by_task: dict[int, list[float]] = defaultdict(list)
        for r in arm_rows[x]:
            if r["key"] in ky:
                by_task[r["task"]].append(float(kx[r["key"]]) - float(ky[r["key"]]))
        m, lo, hi, G = clustered(by_task)
        P(f"  {x} − {y}: Δ = {100*m:+6.2f} pp  95%CI [{100*lo:+6.2f}, {100*hi:+6.2f}]  G={G}")

    P("")
    P("── 4. 成功率（次要输出；E1 臂用 v2 修正口径，对照用 frozen_table 的修正列） ──")
    for a in ("zh_p", "zh_t", "zh_e", "zh", "zhp"):
        rows = arm_rows[a] if a != "zh" else base_zh
        bt, n_pair = paired_vs_base(rows, base_en, "reward")
        m, lo, hi, G = clustered(bt)
        P(f"  {a:<6} Δ = {100*m:+6.2f} pp   95%CI [{100*lo:+6.2f}, {100*hi:+6.2f}]  "
          f"G={G} 配对={n_pair}  {'跨零' if lo <= 0 <= hi else '**不跨零**'}")

    out = SQJ / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "e1_full_analysis.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    P(f"\n已写 {out/'e1_full_analysis.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
