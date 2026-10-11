"""检测器：一组**只读**的检查，用来看一个测试预言机是否可信。

分两族：

不变量（invariant）——预言机必须满足的性质，与具体任务无关
  INV-1 状态保持           直接调用打分函数不得改变被判分状态
  INV-2 重复评分一致       同一环境连评两次，判定与状态都必须相同
  INV-3 顺序无关           判定不得依赖各集被打分的先后
  INV-4 异常路径不泄漏     内部抛异常时，状态必须还原且异常必须外传
  INV-5 结束步状态稳定     会话结束步**不得改变**被判分状态（「第二次读取」危害的根因）

对照（control）——用已知答案的 episode 校验判定的**方向**是否正确
  CTL-1 负对照（必须不通过）①有写操作、无输出：什么都没做 ②有写操作、有输出：说了输出但没写库
  CTL-2 正对照（必须通过）  参考解 + 说全输出
  CTL-3 格式容忍（必须通过）输出写成等价写法（千分位 / 声明过的别名）仍应通过

每个检测器返回 CheckResult；`ran=False` 表示在该 target/任务集上不适用——**空跑不算通过**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from . import _paths  # noqa: F401
from .adapters import QuietUser, StopUser, Target  # noqa: E402
from .oracle_variants import reset_state  # noqa: E402

from tau_bench.types import Action  # noqa: E402


@dataclass
class CheckResult:
    detector: str
    violated: bool
    detail: str
    ran: bool = True
    n_checked: int = 0

    @property
    def mark(self) -> str:
        if not self.ran:
            return "·"        # N/A
        return "✗" if self.violated else "✓"


# ── 取样与构造 ──────────────────────────────────────────────────────────────

def _reference_changes_data(target: Target, t: int) -> bool:
    env = target.make(t)
    before = env.get_data_hash()
    for a in target.reference_actions(env):
        try:
            env.tools_map[a.name].invoke(data=env.data, **a.kwargs)
        except Exception:  # noqa: BLE001
            pass
    return env.get_data_hash() != before


def select_write_tasks(target: Target, k: int,
                       require_outputs: Optional[bool] = None) -> List[int]:
    """挑出「参考解**确实改写**数据库」的任务；可再按有无 outputs 过滤。"""
    out: List[int] = []
    for t in target.task_ids():
        env = target.make(t)
        if not target.has_writes(env):
            continue
        has_out = bool(getattr(env.task, "outputs", None))
        if require_outputs is not None and has_out != require_outputs:
            continue
        if not _reference_changes_data(target, t):
            continue
        out.append(t)
        if len(out) >= k:
            break
    return out


def _outputs_content(env, variants: Sequence[str] | None = None) -> str:
    """一段把任务要求的输出都说全的回复（可选换成等价写法）。"""
    outs = list(getattr(env.task, "outputs", []) or [])
    if not outs:
        return "All done, goodbye!"
    if variants:
        return "Here: " + " ".join(str(v) for v in variants)
    return "Here: " + " ".join(str(o) for o in outs)


def _solved_env(target: Target, t: int, variants: Sequence[str] | None = None):
    """一个**已被做对**的环境，且**不触发**预言机。

    用 QuietUser：respond 不会结束会话，故打分函数还没被调用过——检测器随后
    显式调用 `target.oracle`，被测的就是那一次调用。
    """
    env = target.make(t)
    env.user = QuietUser()
    env.reset(task_index=t)
    for a in target.reference_actions(env):
        env.step(Action(name=a.name, kwargs=dict(a.kwargs)))
    if getattr(env.task, "outputs", None):
        env.step(Action(name=target.respond, kwargs={"content": _outputs_content(env, variants)}))
    return env


# ── 不变量 ──────────────────────────────────────────────────────────────────

def inv1_state_preserved(target: Target, tasks: Sequence[int]) -> CheckResult:
    bad = []
    for t in tasks:
        reset_state()
        env = _solved_env(target, t)
        s0 = target.state(env)
        target.oracle(env, t)
        if target.state(env) != s0:
            bad.append(t)
    return CheckResult("INV-1 state-preservation", bool(bad),
                       f"打分改变了状态的任务：{bad[:6]}", True, len(tasks))


def inv2_repeat_consistent(target: Target, tasks: Sequence[int]) -> CheckResult:
    bad = []
    for t in tasks:
        reset_state()
        env = _solved_env(target, t)
        v1 = target.oracle(env, t)
        s1 = target.state(env)
        v2 = target.oracle(env, t)
        s2 = target.state(env)
        if v1.solved != v2.solved or s1 != s2:
            bad.append(t)
    return CheckResult("INV-2 repeat-consistency", bool(bad),
                       f"两次评分不一致的任务：{bad[:6]}", True, len(tasks))


def inv3_order_independent(target: Target, tasks: Sequence[int]) -> CheckResult:
    """把同一任务的两集按两种先后打分，比较**按集对齐**后的判定。

    比较的是 {集→判定} 这个映射，不是打分序列——否则「顺序」本身会把结果错开。
    """
    bad = []
    for t in tasks:
        def run(order) -> Dict[str, bool]:
            out: Dict[str, bool] = {}
            for kind in order:
                if kind == "solved":
                    env = _solved_env(target, t)
                else:
                    env = target.make(t)
                    env.user = QuietUser()
                    env.reset(task_index=t)
                out[kind] = target.oracle(env, t).solved
            return out

        reset_state()
        a = run(["nothing", "solved"])
        reset_state()
        b = run(["solved", "nothing"])
        if a != b:
            bad.append((t, a, b))
    return CheckResult("INV-3 order-independence", bool(bad),
                       f"判定随顺序改变 (task,先nothing,先solved)：{bad[:3]}", True, len(tasks))


def inv4_exception_restoration(target: Target, tasks: Sequence[int]) -> CheckResult:
    """在预言机**内部执行路径**上注入失败：状态必须还原，异常必须外传。

    若某实现在探针下根本没有走执行路径（既没抛异常也没动状态），对这个探针而言
    是**不适用**而不是通过——按 N/A 记，避免把「什么都没做」误读成「干净」。
    """
    bad, raised_any, n = [], False, 0
    for t in tasks:
        reset_state()
        env = _solved_env(target, t)
        s0 = target.state(env)

        def boom(*_a, **_k):
            raise RuntimeError("injected failure inside the oracle")

        env.step = boom
        raised = False
        try:
            target.oracle(env, t)
        except Exception:  # noqa: BLE001
            raised = True
        finally:
            del env.step
        if not raised:
            continue                      # 该实现不走这条路径 → 本任务不计入
        n += 1
        raised_any = True
        if target.state(env) != s0:
            bad.append(t)
    ran = raised_any
    return CheckResult("INV-4 exception-restoration", bool(bad),
                       (f"异常路径下未还原状态的任务：{bad[:6]}" if ran
                        else "预言机不经过内部执行路径，本探针不适用"),
                       ran, n)


def inv5_terminal_state_stability(target: Target, tasks: Sequence[int]) -> CheckResult:
    """会话结束步**不得**改变被判分的数据库状态，也不得留下多余的动作。

    这就是「第二次读取」危害的根因不变量：若预言机在打分时把环境留在参考解上，
    结束步之前与之后的**数据库散列**就不再相同——不需要任何下游代码配合就能看见。
    （结束步本身追加的那一条 respond 是合法的，故动作数只允许 +1。）
    """
    bad = []
    for t in tasks:
        reset_state()
        env = target.make(t)
        env.user = StopUser()
        env.reset(task_index=t)
        for a in target.reference_actions(env):
            env.step(Action(name=a.name, kwargs=dict(a.kwargs)))
        data_before = env.get_data_hash()
        n_before = len(env.actions)
        env.step(Action(name=target.respond, kwargs={"content": _outputs_content(env)}))
        if env.get_data_hash() != data_before or len(env.actions) != n_before + 1:
            bad.append(t)
    return CheckResult("INV-5 terminal-state stability", bool(bad),
                       f"结束步改变了数据库或留下多余动作的任务：{bad[:6]}", True, len(tasks))


# ── 对照 ────────────────────────────────────────────────────────────────────

def ctl1_negative(target: Target, tasks_no_out: Sequence[int],
                  tasks_with_out: Sequence[int]) -> CheckResult:
    bad_a, bad_b, n = [], [], 0
    for t in tasks_no_out:                      # ① 有写、无输出：什么都不做
        reset_state()
        env = target.make(t)
        target.do_nothing(env, t)
        reset_state()
        if target.oracle(env, t).solved:
            bad_a.append(t)
        n += 1
    for t in tasks_with_out:                    # ② 有写、有输出：只说输出、不写库
        reset_state()
        env = target.make(t)
        target.do_nothing(env, t, contents=[_outputs_content(env)])
        reset_state()
        if target.oracle(env, t).solved:
            bad_b.append(t)
        n += 1
    return CheckResult("CTL-1 negative-control", bool(bad_a or bad_b),
                       f"①未做事被判通过：{bad_a[:5]}；②只说未做被判通过：{bad_b[:5]}",
                       n > 0, n)


def ctl2_positive(target: Target, tasks: Sequence[int]) -> CheckResult:
    bad = []
    for t in tasks:
        reset_state()
        env = target.make(t)
        target.reference_solved(env, t, contents=[_outputs_content(env)])
        reset_state()
        if not target.oracle(env, t).solved:
            bad.append(t)
    return CheckResult("CTL-2 positive-control", bool(bad),
                       f"参考解被判不通过的任务：{bad[:6]}", True, len(tasks))


_DIGIT_RUN = re.compile(r"\d{4,}")


def _format_variant(required: str, declared: Sequence[str]) -> Optional[str]:
    """给出一个**该被接受**的等价写法；给不出就返回 None（该任务不参与本轮）。

    两种来源：① 对象自己声明的等价说法；② 输出里含 ≥4 位的数字串，给它插入千分位
    （τ-bench 与修补后的 harness **都**会去掉千分位逗号，故这是双方都该接受的写法）。
    """
    if declared:
        return declared[0]
    m = _DIGIT_RUN.search(str(required))
    if m:
        return f"{required[:m.start()]}{int(m.group()):,}{required[m.end():]}"
    return None


def ctl3_format_tolerance(target: Target, tasks: Sequence[int]) -> CheckResult:
    bad, n = [], 0
    for t in tasks:
        env = target.make(t)
        outs = list(getattr(env.task, "outputs", []) or [])
        if not outs:
            continue
        declared = target.accepted_variants(t)
        variant = [_format_variant(o, declared.get(o, [])) for o in outs]
        if any(v is None for v in variant):
            continue                                # 该任务构造不出等价写法
        reset_state()
        env = _solved_env(target, t, variants=variant)
        reset_state()
        if not target.oracle(env, t).solved:
            bad.append(t)
        n += 1
    return CheckResult("CTL-3 format-tolerance", bool(bad),
                       f"该接受而未接受的等价写法：{bad[:6]}", n > 0, n)


def run_all(target: Target, k: int) -> Dict[str, CheckResult]:
    """按固定取样跑完全部检测器（取样一次，所有检测器共用，保证可复现）。"""
    tasks = select_write_tasks(target, k)
    no_out = select_write_tasks(target, k, require_outputs=False)
    with_out = select_write_tasks(target, k, require_outputs=True)
    return {
        "INV-1": inv1_state_preserved(target, tasks),
        "INV-2": inv2_repeat_consistent(target, tasks),
        "INV-3": inv3_order_independent(target, tasks),
        "INV-4": inv4_exception_restoration(target, tasks),
        "INV-5": inv5_terminal_state_stability(target, tasks),
        "CTL-1": ctl1_negative(target, no_out, with_out),
        "CTL-2": ctl2_positive(target, tasks),
        "CTL-3": ctl3_format_tolerance(target, with_out or tasks),
    }


DETECTOR_ORDER = ["INV-1", "INV-2", "INV-3", "INV-4", "INV-5", "CTL-1", "CTL-2", "CTL-3"]
