#!/usr/bin/env python3
"""工作包 B3/B4 · 基线对照与检测器消融（只读 `results/b_matrix.csv`，零模型调用）。

**B3 基线**（计划要求回答「提案比当前已有测试增加什么」）：
  * 原框架随带的测试        —— τ-bench 不随带预言机测试，**记为无可比较项**（如实写）；
  * 仅重复评分一致性        —— 检测器子集 {INV-2}；
  * 仅状态不变量            —— {INV-1..INV-5}；
  * 仅已知答案控制          —— {CTL-1..CTL-3}；
  * 完整套件                —— 全部 8 个。
  各方法用**同一批**变体与任务，只比检出增益。

**B4 消融**：逐个移除一个检测器，报告移除后**丢失的独有检出**、**冗余检出**。

**注意**：本脚本**不**从集合计数推导运行时间——时间必须实际测量，见 `overhead.py`。

## 外部复审之后的改动

**第二轮（2026-10-10）**
1. **`_true_class` 不再有静默回退**。原实现 `from variants_ext import CATALOG` 在未启用
   项目导入引导的执行方式下抛异常，被宽泛的 `except Exception` 吞掉、退回 `return variant`，
   于是 B3b 把 `G1a_replay_in_place` 等**按具体变体**当成缺陷类列出，没有聚合到七类。
2. **分母分两套**。有效性是三态（`confirmed_differ` / `unresolved` /
   `confirmed_equivalent`）：主分母只含 `confirmed_differ`；保守分母把 `unresolved`
   也算作未检出。`unresolved` **不等于等价**——它只说明现有探针没分辨出来。

**第三轮（2026-10-10）**
3. **本脚本现在完全独立**：不再 `import _boot`，只读 `manifests/mutant_catalog.json`
   这张**冻结的**「名 → 缺陷类」表（由 `run_holdout.py` 生成）。
   之前那版为了拿这张表把整个 τ-bench 栈都引导起来，clean-room 里跑不动。
4. **B4 与 B3 的分母统一**。第三轮复审抓到：B4b 写的「覆盖 56/56」用的是
   `differ ∪ unresolved` 的报警集合，而 B3 主分母只有 `differ` 的 54——
   **两个总体被混在同一个分数里**。现在两者都显式给出、各自标清总体，并加断言。

用法：python3 analyze_b.py
产物：results/b_analysis.txt + results/b_baselines.csv + results/b_ablation.csv
"""

from __future__ import annotations

import csv
import json
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
ROOT = _find_root(HERE)
RESULTS = ROOT / "results"
LINES: list[str] = []

METHODS = {
    "原框架随带测试": None,                      # τ-bench 不随带预言机测试
    "仅重复评分一致 (INV-2)": ["INV-2"],
    "仅状态不变量 (INV-1..5)": ["INV-1", "INV-2", "INV-3", "INV-4", "INV-5"],
    "仅已知答案对照 (CTL-1..3)": ["CTL-1", "CTL-2", "CTL-3"],
    "完整套件 (8 项)": ["INV-1", "INV-2", "INV-3", "INV-4", "INV-5",
                        "CTL-1", "CTL-2", "CTL-3"],
}
ALL = METHODS["完整套件 (8 项)"]

#: 协议冻结的七个缺陷类。B3b 的聚合必须恰好落在这七类上。
EXPECTED_CLASSES = {"state_mutation", "exception_leak", "actions_not_restored",
                    "order_dependent", "saturated", "db_blind", "strict_format"}
EXPECTED_PER_CLASS = 3          # 7 类 × 3（1 开发 + 2 预留）= 21 个变体（不含 C0）

#: as-shipped 对照的名字（不是缺陷变体，只用来查特异性 0 报警）
REFERENCE_VARIANT = "C0 none (as-shipped)"


