#!/usr/bin/env python3
"""重算论文 Table 1 与「哪几个检查是承重的」——**从本仓库里的数据现算，不复述结论**。

输入（都在本仓库内）：
    results/summary/b_matrix.csv                                  逐 (目标, 变体, 检测器) 的报警记录
    results/summary/b_validity.csv                                有效性三态（已分辨 / 未定 / 已证等价）
    artifact/holdout/mutant_catalog.json                          变体名 → 缺陷类

输出（写到 results/summary/）：
    table1_variant_necessity.csv   逐缺陷类：变体数、报警的检查并集、留一必要项
    table1_summary.csv             主分母 / 保守分母 / 检出数 / 唯一漏检 / 逐检测器独有检出

## 为什么要有这个脚本

论文 §4.1 的那张表**曾经是手写的**，而手写的那版把 `INV-1` 标成了两个缺陷类的「必要检测器」。
按这里的留一法算，`INV-1` 的独有检出是 **0** —— 它一个缺陷类都不独有覆盖。那是独立复审
发现的、并且是本项目自己记录里早就写明的事。

所以这张表现在由脚本生成：谁都可以重跑，并把它和论文并排对照。
**若两者不一致，是论文错了，不是脚本错了。**

用法：python3 artifact/scripts/build_tables.py
退出码：0 = 算出；1 = 输入缺失或格式变了（**不静默回退**）。
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUMMARY = REPO / "results" / "summary"
CATALOG = REPO / "artifact" / "holdout" / "mutant_catalog.json"

DETECTORS = ["INV-1", "INV-2", "INV-3", "INV-4", "INV-5", "CTL-1", "CTL-2", "CTL-3"]
CLASS_ORDER = ["state_mutation", "exception_leak", "actions_not_restored", "order_dependent",
               "saturated", "db_blind", "strict_format"]
CLASS_LABEL = {
    "state_mutation": "state mutation",
    "exception_leak": "exception leak",
    "actions_not_restored": "actions not restored",
    "order_dependent": "order dependence",
    "saturated": "saturated oracle",
    "db_blind": "database-blind oracle",
    "strict_format": "strict output match",
}


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    raise SystemExit(1)


def load():
    for p in (SUMMARY / "b_matrix.csv", SUMMARY / "b_validity.csv", CATALOG):
        if not p.exists():
            die(f"缺少输入：{p}（若只下载了部分仓库，请先取全）")
    matrix = list(csv.DictReader((SUMMARY / "b_matrix.csv").open(encoding="utf-8")))
    validity = list(csv.DictReader((SUMMARY / "b_validity.csv").open(encoding="utf-8")))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not matrix or not validity:
        die("b_matrix.csv / b_validity.csv 为空")
    return matrix, validity, catalog


def main() -> int:
    matrix, validity, catalog = load()

    cls_of = {v: d["defect_class"] for v, d in catalog["variants"].items()}
    status = {(r["target"], r["variant"]): r["status"] for r in validity}
    differ = {k for k, s in status.items() if s == "confirmed_differ"}
    unresolved = {k for k, s in status.items() if s == "unresolved"}
    equivalent = {k for k, s in status.items() if s == "confirmed_equivalent"}

    fires: dict[tuple, set] = defaultdict(set)
    for r in matrix:
        if r["violated"] == "1":
            fires[(r["target"], r["variant"])].add(r["detector"])

    by_class: dict[str, list] = defaultdict(list)
    for k in differ:
        by_class[cls_of[k[1]]].append(k)

    rows = []
    for c in CLASS_ORDER:
        ks = by_class.get(c, [])
        union = sorted({d for k in ks for d in fires[k]}, key=DETECTORS.index)
        necessary = [d for d in DETECTORS if any(fires[k] == {d} for k in ks)]
        rows.append({
            "defect_class": CLASS_LABEL[c],
            "variants": len(ks),
            "checks_that_fire": ", ".join(union) or "(none)",
            "necessary": ", ".join(necessary) or "none",
            "variants_no_check_fires": sum(1 for k in ks if not fires[k]),
        })

    SUMMARY.mkdir(parents=True, exist_ok=True)
    with (SUMMARY / "table1_variant_necessity.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    detected_primary = sum(1 for k in differ if fires[k])
    missed = sorted(k for k in differ if not fires[k])
    detected_conservative = sum(1 for k in (differ | unresolved) if fires[k])
    registry = {d: sum(1 for k in differ if fires[k] == {d}) for d in DETECTORS}

    summary = [
        ("primary_denominator", len(differ), "confirmed-differ variant x target combinations"),
        ("unresolved", len(unresolved), "probes could not separate them from the reference"),
        ("confirmed_equivalent", len(equivalent), "no variant was shown equivalent"),
        ("detected_primary", detected_primary, f"of {len(differ)}"),
        ("conservative_denominator", len(differ | unresolved), ""),
        ("detected_conservative", detected_conservative, f"of {len(differ | unresolved)}"),
        ("combinations_not_detected", len(missed), "; ".join(f"{t}/{v}" for t, v in missed)),
        ("unique_detections_total", sum(registry.values()),
         "sum over detectors of leave-one-out-unique hits"),
    ]
    for d in DETECTORS:
        summary.append((f"unique_{d}", registry[d], "detections no other check contributes"))
    with (SUMMARY / "table1_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["quantity", "value", "note"])
        w.writerows(summary)

    print("Table 1 · defect class x detector   ——   from results/summary/, recomputed")
    print(f"{'defect class':24s} {'n':>3s}  {'necessary':22s} checks that fire")
    for r in rows:
        print(f"{r['defect_class']:24s} {r['variants']:3d}  {r['necessary']:22s} {r['checks_that_fire']}")
    print()
    print(f"primary denominator {len(differ)} | unresolved {len(unresolved)} "
          f"| confirmed equivalent {len(equivalent)}")
    print(f"full suite detects: primary {detected_primary}/{len(differ)}"
          f" | conservative {detected_conservative}/{len(differ | unresolved)}")
    if missed:
        print("not detected by any check:")
        for t, v in missed:
            print(f"   {t}/{v}   (defect class: {cls_of[v]})")
    print()
    print("unique detections per check:")
    for d in DETECTORS:
        print(f"   {d:6s} {registry[d]:2d}  {'<- load-bearing' if registry[d] else '   (redundant)'}")
    print()
    print("written: results/summary/table1_variant_necessity.csv, table1_summary.csv")
    print("These must match §4.1 of the paper. If they do not, the paper is wrong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
