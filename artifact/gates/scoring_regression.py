#!/usr/bin/env python3
"""§7 · 评分回归**防伪**：证明这套判据**真的会失败**。

外部审计指出：一个「只是打印结论」的回归脚本不构成回归。本脚本做成**双向**检查，
任一侧不符即非零退出：

  A 正向臂：对 **as-shipped**（已修补）的实现跑检测器 —— 必须**全绿**（特异性）；
  B 反向臂：把 **修补前的逻辑**（不带 try/finally 还原）装回去 —— 必须**至少一个检测器报警**；
  C 结论一致性：两臂的结论必须**相反**。若两臂结论相同，说明判据没有分辨力 ⇒ 失败。

于是：
  * 实现正确 → 本脚本退出 0；
  * 有人把污染逻辑改回去 → 反向臂「未报警」⇒ 本脚本**非零退出**；
  * 有人把检测器改成永远不报警 → 正向臂仍绿、反向臂不报警 ⇒ 同样非零退出。
发布脚本必须把它作为 gate，失败即中止发布。

用法：python3 scoring_regression.py [--tasks 4] [--targets tau-bench/retail]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import _boot  # noqa: E402,F401

from oracle_audit_kit.adapters import TARGETS, Target  # noqa: E402
from oracle_audit_kit.detectors import DETECTOR_ORDER, CheckResult, run_all  # noqa: E402
from oracle_audit_kit.oracle_variants import VARIANTS, reset_state  # noqa: E402


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


def run_arm(target: Target, fn, k: int) -> Dict[str, CheckResult]:
    state = None if fn is None else install(target, fn)
    try:
        reset_state()
        return run_all(target, k)
    finally:
        if state:
            uninstall(state)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=4)
    ap.add_argument("--targets", default="tau-bench/retail")
    args = ap.parse_args()

    t0 = time.time()
    failures = []
    print("=" * 88)
    print("评分回归防伪 · 双向检查")
    print("=" * 88)

    for tname in [s.strip() for s in args.targets.split(",")]:
        target = TARGETS[tname]()
        print(f"\n目标：{target.name}")

        # A 正向臂：as-shipped 必须全绿
        cells_ok = run_arm(target, None, args.tasks)
        fired_ok = [d for d in DETECTOR_ORDER if cells_ok[d].ran and cells_ok[d].violated]
        print(f"  A 正向臂（as-shipped）：报警 {fired_ok or '无'}")
        if fired_ok:
            failures.append(f"A 正向臂失败：as-shipped 上 {fired_ok} 报警（应为全绿）")

        # B 反向臂：修补前的逻辑必须被抓到
        pre_repair = VARIANTS["C1 state_mutation"]
        cells_bad = run_arm(target, pre_repair, args.tasks)
        fired_bad = [d for d in DETECTOR_ORDER if cells_bad[d].ran and cells_bad[d].violated]
        print(f"  B 反向臂（修补前逻辑）：报警 {fired_bad or '无'}")
        if not fired_bad:
            failures.append("B 反向臂失败：修补前逻辑未被任何检测器抓到（判据无分辨力）")

        # C 结论必须相反
        if bool(fired_ok) == bool(fired_bad):
            failures.append("C 两臂结论相同：判据对「正确 / 被污染」两种实现不可分辨")

    print("\n" + "=" * 88)
    if failures:
        print("✗ 回归检查失败：")
        for f in failures:
            print(f"    · {f}")
        print("  ⇒ 发布脚本必须在此中止。")
        print(f"  用时 {time.time()-t0:.1f} s（仅打印，不写入产物）")
        return 1
    print("✓ 回归检查通过：正确实现全绿，恢复污染逻辑即被抓住。")
    print(f"  用时 {time.time()-t0:.1f} s（仅打印，不写入产物）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