def _load_catalog() -> dict[str, str]:
    """读冻结的变体目录：变体名 → 缺陷类。**缺件或对不上就抛，不猜。**"""
    p = ROOT / "manifests" / "mutant_catalog.json"
    if not p.exists():
        raise FileNotFoundError(
            f"缺 {p}——它由 `run_holdout.py` 生成。没有它本脚本拒绝运行，"
            f"因为「凭空猜缺陷类」正是第二轮复审抓到的那个缺陷。")
    cat = json.loads(p.read_text(encoding="utf-8"))["variants"]
    per = defaultdict(int)
    for _n, meta in cat.items():
        per[meta["defect_class"]] += 1
    if set(per) != EXPECTED_CLASSES or set(per.values()) != {EXPECTED_PER_CLASS}:
        raise AssertionError(f"变体目录不是「七类 × {EXPECTED_PER_CLASS}」：{dict(per)}")
    return {n: meta["defect_class"] for n, meta in cat.items()}


#: 变体名 → 缺陷类（在模块导入期一次性建立；**失败即报错，不回退**）
CLASS_OF: dict[str, str] = _load_catalog()


def P(s: str = "") -> None:
    LINES.append(s)
    print(s, flush=True)


def _true_class(variant: str) -> str:
    """从变体名还原缺陷类。**绝不静默回退**（第二轮复审 B-3）。

    取不到就抛——把「按类别解释不可靠」变成「跑不出来」，而不是悄悄印出变体名充数。
    """
    if variant == REFERENCE_VARIANT:
        return "reference"          # C0 = as-shipped 对照，不是缺陷变体
    if variant in CLASS_OF:
        return CLASS_OF[variant]
    # 基础套件的名字形如 "C1 state_mutation"：**空格**之后才是缺陷类。
    # 用 split("_") 会切在 "state_mutation" 自己的下划线上（踩过）。
    if variant.startswith("C") and " " in variant:
        cls = variant.split(" ", 1)[1]
        if cls in EXPECTED_CLASSES:
            return cls
    raise KeyError(f"变体 {variant!r} 不在 manifests/mutant_catalog.json 里，"
                   f"且不像基础套件命名——拒绝猜测它的缺陷类")


