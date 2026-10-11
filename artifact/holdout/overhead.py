#!/usr/bin/env python3
"""工作包 B5 · 开销与适配成本（**实际测量**，不从集合计数推导）。

计划 §4 B5 要求：冷启动时间、热启动检测时间、P50/P95、峰值内存、适配代码行数、实际工时。

口径（先写死）：
  * 冷启动 = 进程内**第一次**建环境 + 跑单个检测器的时间（含导入与数据加载）；
  * 热启动 = 之后同一检测器的重复时间；报告 **P50 / P95**（20 次重复）；
  * 20 次重复只用于**稳定性与开销**，**不**当作 20 个独立缺陷样本；
  * 峰值内存用 `resource.getrusage(RUSAGE_SELF).ru_maxrss`（整进程峰值，非单次增量）；
  * 适配代码行数按**该适配器的非空、非注释行**计。

用法：python3 overhead.py [--reps 20] [--tasks 3]
产物：results/b_overhead.json + results/b_overhead.txt
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
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


ROOT = _find_root(HERE)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import _boot  # noqa: E402,F401

from oracle_audit_kit.adapters import TARGETS  # noqa: E402
from oracle_audit_kit.detectors import DETECTOR_ORDER, run_all  # noqa: E402

LINES: list[str] = []


def P(s: str = "") -> None:
    LINES.append(s)
    print(s, flush=True)


def loc(path: Path) -> int:
    """非空、非纯注释的代码行数。"""
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith("#") and not t.startswith('"""') and not t.startswith("'''"):
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--tasks", type=int, default=3)
    ap.add_argument("--targets", default="tau-bench/retail,synthetic/tiny")
    args = ap.parse_args()

    out: dict = {"reps": args.reps, "tasks": args.tasks, "targets": {}}
    P("=" * 96)
    P("工作包 B5 · 开销与适配成本（实测）")
    P("=" * 96)
    P(f"每目标任务数 {args.tasks}｜每检测器重复 {args.reps} 次（仅用于稳定性与开销）")

    for tname in [s.strip() for s in args.targets.split(",")]:
        target = TARGETS[tname]()
        P("")
        P(f"── 目标 {target.name}")

        # 冷启动：第一次建环境 + 第一次跑整套
        t0 = time.perf_counter()
        env0 = target.make(0)
        cold_make = time.perf_counter() - t0
        t0 = time.perf_counter()
        _ = target.oracle(env0, 0)
        cold_oracle = time.perf_counter() - t0

        # 热启动：整套跑 reps 次，记录每次耗时
        times = []
        for _ in range(args.reps):
            t0 = time.perf_counter()
            run_all(target, args.tasks)
            times.append(time.perf_counter() - t0)
        times_sorted = sorted(times)
        p50 = statistics.median(times)
        p95 = times_sorted[min(len(times_sorted) - 1, int(round(0.95 * (len(times_sorted) - 1))))]

        peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rec = {
            "cold_start_make_env_s": round(cold_make, 4),
            "cold_start_oracle_call_s": round(cold_oracle, 4),
            "warm_suite_p50_s": round(p50, 4),
            "warm_suite_p95_s": round(p95, 4),
            "warm_suite_min_s": round(min(times), 4),
            "warm_suite_max_s": round(max(times), 4),
            "peak_rss_mb": round(peak_kb / 1024.0, 1),
            "suite_runs": args.reps,
        }
        P(f"   冷启动·建环境 {cold_make*1000:.0f} ms｜冷启动·单次打分 {cold_oracle*1000:.0f} ms")
        P(f"   热启动·整套 P50 {p50:.3f} s｜P95 {p95:.3f} s"
          f"（min {min(times):.3f} / max {max(times):.3f}）")
        P(f"   进程峰值常驻内存 {rec['peak_rss_mb']} MB")
        out["targets"][target.name] = rec

    # 适配成本
    P("")
    P("── 适配代码行数（非空、非注释）")
    code = {
        "oracle_audit_kit/adapters.py": ROOT.parent / "sqj" / "oracle_audit_kit" / "adapters.py",
        "holdout/variants_ext.py": HERE / "variants_ext.py",
        "holdout/probes.py": HERE / "probes.py",
        "holdout/run_holdout.py": HERE / "run_holdout.py",
    }
    locs = {}
    for name, p in code.items():
        if p.exists():
            locs[name] = loc(p)
            P(f"   {name:<34}{locs[name]:>6} 行")
    out["loc"] = locs

    P("")
    P("  判读：E0 核心（8 个检测器 + 4 条 target 契约）在换成第二个实现时**没有改动**；")
    P("        新增的只是**变体目录**与**差分探针**，行数见上表。")

    (ROOT / "results" / "b_overhead.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "results" / "b_overhead.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    print(f"\n已写 {ROOT/'results'/'b_overhead.json'} 与 b_overhead.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
