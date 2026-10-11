"""工作包 B：E0 的**预留实现变体库**（held-out implementation variants）。

与 `oracle_audit_kit/oracle_variants.py` 的关系：

  * 该文件里的 `C1…C7` 是**开发变体**（dev）——编写检测器时看着它们写的，
    因此「检测器能抓住它们」不构成泛化证据；
  * 本文件新增**每类两个预留变体**（held-out），在检测器与适配器**冻结之后**才首次运行，
    用来回答真正的问题：检测器抓的是**这一类缺陷**，还是只是**那一个实现**。

术语（按外部建议稿 §4 B2 的措辞）：
  * 这些变体是 **pre-frozen held-out implementation variants**——
    由作者构造并事先保留，**不是**独立第三方创作的未知故障。论文必须这样写，不得抬高。

状态清理的接口约定
------------------
基础套件的 `reset_state()`（`oracle_variants.py`）只清空它自己的 `_ORDER_CACHE`。
基础检测器在每次内层迭代都会调用它。本文件里有状态的变体**把自己的状态也存进
`_ORDER_CACHE`**（用 `("EXT", …)` 前缀做键），于是基础 `reset_state()` 会一并清掉，
无需改动只读的基础套件。这是一处**接口复用**，不是巧合：反过来做就得改基础文件。
"""

from __future__ import annotations

import copy
from typing import Callable, Dict, List, Optional, Tuple

from oracle_audit_kit import _paths  # noqa: F401  只读引导（sys.path → vendored τ-bench）
from oracle_audit_kit.adapters import Target  # noqa: E402
from oracle_audit_kit.oracle_variants import (  # noqa: E402
    Info,
    Result,
    _check_outputs,
    _ORDER_CACHE,
    _replay,
    _restore,
    _snap,
)

from tau_bench.envs.base import consistent_hash, to_hashable  # noqa: E402
from tau_bench.types import RESPOND_ACTION_NAME  # noqa: E402


def _terminate(env) -> List[str]:
    return list(getattr(env, "terminate_tools", []) or [])


def _first_partition(env) -> Optional[str]:
    if isinstance(env.data, dict) and env.data:
        return next(iter(env.data))
    return None


def _partition_hash(env, name: str) -> str:
    if isinstance(env.data, dict) and name in env.data:
        return consistent_hash(to_hashable(env.data[name]))
    return env.get_data_hash()


# ═══════════════════════════════════════════════════════════════════════════
# C1 状态未恢复 —— 预留变体
# ═══════════════════════════════════════════════════════════════════════════

def g1_replay_in_place(env):
    """就地回放：**不**先换成干净数据，直接在活对象上跑参考动作。

    于是 `_restore` 把「同一个已经被改过的对象」赋回去——看似还原，实则没有。
    与开发变体 C1 的区别：C1 是「换干净数据 → 不还原」，本条是「根本不换」，
    两条路径的可见症状相同，但**实现与代码形状完全不同**。
    """
    data_hash = env.get_data_hash()
    snap = _snap(env)                       # snap[0] 就是 env.data 本身
    for a in env.task.actions:
        if a.name not in _terminate(env):
            env.step(a)                     # 原地改写 env.data 的嵌套结构
    gt = env.get_data_hash()
    _restore(env, snap)                     # 赋回同一个引用
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


def g1_partial_partition(env):
    """只还原「开发者以为会被改到的那些分区」，其余分区留在参考终态。

    现实成因：作者知道自己的工具只写 orders，于是快照/还原时只处理 orders；
    一旦某条任务的参考动作也动了 users，污染就留下来了。
    """
    if not isinstance(env.data, dict):
        return _reference_oracle(env)             # 非分区式数据：不适用 ⇒ 退化为「不注入」
    keep = [k for k in env.data if k != "orders"] or list(env.data)
    snap = {k: copy.deepcopy(env.data[k]) for k in keep}
    data_hash = env.get_data_hash()
    gt = _replay(env)
    for k in keep:                                # ← orders 没有被还原
        env.data[k] = snap[k]
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ═══════════════════════════════════════════════════════════════════════════
# C2 异常路径未恢复 —— 预留变体
# ═══════════════════════════════════════════════════════════════════════════

