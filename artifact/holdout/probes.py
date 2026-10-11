"""工作包 B2 · 变体有效性的**独立核查**。

计划 §4 B2 要求：在跑检测器套件**之前**，用「不调用该套件的最小检查」验证每个变体
——能加载、预定路径可达、**确实违反目标契约**、不是语法/导入错误、与原实现不等价。

本文件的做法是**差分探测**（一种最不依赖具体缺陷类的判据）：

  1. 在一组从契约出发构造的探针 episode 上，分别用
       · **参考实现**（不注入，即 as-shipped 的 `calculate_reward`）
       · **待核查变体**
     各跑一遍；
  2. 记录每次的 `(判定, 事后状态签名, 是否外传异常)`；
  3. 若存在**任一**探针上两者不同 ⇒ 该变体**有效**（确实改变了可观察行为），
     并把第一个不同的探针记为它的 **witness**；
  4. 全都相同 ⇒ 记为 **等价变体**（invalid: equivalent），不计入检出率分母。

它与检测器的分工：
  * 检测器回答「**报警了吗**」；
  * 本文件回答「**这个变体到底是不是个真缺陷**」。
两者用**各自的代码**实现，故「检测器抓不到」不会被误判成「变体无效」。

探针（都从契约出发，不看变体）：
  P1 什么都没做            —— 契约：不应通过
  P2 只说答案、不写库       —— 契约：不应通过（仅在任务要求写库时）
  P3 参考解法做完           —— 契约：应通过
  P4 参考解 + 等价写法       —— 契约：应通过（仅在构造得出等价写法时）
  P5 对同一环境连评两次      —— 契约：两次判定与状态一致
  P6 在预言机内部路径注入失败 —— 契约：状态还原且异常外传
  P7 换打分顺序（同任务）    —— 契约：按集对齐的判定不变
  P8 换打分顺序（不同任务）  —— 契约：按集对齐的判定不变

**P7/P8 的构造不是随便写的**（第二轮外部复审 2026-10-10 抓到第一版写错了）：
顺序探针**只在每一轮之前** `reset_state()` 一次，**一轮之内的两次打分之间绝不清理**。
第一版把 `reset_state()` 写进了 `for kind in order:` 循环内部，每打分一次就清一次
模块级共享缓存（`oracle_variants._ORDER_CACHE`），恰好抹掉了它要激发的顺序/缓存缺陷，
于是 `C4`/`G4a`/`G4b` 被误判成「等价变体」并排除出检出率分母——而同一份 `b_matrix.csv`
里 INV-3 对这三者全部报警。基础套件 `detectors.inv3_order_independent` 的构造才是对的，
本文件现在与它同构。独立反证见 `checks/order_cache_counterexample.py`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from oracle_audit_kit.adapters import QuietUser, StopUser, Target
from oracle_audit_kit.oracle_variants import reset_state

from tau_bench.types import Action


def comparable(state):
    """把状态签名规范化成**可跨环境比较**的形式。

    基础套件 `Target.state()` 的末尾是 `id(env.user)`——一个 **Python 对象地址**。
    它只在**同一个环境内部**前后比较时才有意义（用来发现"预言机把用户对象换掉了"）；
    拿它去比**两个独立新建的环境**，任何两个环境都必然不同，于是
    「变体与参考实现在这一点上有差异」会被**无条件**判真。

    **外部复审 2026-10-10 用一个可执行反例抓到了这个缺陷**：把**参考实现自己**
    当候选变体交给本函数，三个目标全部返回 `valid=True`，witness 全是 `P1_do_nothing`，
    `probes_compared` 全是 1。这使原先 `b_validity.csv` 里 63/63「有效」的结论**不成立**。
    """
    if isinstance(state, tuple) and len(state) == 3 and isinstance(state[2], int):
        return state[:2]                     # 丢掉对象地址，保留 (数据散列, 动作历史)
    return state


@dataclass
class ProbeObservation:
    verdict: Optional[bool] = None      # 判定（None = 未取得）
    state: Any = None                   # 事后状态签名
    raised: Optional[bool] = None       # 是否外传异常
    applicable: bool = True             # 该探针在此 target/任务上是否适用
    note: str = ""


@dataclass
class DifferentialResult:
    variant: str
    valid: bool
    witness: Optional[str] = None
    detail: str = ""
    probes_compared: int = 0
    per_probe: Dict[str, str] = field(default_factory=dict)
    #: 三态而非二态（第二轮复审 2026-10-10 的 B-2 要求）：
    #:   confirmed_differ     —— 至少一个探针上与参考实现分区 ⇒ 真缺陷，**计入分母**
    #:   unresolved           —— 全部探针**未观察到**差别 ⇒ 探针灵敏度不足，**不等于等价**
    #:   confirmed_equivalent —— 有可说明的等价论证（本轮**没有任何一条**达到这个标准）
    status: str = "unresolved"


DIFFER = "confirmed_differ"
UNRESOLVED = "unresolved"
EQUIVALENT = "confirmed_equivalent"


# ── 探针构造（只用 Target 的四条契约，不碰 detectors.py）─────────────────────

def _outputs(env) -> List[str]:
    return list(getattr(env.task, "outputs", []) or [])


def _say_all(env, variants: Sequence[str] | None = None) -> str:
    outs = _outputs(env)
    if not outs:
        return "All done, goodbye!"
    return "Here: " + " ".join(str(v) for v in (variants or outs))


def _solved_env(target: Target, t: int, variants: Sequence[str] | None = None):
    """已被做对、且**尚未触发**预言机的环境（QuietUser 不结束会话）。"""
    env = target.make(t)
    env.user = QuietUser()
    env.reset(task_index=t)
    for a in target.reference_actions(env):
        env.step(Action(name=a.name, kwargs=dict(a.kwargs)))
    if _outputs(env):
        env.step(Action(name=target.respond, kwargs={"content": _say_all(env, variants)}))
    return env


def _observed(target: Target, env, t: int) -> ProbeObservation:
    try:
        v = target.oracle(env, t)
    except Exception as e:  # noqa: BLE001
        return ProbeObservation(None, target.state(env), True, note=type(e).__name__)
    return ProbeObservation(v.solved, target.state(env), False)


_DIGITS = re.compile(r"\d{4,}")


def _equivalent_spelling(required: str, declared: Sequence[str]) -> Optional[str]:
    if declared:
        return declared[0]
    m = _DIGITS.search(str(required))
    if m:
        return f"{required[:m.start()]}{int(m.group()):,}{required[m.end():]}"
    return None


def run_probes(target: Target, t: int) -> Dict[str, ProbeObservation]:
    """在任务 t 上跑全部探针，返回 {探针名: 观测}。"""
    out: Dict[str, ProbeObservation] = {}

    # P1 什么都没做
    reset_state()
    env = target.make(t)
    target.do_nothing(env, t)
    reset_state()
    out["P1_do_nothing"] = _observed(target, env, t)

    # P2 只说答案、不写库（仅在任务确实要求写库时适用）
    has_writes = target.has_writes(target.make(t))
    if has_writes:
        reset_state()
        env = target.make(t)
        target.do_nothing(env, t, contents=[_say_all(env)])
        reset_state()
        out["P2_say_only"] = _observed(target, env, t)
    else:
        out["P2_say_only"] = ProbeObservation(applicable=False, note="任务无写操作")

    # P3 参考解做完
    reset_state()
    env = target.make(t)
    target.reference_solved(env, t, contents=[_say_all(env)])
    reset_state()
    out["P3_reference_solved"] = _observed(target, env, t)

    # P4 参考解 + 等价写法
    env_probe = target.make(t)
    declared = target.accepted_variants(t)
    spell = [_equivalent_spelling(o, declared.get(o, [])) for o in _outputs(env_probe)]
    if _outputs(env_probe) and all(s is not None for s in spell):
        reset_state()
        env = target.make(t)
        target.reference_solved(env, t, contents=[_say_all(env, spell)])
        reset_state()
        out["P4_equivalent_spelling"] = _observed(target, env, t)
    else:
        out["P4_equivalent_spelling"] = ProbeObservation(applicable=False,
                                                         note="构造不出等价写法")

    # P5 同一环境连评两次
    reset_state()
    env = _solved_env(target, t)
    a = _observed(target, env, t)
    b = _observed(target, env, t)
    reset_state()
    same = (a.verdict == b.verdict and a.state == b.state and a.raised == b.raised)
    out["P5_repeat"] = ProbeObservation(same, a.state, a.raised,
                                        note=f"两次={a.verdict}/{b.verdict}")

    # P6 预言机内部路径注入失败
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
    restored = target.state(env) == s0
    out["P6_exception"] = ProbeObservation(raised and restored, target.state(env), raised,
                                           note=f"raised={raised} restored={restored}")
    reset_state()

    # P7 换打分顺序（**同一任务**：先「什么都没做」vs 先「参考解做完」）
    #   构造与基础套件 `detectors.inv3_order_independent` **同构**：每轮之前 reset 一次，
    #   一轮之内的两次打分之间**不**清理——否则共享缓存被清掉，缺陷激发不出来。
    def run_order(order):
        res = {}
        for kind in order:
            if kind == "solved":
                e = _solved_env(target, t)
            else:
                e = target.make(t)
                e.user = QuietUser()
                e.reset(task_index=t)
            res[kind] = _observed(target, e, t).verdict
        return res
    reset_state()
    a_ord = run_order(["nothing", "solved"])
    reset_state()
    b_ord = run_order(["solved", "nothing"])
    out["P7_order"] = ProbeObservation(a_ord == b_ord, None, None,
                                       note=f"{a_ord} vs {b_ord}")
    reset_state()

    # P8 换打分顺序（**不同任务**：t 与 t2 谁先被评分）
    #   覆盖「缓存按别的东西（而不是 task id）做键」这类实现：P7 只动同一个任务。
    others = [i for i in target.task_ids() if i != t]
    if others:
        t2 = others[0]

        def run_pair(order):
            res = {}
            for tt in order:
                res[tt] = _observed(target, _solved_env(target, tt), tt).verdict
            return res
        reset_state()
        a_pair = run_pair([t, t2])
        reset_state()
        b_pair = run_pair([t2, t])
        out["P8_order_across_tasks"] = ProbeObservation(a_pair == b_pair, None, None,
                                                        note=f"t={t},t2={t2}｜{a_pair} vs {b_pair}")
        reset_state()
    else:
        out["P8_order_across_tasks"] = ProbeObservation(applicable=False, note="该目标只有一个任务")
    return out


# ── 差分核查 ───────────────────────────────────────────────────────────────

def check_variant(target: Target, tasks: Sequence[int], name: str,
                  fn) -> DifferentialResult:
    """把变体与参考实现做差分，判定其有效性。

    注意 `fn` 会被装到 `target.env_class.calculate_reward` 上；参考实现是该类
    **原本**的 `calculate_reward`（as-shipped，即已修补的那个）。
    """
    cls = target.env_class
    had = "calculate_reward" in cls.__dict__
    orig = cls.__dict__.get("calculate_reward")

    def _restore() -> None:
        if had:
            setattr(cls, "calculate_reward", orig)
        else:
            try:
                delattr(cls, "calculate_reward")   # cls.__dict__ 是 mappingproxy，不能 pop
            except AttributeError:
                pass

    def measure(fn_or_none) -> Dict[int, Dict[str, ProbeObservation]]:
        if fn_or_none is None:
            _restore()
        else:
            setattr(cls, "calculate_reward", fn_or_none)
        try:
            return {t: run_probes(target, t) for t in tasks}
        finally:
            _restore()

    ref = measure(None)
    try:
        var = measure(fn)
    except Exception as e:  # noqa: BLE001
        return DifferentialResult(name, False, None,
                                  f"变体装载/执行即失败：{type(e).__name__}: {e}",
                                  status="load_failed")

    compared, per_probe = 0, {}
    for t in tasks:
        for probe in ref[t]:
            o_ref, o_var = ref[t][probe], var[t].get(probe)
            if not o_ref.applicable or o_var is None:
                continue
            compared += 1
            differ = (o_ref.verdict != o_var.verdict
                      or comparable(o_ref.state) != comparable(o_var.state)
                      or o_ref.raised != o_var.raised)
            if differ:
                per_probe[probe] = f"task {t}：参考 verdict={o_ref.verdict} " \
                                   f"→ 变体 verdict={o_var.verdict}"
                return DifferentialResult(name, True, probe,
                                          f"在探针 {probe} 上与参考实现分区（task {t}）",
                                          compared, per_probe, status=DIFFER)
    return DifferentialResult(name, False, None,
                              f"在全部 {compared} 个探针观测上**未观察到**差别 ⇒ **未定**"
                              f"（探针灵敏度不足，不等于等价；不计入主分母、计入保守分母）",
                              compared, per_probe, status=UNRESOLVED)
