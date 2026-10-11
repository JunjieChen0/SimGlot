#!/usr/bin/env python3
"""B-1 **独立执行反证**：顺序/缓存类变体在「两次评分之间不清理共享缓存」下确实改变判定。

## 来历（第二轮外部独立复审 2026-10-10）

第一轮的 P0 修好了 `id(env.user)` 的跨环境误判，但改完之后的 `b_validity.csv`
把 `C4`/`G4a`/`G4b` 判成「等价变体」并**排除出检出率分母**；而**同一份** `b_matrix.csv`
里 `INV-3` 对这三者在三个目标上**全部报警**。两个产物自相矛盾：
有效性门禁把**自己检测器已经抓到的真缺陷**从分母里剔掉了。

**根因**：`probes.run_probes` 的 `P7_order` 探针在 `for kind in order:` 循环**内部**
每一步都先调 `reset_state()`。`reset_state()` 会清空被测变体的模块级共享缓存
（`oracle_variants._ORDER_CACHE`，本轮的 `variants_ext` 也把状态寄存在同一字典里），
于是「第二次打分」永远看到冷缓存——**恰好抹掉了它本来要激发的那个缺陷**。

基础套件的 `detectors.inv3_order_independent` 不是这么写的：它**只在每一轮之前**
reset 一次，一轮之内的两次打分之间不清理。本脚本用同样构造跑出可执行反证。

## 判据

  · 参考实现：两种顺序下**按集对齐**的判定映射必须相同（无顺序效应）；
  · `C4`、`G4a`、`G4b`：必须**出现**顺序效应（否则本反证不成立）。

任一条不满足即非零退出。用法：python3 checks/order_cache_counterexample.py
"""

from __future__ import annotations

import sys
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
for _p in (ROOT, ROOT / "experiments" / "oracle_mutation_holdout"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import _boot  # noqa: E402,F401

from holdout import variants_ext as V  # noqa: E402
from holdout.probes import _solved_env  # noqa: E402

from oracle_audit_kit.adapters import QuietUser, TARGETS  # noqa: E402
from oracle_audit_kit.oracle_variants import VARIANTS as BASE, reset_state  # noqa: E402

TASK = 0


def _impls(target) -> dict:
    """{名字: 注入函数 or None(=参考实现)}。"""
    return {
        "参考实现": None,
        "C4_order_dependent": BASE["C4 order_dependent"],
        "G4a_keyless_cache": V.CATALOG["G4a_keyless_cache"][1],
        "G4b_prev_verdict_reuse": V.CATALOG["G4b_prev_verdict_reuse"][1],
    }


def _install(cls, had: bool, orig, fn) -> None:
    if fn is None:
        if had:
            setattr(cls, "calculate_reward", orig)
        else:
            try:
                delattr(cls, "calculate_reward")      # cls.__dict__ 是 mappingproxy
            except AttributeError:
                pass
    else:
        setattr(cls, "calculate_reward", fn)


def _plain_env(target, task):
    env = target.make(task)
    env.user = QuietUser()
    env.reset(task_index=task)
    return env


def run_order(target, task, order) -> dict:
    """按给定顺序连评——**两次打分之间不调 reset_state()**（这正是 INV-3 的构造）。"""
    out: dict = {}
    for kind in order:
        env = _solved_env(target, task) if kind == "solved" else _plain_env(target, task)
        try:
            out[kind] = target.oracle(env, task).solved
        except Exception as e:  # noqa: BLE001
            out[kind] = f"raised:{type(e).__name__}"
    return out


def probe(target, task) -> tuple[dict, dict]:
    reset_state()
    a = run_order(target, task, ["nothing", "solved"])
    reset_state()
    b = run_order(target, task, ["solved", "nothing"])
    return a, b


def main() -> int:
    target = TARGETS["synthetic/tiny"]()
    cls = target.env_class
    had = "calculate_reward" in cls.__dict__
    orig = cls.__dict__.get("calculate_reward")

    print("=" * 96)
    print(f"B-1 顺序/缓存独立反证｜目标 {target.name}｜task {TASK}｜两次评分之间**不**清理共享缓存")
    print("=" * 96)
    print(f"{'实现':<26}{'nothing→solved':>26}{'solved→nothing':>26}{'顺序效应':>10}")
    print("-" * 96)

    results: dict[str, tuple[dict, dict]] = {}
    fails: list[str] = []
    try:
        for name, fn in _impls(target).items():
            _install(cls, had, orig, fn)
            try:
                a, b = probe(target, TASK)
            finally:
                reset_state()
                _install(cls, had, orig, None)
            results[name] = (a, b)
            same = a == b
            fa, fb = tuple(a[k] for k in ["nothing", "solved"]), tuple(b[k] for k in ["solved", "nothing"])
            print(f"{name:<26}{str(fa):>26}{str(fb):>26}{('否' if same else '**是**'):>10}")
    finally:
        reset_state()
        _install(cls, had, orig, None)

    print("-" * 96)

    # ① 参考实现必须无顺序效应
    if results["参考实现"][0] != results["参考实现"][1]:
        fails.append("参考实现在两种顺序下判定不同——反证本身不成立，先查探针")

    # ② 三个缓存变体必须都有顺序效应
    for name in ("C4_order_dependent", "G4a_keyless_cache", "G4b_prev_verdict_reuse"):
        a, b = results[name]
        if a == b:
            fails.append(f"{name} 未出现顺序效应——与 b_matrix.csv 中 INV-3 的报警矛盾")
        elif results["参考实现"][0] != a and a == {k: False for k in a} and b.get("solved") is False:
            fails.append(f"{name} 的顺序效应单向偏负（两种顺序下 solved 恒 False）——需人工复核")

    print()
    for name in ("C4_order_dependent", "G4a_keyless_cache", "G4b_prev_verdict_reuse"):
        a, b = results[name]
        print(f"  {name}：{a} → {b}｜按集对齐后 "
              f"nothing={a['nothing']}/{b['nothing']}、solved={a['solved']}/{b['solved']}")

    if fails:
        print("\n✗ 反证失败：")
        for f in fails:
            print(f"    · {f}")
        return 1
    print("\n✓ 反证成立：参考实现无顺序效应，三个缓存变体在两轮之间不清理缓存时**全部**出现顺序效应。")
    print("  ⇒ C4 / G4a / G4b 是**真实可触发的缺陷**，不得记作「等价变体」并排除出分母。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