def g2_raise_mid_replay(env):
    """参考动作**执行到一半**失败：异常被就地吞掉并直接返回，状态留在半途。

    与开发变体 C2（finally 里故意留空）的区别：C2 只在**外部注入**的异常下泄漏，
    本条在**它自己**的执行路径上失败，连异常都不外传（INV-4 的"必须外传"也一并违反）。
    """
    data_hash = env.get_data_hash()
    snap = _snap(env)
    env.data = env.data_load_func()                 # 已经开始重置
    acts = [a for a in env.task.actions if a.name not in _terminate(env)]
    try:
        for i, a in enumerate(acts):
            if i == max(1, len(acts) // 2):
                raise RuntimeError("reference action failed halfway")
            env.step(a)
    except Exception:  # noqa: BLE001
        return Result(0.0, Info(False, None))       # ← 不还原、不外传
    gt = env.get_data_hash()
    _restore(env, snap)
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


def g2_cleanup_only_expected(env):
    """清理只写在 `except (KeyError, IndexError)` 里——「预料之中」的失败才还原。

    任何其它异常（包括上游注入的 RuntimeError）直接外传且**不还原**。
    与 C2 的区别：C2 是还原语句放错位置，本条是还原逻辑**只覆盖一部分异常类型**。
    """
    data_hash = env.get_data_hash()
    snap = _snap(env)
    try:
        gt = _replay(env)
    except (KeyError, IndexError):
        gt = data_hash
        _restore(env, snap)
    # 其它异常不在此还原：异常向外传播时 env.data / env.actions 停在半途
    _restore(env, snap)
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ═══════════════════════════════════════════════════════════════════════════
# C3 动作历史未恢复 —— 预留变体
# ═══════════════════════════════════════════════════════════════════════════

def g3_partial_truncate(env):
    """「清理」动作列表时**只删掉最后一条**，剩下的回放动作留在里面。

    与 C3（压根不管动作列表）的区别：本条**确实执行了清理语句**，只是清得不完整。
    """
    data_hash = env.get_data_hash()
    snap = _snap(env)
    gt = _replay(env)
    env.data = snap[0]
    if snap[2] is not None:
        env.user = snap[2]
    if env.actions:
        del env.actions[-1]                     # ← 以为删掉回放追加的那些就够了
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


def g3_list_alias(env):
    """快照时**存的是列表别名而不是副本**，回放往同一个列表里追加。

    还原时把别名赋回去 = 什么都没还原。与 C3 的可见症状相同，
    但成因是别名共享——这正是「浅拷贝陷阱」那一类实现缺陷。
    """
    data_hash = env.get_data_hash()
    snap_actions = env.actions                    # ← 别名
    snap_data, snap_user = env.data, getattr(env, "user", None)
    gt = _replay(env)                             # 追加进同一个列表对象
    env.data = snap_data
    if snap_user is not None:
        env.user = snap_user
    env.actions = snap_actions                    # 赋回别名
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ═══════════════════════════════════════════════════════════════════════════
# C4 顺序 / 缓存依赖 —— 预留变体
# ═══════════════════════════════════════════════════════════════════════════

def g4_keyless_cache(env):
    """缓存键里**没有任务标识**：一个全局槽位，谁先来谁定调。

    与 C4（按 task_index 建键，所以只在同一任务内部跨态泄漏）的区别：
    本条的污染**跨任务**传播。状态完整性本身是好的，缺陷只在缓存键。
    """
    key = ("EXT", "g4")
    if key not in _ORDER_CACHE:
        _ORDER_CACHE[key] = env.get_data_hash()
    data_hash = _ORDER_CACHE[key]
    snap = _snap(env)
    try:
        gt = _replay(env)
    finally:
        _restore(env, snap)
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


def g4_prev_verdict_reuse(env):
    """第二次起**直接返回上一次的判定**（以为同一任务会连评）。

    状态完整性完全正常（回放前后都还原），缺陷只在判定被跨集复用。
    与 C4 的区别：C4 复用的是一个**散列**，本条复用的是**上一次的最终判定**。
    """
    key = ("EXT", "g4v")
    if key in _ORDER_CACHE:
        return Result(float(_ORDER_CACHE[key]), Info(None, None))
    data_hash = env.get_data_hash()
    snap = _snap(env)
    try:
        gt = _replay(env)
    finally:
        _restore(env, snap)
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    reward = 1.0 if (r_actions and r_outputs) else 0.0
    _ORDER_CACHE[key] = reward
    return Result(reward, Info(r_actions, r_outputs))


# ═══════════════════════════════════════════════════════════════════════════
# C5 恒通过 —— 预留变体
# ═══════════════════════════════════════════════════════════════════════════

def g5_dead_branch(env):
    """先置成功再走分支，但分支条件写错，永远进不去 ⇒ 恒通过。

    与 C5（直接 `return 1.0`）的区别：本条**看起来有判定逻辑**，
    静态阅读时会以为它在检查 outputs。
    """
    ok = True
    if len(env.task.actions) < 0:            # ← 恒假
        ok = _check_outputs(env)
    return Result(1.0 if ok else 0.0, Info(True, True))


def g5_exception_swallow(env):
    """整段包在 try 里，**任何异常都当作通过**。

    正常路径上它是正确的；缺陷只在异常路径——而且是**它自己吞掉异常**。
    与 C5 的区别：本条在无异常的 episode 上与正确实现完全一致。
    """
    data_hash = env.get_data_hash()
    snap = _snap(env)
    try:
        gt = _replay(env)
        _restore(env, snap)
        r_actions = data_hash == gt
        r_outputs = _check_outputs(env)
        return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))
    except Exception:  # noqa: BLE001
        _restore(env, snap)
        return Result(1.0, Info(None, None))          # ← 出错即通过


