#!/usr/bin/env python3
"""**基线身份核验**：回答「E0 的 C0 到底审的是哪个实现」——独立复核方提的第一号问题。

## 问题

矩阵里 C0（as-shipped）全绿，正文却说 INV-5 会在基准的评分函数上报警。两句都真，
但**只有说清各自指的是哪个对象**才成立：

  * 本项目 `vendor/tau-bench` 里的 `Env.calculate_reward()` **已带 v1.0 的 D17 修补**
    （`try/finally` 还原）⇒ C0 审的是**已修补**的实现 ⇒ 全绿；
  * C1 是**显式复刻的修补前实现**（上游原逻辑）⇒ INV-5 报警。

**本脚本把这三件事各自断言一遍**，使「C0 是什么」不靠叙述、而靠可运行的判据。

用法：cd sqj/oracle_audit_kit && python3 verify_baseline_identity.py
出入码 0 = 三条断言全过。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from oracle_audit_kit import _paths  # noqa: E402,F401
from oracle_audit_kit.adapters import TARGETS  # noqa: E402
from oracle_audit_kit.detectors import inv5_terminal_state_stability, select_write_tasks  # noqa: E402
from oracle_audit_kit.oracle_variants import VARIANTS, reset_state  # noqa: E402

from tau_bench.envs.base import Env  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, ok: str, bad: str) -> None:
    print(("  ✓ " if cond else "  ✗ ") + (ok if cond else bad))
    if not cond:
        FAILS.append(bad)


def main() -> int:
    print("=" * 88)
    print("基线身份核验：C0 审的是已修补的实现，C1 复刻的是修补前的上游逻辑")
    print("=" * 88)

    src = inspect.getsource(Env.calculate_reward)
    print("\n── 1. 本项目 vendored 的 `Env.calculate_reward` 是否带 D17 修补？ ──")
    check("finally:" in src and "_data_snapshot" in src,
          "带修补：函数内有快照 + `finally` 还原 ⇒ **C0（不注入）审的是已修补的实现**",
          "未带修补 —— 那么 C0 全绿这件事需要重新解释")
    check("SimGlot 修补" in src,
          "修补处带 SimGlot 署名注释（可追溯到 v1.0 DEVIATIONS D17）",
          "修补处没有署名注释，来源不可追溯")

    print("\n── 2. C1 复刻的确实是修补前的逻辑（逐行核对关键差异） ──")
    c1 = inspect.getsource(VARIANTS["C1 state_mutation"])
    check("finally" not in c1 and "_restore" not in c1,
          "C1 内**没有**任何还原语句（`finally` / `_restore` 都不出现）⇒ 即上游原逻辑",
          "C1 里出现了还原语句 —— 那它就不是修补前的实现")

    print("\n── 3. 两种实现上的 INV-5 行为必须相反 ──")
    for name in ("tau-bench/retail", "tau-bench/airline"):
        target = TARGETS[name]()
        tasks = select_write_tasks(target, 4)

        reset_state()
        r0 = inv5_terminal_state_stability(target, tasks)
        check((not r0.violated) and r0.ran,
              f"{name} · C0（已修补）：INV-5 不报警 —— {r0.detail}",
              f"{name} · C0：INV-5 报警了，与「C0 全绿」矛盾")

        cls = target.env_class
        had = "calculate_reward" in cls.__dict__
        orig = cls.__dict__.get("calculate_reward")
        setattr(cls, "calculate_reward", VARIANTS["C1 state_mutation"])
        try:
            reset_state()
            r1 = inv5_terminal_state_stability(target, tasks)
        finally:
            if had:
                setattr(cls, "calculate_reward", orig)
            else:
                delattr(cls, "calculate_reward")
        check(r1.violated,
              f"{name} · C1（修补前）：INV-5 **报警** —— {r1.detail}",
              f"{name} · C1：INV-5 竟然没报警 —— 检测器漏了这类缺陷")

    print("\n" + "=" * 88)
    if FAILS:
        print(f"✗ {len(FAILS)} 项失败：")
        for f in FAILS:
            print("   · " + f)
        return 1
    print("✓ 全过。结论：**C0 = 本项目随包发布的、已修补的实现；C1 = 修补前上游逻辑的复刻**。")
    print("  论文必须照此写明，不得把「as-shipped」读成「上游原版」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