def load_validity() -> dict[tuple[str, str], str]:
    """读 `b_validity.csv`，返回 {(target, variant): status}。

    三态（第二轮复审 B-2）：`confirmed_differ` / `unresolved` / `confirmed_equivalent`。
    旧的两态文件（无 `status` 列）会被明确拒绝，避免把过期口径当成新口径。
    """
    p = RESULTS / "b_validity.csv"
    if not p.exists():
        raise FileNotFoundError(f"缺 {p}；请先跑 analysis/rerun_validity.py")
    with p.open(encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        if "status" not in (rd.fieldnames or []):
            raise ValueError(f"{p} 没有 status 列——这是修补前的两态口径；"
                             f"请重跑 analysis/rerun_validity.py")
        return {(r["target"], r["variant"]): r["status"] for r in rd}


def load(keep: set) -> list[dict]:
    p = RESULTS / "b_matrix.csv"
    if not p.exists():
        raise FileNotFoundError(f"缺 {p}；请先跑 experiments/oracle_mutation_holdout/run_holdout.py")
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    return [r for r in rows
            if r["variant"] == "C0 none (as-shipped)" or (r["target"], r["variant"]) in keep]


def main() -> int:
    validity = load_validity()
    differ = {k for k, s in validity.items() if s == "confirmed_differ"}
    unresolved = {k for k, s in validity.items() if s == "unresolved"}
    equiv = {k for k, s in validity.items() if s == "confirmed_equivalent"}
    other = {k for k, s in validity.items() if s not in
             ("confirmed_differ", "unresolved", "confirmed_equivalent")}

    P("=" * 104)
    P("工作包 B3/B4 · 基线对照与检测器消融")
    P("=" * 104)
    P(f"有效性三态（`b_validity.csv`，第二轮复审后）：")
    P(f"  已分辨（confirmed_differ）{len(differ)}/63｜未定（unresolved）{len(unresolved)}｜"
      f"已证等价（confirmed_equivalent）{len(equiv)}｜其他 {len(other)}")
    P("  主分母 = 已分辨；保守分母 = 已分辨 + 未定（未定**不等于等价**，只是探针没分辨出来）。")
    if equiv:
        P(f"  ⚠ 本轮**没有任何一条**给出可说明的等价论证，却出现了 {len(equiv)} 条 confirmed_equivalent——请复核。")

    rows = load(differ | unresolved)
    fire: dict[tuple, set] = defaultdict(set)
    meta: dict[tuple, dict] = {}
    for r in rows:
        k = (r["target"], r["variant"])
        meta[k] = {"defect_class": _true_class(r["variant"]), "held_out": r["held_out"]}
        if r["ran"] == "1" and r["violated"] == "1":
            fire[k].add(r["detector"])

    variants = sorted(k for k in meta if k[1] != "C0 none (as-shipped)")
    targets = sorted({k[0] for k in variants})
    P(f"进入统计的变体 × 目标 = {len(variants)} 条｜目标 {targets}")

    # ── 类别完整性断言（复审 B-3 要求）────────────────────────────────────
    classes = sorted({meta[k]["defect_class"] for k in variants})
    if set(classes) != EXPECTED_CLASSES:
        extra, missing = set(classes) - EXPECTED_CLASSES, EXPECTED_CLASSES - set(classes)
        raise AssertionError(f"缺陷类不是约定的七类：多出 {sorted(extra)}、缺 {sorted(missing)}")

    #: **主分母总体**：B3 与 B4/B4b 必须用同一个总体。
    #: 第三轮复审抓到上一版把 `differ ∪ unresolved` 的报警集合拿去算 B4b 的 56/56，
    #: 而 B3 主分母只有 54——两个总体混在同一个分数里。下面所有段落一律用 primary。
    primary = [k for k in variants if k in differ]
    assert len(primary) == len(differ), "主分母总体与 confirmed_differ 集合不等"

    # ── B3 基线（主分母）────────────────────────────────────────────────────
    P("")
    P("─" * 104)
    P("B3 · 基线对照：各方法检出的**变体数 / 主分母**（分母 = 该目标已分辨的变体数）")
    P("─" * 104)
    base_rows = []
    hdr = f"{'目标':<22}{'主分母':>7}" + "".join(f"{m:>24}" for m in METHODS)
    P(hdr)
    for tname in targets:
        ks = [k for k in primary if k[0] == tname]
        cells = []
        for mname, subset in METHODS.items():
            if subset is None:
                cells.append(f"{'N/A（无可比项）':>24}")
                base_rows.append({"target": tname, "method": mname, "detected": "",
                                  "total": len(ks), "note": "框架不随带预言机测试"})
                continue
            hit = sum(1 for k in ks if fire[k] & set(subset))
            cells.append(f"{hit:>14}/{len(ks):<8}")
            base_rows.append({"target": tname, "method": mname, "detected": hit,
                              "total": len(ks), "note": ""})
        P(f"{tname:<22}{len(ks):>7}" + "".join(cells))

    # 跨表一致性断言（第三轮复审 §5 要求）
    _full = METHODS["完整套件 (8 项)"]
    per_target_hits = {t: sum(1 for k in primary if k[0] == t and fire[k] & set(_full))
                       for t in targets}
    n_detected_primary = len({k for k in primary if fire[k]})
    assert sum(per_target_hits.values()) == n_detected_primary, (
        f"B3 逐目标检出合计 {sum(per_target_hits.values())} ≠ 主分母总体检出 {n_detected_primary}")
    P(f"  ↳ 逐目标检出合计 {sum(per_target_hits.values())} = 主分母总体检出 "
      f"{n_detected_primary}（B4/B4b 用的就是这个总体）")

    # ── B3b 按缺陷类 ────────────────────────────────────────────────────────
    P("")
    P("B3b · 按缺陷类（**七类聚合**）：完整套件 vs 仅状态不变量 vs 仅对照")
    P("─" * 104)
    P(f"{'缺陷类':<24}{'n':>4}{'仅不变量':>12}{'仅对照':>12}{'完整套件':>12}{'预留命中':>10}")
    for cls in sorted(EXPECTED_CLASSES):
        ks = [k for k in primary if meta[k]["defect_class"] == cls]
        if not ks:
            continue
        inv = sum(1 for k in ks if fire[k] & set(METHODS["仅状态不变量 (INV-1..5)"]))
        ctl = sum(1 for k in ks if fire[k] & set(METHODS["仅已知答案对照 (CTL-1..3)"]))
        full = sum(1 for k in ks if fire[k])
        ho = [k for k in ks if meta[k]["held_out"] == "1"]
        ho_hit = sum(1 for k in ho if fire[k])
        P(f"{cls:<24}{len(ks):>4}{inv:>10}/{len(ks):<2}{ctl:>10}/{len(ks):<2}"
          f"{full:>10}/{len(ks):<2}{ho_hit:>8}/{len(ho)}")

    # ── 跨仪器核对：**未定但检测器报警**的变体（第三轮复审 §5 暴露的口径问题）──
    P("")
    P("─" * 104)
    P("B3c · 跨仪器核对：有效性探针**未定**、而矩阵检测器**报警**的变体")
    P("─" * 104)
    cross = sorted(k for k in variants if k in unresolved and fire[k])
    if not cross:
        P("  无：两个仪器在每一处都一致。")
    else:
        P(f"  共 {len(cross)} 条。**两个仪器不一致**，不得把它们当作已分辨（也不得当作等价）：")
        for k in cross:
            P(f"    · {k[0]} / {k[1]}（{meta[k]['defect_class']}）→ 报警检测器 {sorted(fire[k])}")
            P(f"        · 有效性探针在该目标上**没分辨出**与参考实现的差别（见 b_validity.csv 的 detail）")
        P("  ⇒ 论文口径：这些是**未定**；它们的检测器报警**计入**「保守分母」下的检出，")
        P("     但**不**计入主分母。两个数都要给，不能只给其中一个。")
        P(f"     全量已报警对象（主分母已检出 {n_detected_primary} + 上述 {len(cross)}）= "
          f"{n_detected_primary + len(cross)}；B4/B4b 用的是前者 {n_detected_primary}。")

    # ── B4 消融（**总体 = 主分母**，与 B3 同一批对象）─────────────────────
    P("")
    P("─" * 104)
    P("B4 · 检测器消融：总体 = **主分母**（已分辨的 57 条），逐个移除一个检测器")
    P("─" * 104)
    P(f"  总体：{len(primary)} 条（= B3 各目标主分母之和 "
      f"{sum(len([k for k in primary if k[0] == t]) for t in targets)}）")
    P(f"{'移除的检测器':<26}{'丢失的独有检出':>16}{'可被替代的检出':>16}")
    abl_rows = []
    for d in ALL:
        unique, redundant = [], []
        for k in primary:
            f = fire[k]
            if d not in f:
                continue
            (unique if len(f) == 1 else redundant).append(k)
        P(f"{d:<26}{len(unique):>16}{len(redundant):>16}")
        for k in unique:
            P(f"      · 独有：{k[0]} / {k[1]}")
        for k, role in [(k, "unique") for k in unique] + [(k, "redundant") for k in redundant]:
            abl_rows.append({"detector": d, "target": k[0], "variant": k[1],
                             "defect_class": meta[k]["defect_class"],
                             "held_out": meta[k]["held_out"], "role": role})

    # 最小可用子集
    P("")
    P("─" * 104)
    P("B4b · 最小可用子集（贪心覆盖**主分母中已检出**的变体）")
    P("─" * 104)
    detected = {k for k in primary if fire[k]}
    chosen: list[str] = []
    covered: set = set()
    while covered != detected:
        best, gain = None, 0
        for d in ALL:
            if d in chosen:
                continue
            g = len({k for k in detected - covered if d in fire[k]})
            if g > gain:
                best, gain = d, g
        if not best or gain == 0:
            break
        chosen.append(best)
        covered |= {k for k in detected if best in fire[k]}
        P(f"  + {best:<26}新增覆盖 {gain}（累计 {len(covered)}/{len(detected)}）")
    P(f"  ⇒ 最小可用子集（贪心）：{chosen}")
    P(f"     覆盖 {len(covered)}/{len(detected)} 个**主分母中已检出**的变体；"
      f"全部 8 项为 {len(ALL)} 项，去掉 {len(ALL)-len(chosen)} 项不改覆盖。")
    P("     ⚠ 贪心不是最优解；此处只给一个**够用的**子集，不声称最小。")
    P("     ⚠ 该子集的成立范围**只是**主分母（已分辨的变体），不是全部 63 条。")

    # ── 汇总（主分母 + 保守分母）──────────────────────────────────────────
    P("")
    P("─" * 104)
    P("汇总 · 主分母（已分辨）与保守分母（已分辨 + 未定）")
    P("─" * 104)
    for tname in targets:
        for label, keys in (("主分母", [k for k in variants if k[0] == tname and k in differ]),
                            ("保守分母", [k for k in variants if k[0] == tname])):
            dev = [k for k in keys if meta[k]["held_out"] == "0"]
            ho = [k for k in keys if meta[k]["held_out"] == "1"]
            dmiss = [k[1] for k in dev if not fire[k]]
            hmiss = [k[1] for k in ho if not fire[k]]
            P(f"  {tname:<22}{label:<8}开发 {len(dev)}（未检出 {len(dmiss)}）｜"
              f"预留 {len(ho)}（未检出 {len(hmiss)}）"
              + (f"｜预留未检出：{', '.join(hmiss)}" if hmiss else ""))

    P("")
    P("  总账（两套分母，**不得混用**）：")
    P(f"    主分母{len(primary)} 条（已分辨）｜检出 {n_detected_primary}｜"
      f"未检出 {len(primary) - n_detected_primary}")
    cons = primary + [k for k in variants if k in unresolved]
    n_cons = sum(1 for k in cons if fire[k])
    P(f"    保守分母{len(cons)} 条（已分辨 + 未定）｜检出 {n_cons}｜"
      f"未检出 {len(cons) - n_cons}")
    P(f"    ⚠ 「全量已报警」= {n_cons}，是**保守分母**下的口径；"
      f"B4/B4b 用的是主分母下的 {n_detected_primary}。两者不可互换。")

    P("")
    allmiss = sorted({k[1] for k in primary if not fire[k]})
    if allmiss:
        P(f"  在**任何**目标上都未被检出的**已分辨**变体：{', '.join(allmiss)}")
    else:
        P("  每个已分辨的变体至少在某个目标上被检出。")

    P("")
    P("  未定（unresolved）的变体——探针没分辨出来，**不等于等价**：")
    for k in sorted(unresolved):
        mark = "（该目标上检测器报警，见 B3c）" if fire[k] else ""
        P(f"      · {k[0]} / {k[1]}（{meta[k]['defect_class']}，"
          f"{'预留' if meta[k]['held_out'] == '1' else '开发'}）{mark}")

    P("")
    P("  注：运行时间**不**在此推导——见 `overhead.py` 的实测。")

    (RESULTS / "b_analysis.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    with (RESULTS / "b_baselines.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["target", "method", "detected", "total", "note"])
        w.writeheader(); w.writerows(base_rows)
    with (RESULTS / "b_ablation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["detector", "target", "variant", "defect_class",
                                           "held_out", "role"])
        w.writeheader(); w.writerows(abl_rows)
    print(f"\n已写 {RESULTS/'b_analysis.txt'} / b_baselines.csv / b_ablation.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