# ═══════════════════════════════════════════════════════════════════════════
# C6 忽略数据库 —— 预留变体
# ═══════════════════════════════════════════════════════════════════════════

def g6_respond_only(env):
    """只检查「智能体有没有给出结束回复」，完全不看回复内容与数据库。

    与 C6（只看输出子串）的区别：本条连输出内容都不看，只看**有没有回复这个动作**。
    """
    ok = any(a.name == RESPOND_ACTION_NAME for a in env.actions)
    return Result(1.0 if ok else 0.0, Info(True, ok))


def g6_partial_partitions(env):
    """只比对**一个**数据分区，其余分区改错了也看不出来。

    与 C6（完全不看库）的区别：本条确实比对了库，只是比对得不全。
    """
    part = _first_partition(env)
    snap = _snap(env)
    data_hash = env.get_data_hash()
    cur_part = _partition_hash(env, part) if part else data_hash
    try:
        gt = _replay(env)
        gt_part = _partition_hash(env, part) if part else gt
    finally:
        _restore(env, snap)
    r_actions = cur_part == gt_part
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ═══════════════════════════════════════════════════════════════════════════
# C7 输出匹配违约 —— 预留变体
# ═══════════════════════════════════════════════════════════════════════════

def _check_outputs_partial(env, mode: str) -> bool:
    """部分规范化：只做一半的等价性判定。"""
    import unicodedata
    outs = list(getattr(env.task, "outputs", []) or [])
    if not outs:
        return True
    contents = [str(a.kwargs.get("content", "")) for a in env.actions
                if a.name == RESPOND_ACTION_NAME]
    if mode == "case_only":            # 认大小写，但**不认**千分位逗号
        f = lambda s: str(s).lower()   # noqa: E731
    elif mode == "comma_only":         # 认千分位逗号，但**不认**大小写
        f = lambda s: str(s).replace(",", "")   # noqa: E731
    elif mode == "nfkc_only":          # 只做 NFKC，不剥逗号也不小写
        f = lambda s: unicodedata.normalize("NFKC", str(s))   # noqa: E731
    else:
        raise ValueError(mode)
    return all(any(f(o) in f(c) for c in contents) for o in outs)


def _g7(env, mode: str):
    data_hash = env.get_data_hash()
    snap = _snap(env)
    try:
        gt = _replay(env)
    finally:
        _restore(env, snap)
    r_actions = data_hash == gt
    r_outputs = _check_outputs_partial(env, mode)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


