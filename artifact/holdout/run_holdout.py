#!/usr/bin/env python3
"""工作包 B · 驱动器：预留变体的**有效性核查** + **缺陷类别 × 检测器**矩阵。

协议（计划 §4）：
  * 检测器与适配器**冻结**（用 `oracle_audit_kit` 里那一套，不改）；
  * 变体 = 基础套件的 C1–C7（**开发变体**，写检测器时已知）+ 本轮的 G\*（**预留变体**，
    函数体在检测器冻结之后才首次运行）；
  * 每个变体先用 `probes.check_variant` 与参考实现做**差分**，无效/等价的不进检出率分母；
  * 只有**有效**变体才进矩阵。

产物（可复算、可续跑——已存在的行会重算，故整脚本幂等）：
  results/b_validity.csv    每个 (target, variant) 的有效性与 witness
  results/b_matrix.csv      (target, variant, detector) → 是否报警 / 是否适用 / 检查数
  results/b_report.txt      人读报告

注意：矩阵里**没有**「时长」类字段——墙钟只打印，不写入产物（与 v1.0 的 D19-9 同族教训）。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import _boot  # noqa: E402,F401

from holdout import variants_ext as V  # noqa: E402
from holdout.probes import check_variant  # noqa: E402

from oracle_audit_kit.adapters import TARGETS, Target  # noqa: E402
from oracle_audit_kit.detectors import DETECTOR_ORDER, CheckResult, run_all  # noqa: E402
from oracle_audit_kit.oracle_variants import VARIANTS as BASE  # noqa: E402
from oracle_audit_kit.oracle_variants import reset_state  # noqa: E402

RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

#: 缺陷类 → 开发变体名（基础套件的名字）
DEV_NAME = {cls: dev for cls, (dev, _h) in V.HOLDOUT.items()}
HOLDOUT_NAME = {n: cls for cls, (n, fn, d, h) in V.CATALOG.items()}


def full_catalog() -> Dict[str, tuple]:
    """变体名 → (缺陷类, 函数, 是否预留)。"""
    out: Dict[str, tuple] = {}
    for name, fn in BASE.items():
        if fn is None:
            continue
        # 名字形如 "C1 state_mutation"：**空格**之后才是缺陷类。
        # 用 split("_") 会切在 "state_mutation" 自己的下划线上（踩过）。
        cls = name.split(" ", 1)[1] if " " in name else name
        out[name] = (cls, fn, False)
    for n, (cls, fn, d, hold) in V.CATALOG.items():
        out[n] = (cls, fn, True)
    return out


def dump_catalog() -> None:
    """把变体目录写成 `manifests/mutant_catalog.json`（冻结的名 → 类映射）。

    为什么要有这个文件：`analysis/analyze_b.py` 只需要「变体名 → 缺陷类」这一张表，
    却曾经靠 `from variants_ext import CATALOG` 去拿——那会拖着整个 τ-bench 栈一起引导，
    在 clean-room 里失败后又被 `except Exception` 吞掉（第二轮复审 B-3 的成因）。
    冻结成数据文件后，analyze_b 可以完全独立运行。
    """
    import json  # noqa: PLC0415

    cat = {n: {"defect_class": c, "held_out": bool(h)}
           for n, (c, _fn, h) in full_catalog().items()}
    man = ROOT / "manifests"
    man.mkdir(parents=True, exist_ok=True)
    (man / "mutant_catalog.json").write_text(
        json.dumps({"_comment": "变体目录：名 → 缺陷类 / 是否预留。由 run_holdout.py 生成。",
                    "generated": "2026-10-10", "variants": cat},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写 {man/'mutant_catalog.json'}（{len(cat)} 个变体）")


def install(target: Target, fn) -> tuple:
    cls = target.env_class
    had = "calculate_reward" in cls.__dict__
    orig = cls.__dict__.get("calculate_reward")
    setattr(cls, "calculate_reward", fn)
    return (cls, had, orig)


def uninstall(state: tuple) -> None:
    cls, had, orig = state
    if had:
        setattr(cls, "calculate_reward", orig)
    else:
        try:
            delattr(cls, "calculate_reward")
        except AttributeError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="tau-bench/retail,tau-bench/airline,synthetic/tiny")
    ap.add_argument("--tasks", type=int, default=6)
    ap.add_argument("--validity-tasks", type=int, default=3)
    ap.add_argument("--skip-validity", action="store_true")
    args = ap.parse_args()

    targets = [s.strip() for s in args.targets.split(",")]
    catalog = full_catalog()
    t0 = time.time()
    lines: List[str] = []

    def P(s: str = "") -> None:
        lines.append(s)
        print(s, flush=True)

    P("=" * 100)
    P("工作包 B · 预留变体：有效性核查 + 缺陷类别 × 检测器 矩阵")
    P("=" * 100)
    P(f"变体：开发 {sum(1 for v in catalog.values() if not v[2])} 个，"
      f"预留 {sum(1 for v in catalog.values() if v[2])} 个｜目标 {targets}｜每目标任务数 {args.tasks}")

    validity_rows: List[dict] = []
    matrix_rows: List[dict] = []

    for tname in targets:
        target = TARGETS[tname]()
        P("")
        P("─" * 100)
        P(f"目标：{target.name}")
        P("─" * 100)

        # ── 有效性核查 ──────────────────────────────────────────────────
        valid: Dict[str, bool] = {}
        vtasks = target.task_ids()[: args.validity_tasks]
        if args.skip_validity:
            valid = {n: True for n in catalog}
        else:
            P(f"[有效性] 差分探针，任务 {vtasks}")
            for name, (cls, fn, hold) in catalog.items():
                r = check_variant(target, vtasks, name, fn)
                valid[name] = r.valid
                tag = "预留" if hold else "开发"
                P(f"  {name:<30}{tag}  {'有效' if r.valid else '★无效'}"
                  f"  witness={str(r.witness):<24}{r.detail[:50]}")
                validity_rows.append({
                    "target": target.name, "variant": name, "defect_class": cls,
                    "held_out": int(hold), "valid": int(r.valid),
                    "status": r.status,          # 三态口径，与 rerun_validity.py 一致
                    "witness": r.witness or "", "probes_compared": r.probes_compared,
                    "detail": r.detail,
                })

        # ── 检测矩阵（只跑有效变体）─────────────────────────────────────
        P("")
        P(f"[矩阵] C0 + 有效变体，每目标 {args.tasks} 个任务")
        header = f"{'变体':<30}{'类':<22}" + "".join(f"{d:>7}" for d in DETECTOR_ORDER)
        P(header)

        # C0 特异性对照
        for name in ["C0 none (as-shipped)"]:
            fn = BASE.get(name)
            state = None if fn is None else install(target, fn)
            try:
                reset_state()
                cells = run_all(target, args.tasks)
            finally:
                if state:
                    uninstall(state)
            P(f"{name:<30}{'—':<22}" + "".join(f"{cells[d].mark:>7}" for d in DETECTOR_ORDER))
            matrix_rows += _rows(target, name, "reference", False, cells)

        for name, (cls, fn, hold) in catalog.items():
            if not valid[name]:
                continue
            state = install(target, fn)
            try:
                reset_state()
                try:
                    cells = run_all(target, args.tasks)
                except Exception as e:  # noqa: BLE001
                    cells = {d: CheckResult(d, True, f"驱动抛异常：{type(e).__name__}: {e}",
                                            ran=True, n_checked=0) for d in DETECTOR_ORDER}
            finally:
                uninstall(state)
            P(f"{name:<30}{cls:<22}" + "".join(f"{cells[d].mark:>7}" for d in DETECTOR_ORDER))
            matrix_rows += _rows(target, name, cls, hold, cells)

    # ── 汇总：开发 vs 预留 ──────────────────────────────────────────────
    P("")
    P("=" * 100)
    P("汇总（按目标）")
    P("=" * 100)
    by_target: Dict[str, List[dict]] = {}
    for r in matrix_rows:
        if r["variant"] == "C0 none (as-shipped)":
            continue
        by_target.setdefault(r["target"], []).append(r)

    for tname, rows in by_target.items():
        by_var: Dict[str, List[dict]] = {}
        for r in rows:
            by_var.setdefault(r["variant"], []).append(r)
        n_dev = n_ho = miss_dev = miss_ho = 0
        for var, cells in by_var.items():
            fired = [c["detector"] for c in cells if c["ran"] and c["violated"] == 1]
            hold = cells[0]["held_out"]
            if hold:
                n_ho += 1
                miss_ho += (not fired)
            else:
                n_dev += 1
                miss_dev += (not fired)
        P(f"  {tname}：开发变体 {n_dev} 个（未检出 {miss_dev}）｜"
          f"预留变体 {n_ho} 个（未检出 {miss_ho}）")

    # C0 特异性
    fp = [r for r in matrix_rows if r["variant"] == "C0 none (as-shipped)"
          and r["ran"] and r["violated"] == 1]
    P("")
    if fp:
        P(f"  ✗ 特异性失败：C0 上有 {len(fp)} 处报警：")
        for r in fp:
            P(f"      · {r['target']} · {r['detector']}")
    else:
        P("  ✓ 特异性：C0（as-shipped）在所有目标、所有检测器上均未报警。")

    P("")
    P(f"  用时 {time.time()-t0:.1f} s（仅打印，不写入产物）")

    (RESULTS / "b_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 列序与 analysis/rerun_validity.py 保持一致（含 status）——两个写入者口径不同
    # 会让下游 analyze_b.py 直接拒绝（它要求有 status 列）。
    _write_csv(RESULTS / "b_validity.csv", validity_rows,
               ["target", "variant", "defect_class", "held_out", "valid", "status",
                "witness", "probes_compared", "detail"])
    # 变体目录（名 → 缺陷类 / 是否预留）**冻结成数据文件**，
    # 使 analysis/analyze_b.py 不必引导整个 τ-bench 栈也能聚合到七类。
    dump_catalog()
    _write_csv(RESULTS / "b_matrix.csv", matrix_rows,
               ["target", "variant", "defect_class", "held_out", "detector",
                "violated", "ran", "n_checked", "detail"])
    print(f"\n已写 {RESULTS/'b_report.txt'} / b_validity.csv / b_matrix.csv")
    return 0


def _rows(target: Target, variant: str, cls: str, hold: bool,
          cells: Dict[str, CheckResult]) -> List[dict]:
    out = []
    for d in DETECTOR_ORDER:
        c = cells[d]
        out.append({
            "target": target.name, "variant": variant, "defect_class": cls,
            "held_out": int(bool(hold)), "detector": d,
            "violated": int(c.violated) if c.ran else "",
            "ran": int(c.ran), "n_checked": c.n_checked, "detail": c.detail,
        })
    return out


def _write_csv(path: Path, rows: List[dict], fields: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
