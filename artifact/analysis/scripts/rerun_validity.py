#!/usr/bin/env python3
"""P0 修复后**重算有效性**，并保留旧结果供对照。

背景（两轮）：
  · 第一轮外部复审（2026-10-10）用「把参考实现自己当变体」的反例证明原门禁失效——
    `Target.state()` 末尾的 `id(env.user)` 被拿去比两个**独立新建**的环境，必然不同。
    修复见 `probes.comparable()`。
  · 第二轮外部复审（同日）指出：改完之后 `C4`/`G4a`/`G4b` 被判成「等价变体」排除出分母，
    而同一份 `b_matrix.csv` 里 INV-3 对这三者全部报警——门禁把**自己检测器抓到的真缺陷**
    剔出了分母。根因是 `P7_order` 探针在每次打分前都调 `reset_state()`，抹掉了要激发的
    缓存缺陷。已在 `probes.run_probes` 修正为与 INV-3 同构，并补 `P8`（不同任务顺序）。
    独立反证见 `checks/order_cache_counterexample.py`。

本脚本**只重算有效性**，不重跑检测矩阵（矩阵由 `run_holdout.py` 产出；检测器都在
**同一个环境内部**前后比较状态，跨环境比较只存在于本门禁）。旧件**按名字+时间戳另存**，
绝不覆盖已有的归档：见 `_archive()`。

用法：python3 rerun_validity.py [--targets ...] [--tasks 3]
产物：results/b_validity.csv（主件，含 status 列）+ results/b_validity_<时间戳>.csv（旧件归档）
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import time
from datetime import datetime
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
for _p in (ROOT, ROOT / "experiments" / "oracle_mutation_holdout"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import _boot  # noqa: E402,F401

from holdout.probes import check_variant  # noqa: E402
from oracle_audit_kit.adapters import TARGETS  # noqa: E402
from run_holdout import full_catalog  # noqa: E402

RESULTS = ROOT / "results"
FIELDS = ["target", "variant", "defect_class", "held_out", "valid", "status", "witness",
          "probes_compared", "detail"]


def _archive(path: Path, tag: str) -> Path | None:
    """把现有主件另存为 `b_validity_<tag>.csv`。**已存在则不动**（不与历史归档抢名字）。"""
    if not path.exists():
        return None
    dest = RESULTS / f"b_validity_{tag}.csv"
    if dest.exists():
        dest = RESULTS / f"b_validity_{tag}_{datetime.now():%H%M%S}.csv"
    shutil.copy2(path, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="tau-bench/retail,tau-bench/airline,synthetic/tiny")
    ap.add_argument("--tasks", type=int, default=3)
    args = ap.parse_args()

    out_csv = RESULTS / "b_validity.csv"
    # 归档时按「上一版是什么」命名：先看它有没有 status 列（有 ⇒ 已是修补后版本）
    tag = "prev"
    if out_csv.exists():
        with out_csv.open(encoding="utf-8") as fh:
            if "status" not in (fh.readline() or ""):
                tag = "pre_p8fix"
    dest = _archive(out_csv, tag)
    if dest:
        print(f"旧件已另存 {dest}（不删除）")

    catalog = full_catalog()
    rows = []
    t0 = time.time()
    print("=" * 100)
    print("重算变体有效性（顺序/缓存探针修补后）")
    print("=" * 100)
    for tname in [s.strip() for s in args.targets.split(",")]:
        target = TARGETS[tname]()
        vtasks = target.task_ids()[: args.tasks]
        print(f"\n目标 {target.name}｜探针任务 {vtasks}")
        n_valid = 0
        for name, (cls, fn, hold) in catalog.items():
            r = check_variant(target, vtasks, name, fn)
            n_valid += int(r.valid)
            tag_s = {"confirmed_differ": "有效", "unresolved": "★未定",
                     "confirmed_equivalent": "等价", "load_failed": "装载失败"}.get(r.status, r.status)
            print(f"  {name:<30}{'预留' if hold else '开发'}  {tag_s}"
                  f"  witness={str(r.witness):<26}{r.detail[:44]}")
            rows.append({"target": target.name, "variant": name, "defect_class": cls,
                         "held_out": int(hold), "valid": int(r.valid), "status": r.status,
                         "witness": r.witness or "", "probes_compared": r.probes_compared,
                         "detail": r.detail})
        print(f"  → 有效 {n_valid}/{len(catalog)}")

    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    v = sum(r["valid"] for r in rows)
    unresolved = [r for r in rows if r["status"] == "unresolved"]
    other = [r for r in rows if r["status"] not in ("confirmed_differ", "unresolved")]
    print()
    print("=" * 100)
    print(f"合计：有效（confirmed_differ）{v}/{total}｜未定（unresolved）{len(unresolved)}｜"
          f"其他 {len(other)}")
    if unresolved:
        print("  被判为**未定**的组合（探针未观察到差别，**不等于等价**；")
        print("  不计入主分母，计入保守分母。本轮没有任何一条达到「已证明等价」的标准）：")
        for r in unresolved:
            print(f"    · {r['target']} / {r['variant']}：{r['detail'][:56]}")
    for r in other:
        print(f"    · [其他] {r['target']} / {r['variant']}：{r['status']}｜{r['detail'][:50]}")
    print(f"  用时 {time.time()-t0:.0f} s（仅打印，不写入产物）")
    print(f"已写 {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