def g7_case_only(env):
    """只做大小写归一，拒绝千分位写法 ⇒ 契约允许的等价表达被拒。"""
    return _g7(env, "case_only")


def g7_comma_only(env):
    """只剥千分位逗号，不做大小写归一 ⇒ 另一种半吊子规范化。"""
    return _g7(env, "comma_only")


# ═══════════════════════════════════════════════════════════════════════════
# 目录
# ═══════════════════════════════════════════════════════════════════════════

def _reference_oracle(env):
    """**不注入**：按已修补的语义打分（快照 → 回放 → finally 还原）。

    只用作「该变体在这个 target 上不适用」的退化路径。注意**不能**在这里调用
    `env.calculate_reward()`——注入时那个属性已经指向本变体自己，会无限递归。
    """
    data_hash = env.get_data_hash()
    snap = _snap(env)
    try:
        gt = _replay(env)
    finally:
        _restore(env, snap)
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


#: 缺陷类 → (开发变体名, [(预留变体名, 函数, 一句话描述), ...])
HOLDOUT: Dict[str, Tuple[str, List[Tuple[str, Callable, str]]]] = {
    "state_mutation": ("C1_state_mutation", [
        ("G1a_replay_in_place", g1_replay_in_place,
         "就地回放，还原的是同一个已被改写过的对象"),
        ("G1b_partial_partition", g1_partial_partition,
         "只还原除 orders 外的分区，orders 留在参考终态"),
    ]),
    "exception_leak": ("C2_exception_leak", [
        ("G2a_raise_mid_replay", g2_raise_mid_replay,
         "参考动作执行到一半自爆，异常被吞、状态不还原"),
        ("G2b_cleanup_only_expected", g2_cleanup_only_expected,
         "还原只覆盖 KeyError/IndexError，其余异常外传且不还原"),
    ]),
    "actions_not_restored": ("C3_actions_not_restored", [
        ("G3a_partial_truncate", g3_partial_truncate,
         "清理动作列表时只删最后一条"),
        ("G3b_list_alias", g3_list_alias,
         "快照存的是列表别名，还原别名等于没还原"),
    ]),
    "order_dependent": ("C4_order_dependent", [
        ("G4a_keyless_cache", g4_keyless_cache,
         "缓存键不含任务标识，污染跨任务传播"),
        ("G4b_prev_verdict_reuse", g4_prev_verdict_reuse,
         "第二次起直接复用上一次的最终判定"),
    ]),
    "saturated": ("C5_saturated", [
        ("G5a_dead_branch", g5_dead_branch,
         "先置成功再走一个恒假分支 ⇒ 恒通过"),
        ("G5b_exception_swallow", g5_exception_swallow,
         "整段包 try，任何异常都判通过"),
    ]),
    "db_blind": ("C6_db_blind", [
        ("G6a_respond_only", g6_respond_only,
         "只检查有没有给出结束回复"),
        ("G6b_partial_partitions", g6_partial_partitions,
         "只比对第一个数据分区"),
    ]),
    "strict_format": ("C7_strict_format", [
        ("G7a_case_only", g7_case_only,
         "只归一大小写，拒绝千分位写法"),
        ("G7b_comma_only", g7_comma_only,
         "只剥千分位逗号，不做大小写归一"),
    ]),
}

#: 扁平索引：变体名 → (缺陷类, 函数, 描述, 是否预留)
CATALOG: Dict[str, Tuple[str, Callable, str, bool]] = {}
for _cls, (_dev, _h) in HOLDOUT.items():
    for _n, _fn, _d in _h:
        CATALOG[_n] = (_cls, _fn, _d, True)
del _cls, _dev, _h, _n, _fn, _d


def load_target_variants() -> Dict[str, Optional[Callable]]:
    """把基础套件的 C0–C7 与本文件的预留变体合成一张注入表（名字 → 可调用/None）。"""
    from oracle_audit_kit.oracle_variants import VARIANTS as BASE
    out: Dict[str, Optional[Callable]] = dict(BASE)
    for name, (_cls, fn, _d, _hold) in CATALOG.items():
        out[name] = fn
    return out
