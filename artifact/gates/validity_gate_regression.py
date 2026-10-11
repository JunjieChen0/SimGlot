#!/usr/bin/env python3
"""B 有效性门禁的**回归测试**。

来历：外部独立复审（2026-10-10）给出一个可执行反例——把**参考实现自己**
当候选变体交给 `probes.check_variant()`，三个目标全部返回 `valid=True`。
根因是 `Target.state()` 末尾带 `id(env.user)`（Python 对象地址），
而门禁在**两个独立新建的环境**之间比它，必然不同。

本脚本把修复钉成**会失败的检查**：任一条不满足即非零退出。
用法：python3 validity_gate_regression.py
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
from holdout.probes import check_variant, comparable  # noqa: E402

from oracle_audit_kit.adapters import TARGETS  # noqa: E402
from oracle_audit_kit.oracle_variants import VARIANTS as BASE  # noqa: E402


def _reference_of(target):
    ref = target.env_class.__dict__.get("calculate_reward")
    if ref is None:
        from tau_bench.envs.base import Env
        ref = Env.__dict__.get("calculate_reward")
    return ref


def main() -> int:
    fails = []
    print("=" * 88)
    print("B 有效性门禁 · 回归测试")
    print("=" * 88)

    # 0 规范化本身：三字段状态必须被抹掉第三项（对象地址）
    st = ("datahash", ("a", "b"), 140234567890)
    if comparable(st) != ("datahash", ("a", "b")):
        fails.append("comparable() 未抹掉第三字段（对象地址）")
    print(f"  comparable 规范化：{comparable(st)}")

    t = TARGETS["synthetic/tiny"]()
    ref = _reference_of(t)

    # 1 参考实现 vs 自己 —— 必须**非**有效
    r = check_variant(t, [0, 1], "IDENTITY_REFERENCE", ref)
    print(f"  ① 参考实现 vs 自己 → valid={r.valid}（期望 False）")
    if r.valid:
        fails.append(f"① 同一实现被判为有效变体（{r.witness}）——门禁失效")

    # 2 已知真缺陷 —— 必须有效
    r = check_variant(t, [0], "C1_state_mutation", BASE["C1 state_mutation"])
    print(f"  ② C1 状态污染 → valid={r.valid} witness={r.witness}（期望 True）")
    if not r.valid:
        fails.append("② 已知真缺陷未被判为有效变体")

    # 3 只破坏输出等价的变体 —— witness 必须落在格式探针，**不是** P1
    r = check_variant(t, [0], "G7a_case_only", V.CATALOG["G7a_case_only"][1])
    print(f"  ③ G7a 只归一大小写 → valid={r.valid} witness={r.witness}（期望 P4_*）")
    if not r.valid:
        fails.append("③ 已知真缺陷未被判为有效变体")
    elif r.witness and r.witness.startswith("P1"):
        fails.append(f"③ 输出匹配类缺陷的 witness 落在 {r.witness}——应为格式探针")

    # 4 顺序/缓存类变体 —— 必须被判为**有效**，witness 落在顺序探针上
    #   （第二轮复审 B-1/B-2：旧 P7 在每次打分前都 reset，把这些真缺陷洗成了「等价」）
    for vname in ("C4 order_dependent", "G4a_keyless_cache", "G4b_prev_verdict_reuse"):
        fn = BASE[vname] if vname in BASE else V.CATALOG[vname][1]
        r = check_variant(t, [0, 1], vname, fn)
        print(f"  ④ {vname:<24} → valid={r.valid} witness={r.witness}（期望 P7_/P8_）")
        if not r.valid:
            fails.append(f"④ {vname} 被判为未定——顺序/缓存探针没有激励出该缺陷")
        elif not (r.witness or "").startswith(("P7", "P8")):
            fails.append(f"④ {vname} 的 witness 落在 {r.witness}——应为顺序探针")

    print()
    if fails:
        print("✗ 回归失败：")
        for f in fails:
            print(f"    · {f}")
        return 1
    print("✓ 回归通过：门禁能区分「同一个实现」与「真缺陷」，且 witness 落在正确的探针上。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
