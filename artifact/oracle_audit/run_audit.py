#!/usr/bin/env python3
"""E0 驱动器：在若干目标上跑「缺陷类别 × 检测器」矩阵，并写出可复算的产物。

用法：
    python3 run_audit.py [--tasks 6] [--targets tau-bench/retail,tau-bench/airline,synthetic/tiny]

产物：
    results/oracle_audit_matrix.txt   人读报告（含结论与盲区）
    results/oracle_audit_matrix.csv   机器可读矩阵（长表）

设计要点：
* 每个 (target, defect) 组合开跑前**清空注入变体的模块级状态**，使 C4 的顺序依赖可复现；
* 检测器抛异常也算「报警」，但要单独标注（一个会把检测器打崩的预言机本身不可用）；
* **C0（as-shipped）必须全绿**——这是特异性；任一检测器在 C0 上误报，即为假阳性。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:            # 使 `python3 run_audit.py` 可直接运行
    sys.path.insert(0, str(HERE.parent))

from oracle_audit_kit import _paths  # noqa: E402,F401  离线引导（副作用导入）

from oracle_audit_kit.adapters import TARGETS, Target  # noqa: E402
from oracle_audit_kit.detectors import (  # noqa: E402
    DETECTOR_ORDER, CheckResult, run_all, select_write_tasks)
from oracle_audit_kit.oracle_variants import VARIANTS, reset_state  # noqa: E402

RESULTS = HERE / "results"
LINES: List[str] = []


def P(s: str = "") -> None:
    LINES.append(s)


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
        delattr(cls, "calculate_reward")


def audit_target(name: str, k_tasks: int) -> List[dict]:
    target = TARGETS[name]()
    tasks = select_write_tasks(target, k_tasks)
    no_out = select_write_tasks(target, k_tasks, require_outputs=False)
    with_out = select_write_tasks(target, k_tasks, require_outputs=True)
    P("")
    P("=" * 92)
    P(f"目标：{target.name}")
    P(f"取样·有写操作：{tasks}")
    P(f"取样·有写无输出：{no_out}   ｜   取样·有写有输出：{with_out}")
    P("-" * 92)
    header = f"{'缺陷类别':<26}" + "".join(f"{d:>7}" for d in DETECTOR_ORDER)
    P(header)
    print(header, flush=True)

    rows: List[dict] = []
    for defect, fn in VARIANTS.items():
        state = install(target, fn) if fn is not None else None
        try:
            reset_state()
            try:
                cells = run_all(target, k_tasks)
            except Exception as e:  # noqa: BLE001
                cells = {d: CheckResult(d, True, f"驱动抛异常：{type(e).__name__}: {e}",
                                        ran=True, n_checked=0) for d in DETECTOR_ORDER}
        finally:
            if state is not None:
                uninstall(state)

        line = f"{defect:<26}"
        for dname in DETECTOR_ORDER:
            r = cells[dname]
            line += f"{r.mark:>7}"
            rows.append({
                "target": target.name, "defect": defect, "detector": dname,
                "violated": int(r.violated) if r.ran else "",
                "ran": int(r.ran), "n_checked": r.n_checked, "detail": r.detail,
            })
        P(line)
        print(line, flush=True)          # 逐行回显：τ-bench 上整轮需数分钟，便于观察进度
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=6)
    ap.add_argument("--targets", default="tau-bench/retail,tau-bench/airline,synthetic/tiny")
    args = ap.parse_args()

    t0 = time.time()
    P("=" * 92)
    P("E0 · 测试预言机完整性审计 · 缺陷类别 × 检测器")
    P("=" * 92)
    P("检测器：INV-1 状态保持 ｜ INV-2 重复评分一致 ｜ INV-3 顺序无关 ｜ INV-4 异常路径还原")
    P("        INV-5 记录—状态一致 ｜ CTL-1 负对照 ｜ CTL-2 正对照 ｜ CTL-3 格式容忍")
    P("符号：✓ 未报警（该检测器认为预言机在此性质上可信）｜ ✗ 报警 ｜ · 不适用")

    all_rows: List[dict] = []
    for name in args.targets.split(","):
        all_rows += audit_target(name.strip(), args.tasks)

    # ── 汇总 ────────────────────────────────────────────────────────────────
    P("")
    P("=" * 92)
    P("汇总")
    P("=" * 92)
    by_target: Dict[str, Dict[str, List[dict]]] = {}
    for r in all_rows:
        by_target.setdefault(r["target"], {}).setdefault(r["defect"], []).append(r)

    gaps: List[str] = []
    falsepos: List[str] = []
    for tgt, bydef in by_target.items():
        for defect, cells in bydef.items():
            fired = [c["detector"] for c in cells if c["ran"] and c["violated"] == 1]
            na = [c["detector"] for c in cells if not c["ran"]]
            if defect.startswith("C0"):
                if fired:
                    falsepos.append(f"{tgt} · {defect} → {fired}")
            elif not fired:
                gaps.append(f"{tgt} · {defect} → 无检测器报警（类别盲区）")
            else:
                P(f"  {tgt:<22}{defect:<26} 被 {', '.join(fired)} 检出"
                  + (f"；不适用 {', '.join(na)}" if na else ""))

    P("")
    if falsepos:
        P("  ✗ 假阳性（C0 上不应报警）：")
        for f in falsepos:
            P(f"      · {f}")
    else:
        P("  ✓ 特异性：C0（as-shipped）在每个目标上都全绿——没有检测器误报。")
    if gaps:
        P("  ✗ 盲区：")
        for g in gaps:
            P(f"      · {g}")
    else:
        P("  ✓ 灵敏度：每个注入缺陷类别都至少被一个检测器检出。")

    P("")
    P("  读法：INV-* 检验**状态完整性**（预言机是否干干净净地只读）；")
    P("        CTL-* 检验**判定方向**（用已知答案的 episode 校验通过/不通过）。")
    P("        两者不可互相替代——C5/C6 类别只有对照抓得到，C1/C3 只有不变量抓得到。")
    # 墙钟时间**只打印、不写进产物**：否则同一套判据每次重跑都会在产物里留一行不同的数，
    # 使「逐字节可复现」不成立（本轮自查发现：隔离复算与工作树只差这一行）。
    print(f"\n  用时 {time.time()-t0:.1f} s（仅打印，不写入产物）")

    RESULTS.mkdir(parents=True, exist_ok=True)
    DEFAULT = "tau-bench/retail,tau-bench/airline,synthetic/tiny"
    if args.targets.strip() != DEFAULT:
        P("")
        P(f"  ⚠ 本次只跑了 {args.targets}，**不是**默认的完整目标集。")
        P("    下面写出的 oracle_audit_matrix.* 因此是**部分结果**；")
        P("    要恢复规范产物请不带 --targets 重跑（或改动本文件的产物名）。")
    (RESULTS / "oracle_audit_matrix.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    with (RESULTS / "oracle_audit_matrix.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["target", "defect", "detector", "violated",
                                           "ran", "n_checked", "detail"])
        w.writeheader()
        w.writerows(all_rows)
    print("\n".join(LINES))
    print(f"\n已写 {RESULTS/'oracle_audit_matrix.txt'} 与 .csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
