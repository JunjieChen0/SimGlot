"""故障注入：把一个**已知类别的预言机缺陷**装到审计对象上。

每个变体都是鸭子类型的 `calculate_reward(env)`，因此同一套变体既能装在 τ-bench 的
`Env` 上，也能装在合成域的 `MiniEnv` 上——这正是「方法而非个案」的可检验形式。

命名与论文的缺陷类别一一对应：

  C1 state_mutation      重置数据库回放参考答案后**不还原**（τ-bench 的历史实现）
  C2 exception_leak      成功路径会还原，**异常路径泄漏**（try 里抛异常则跳过还原）
  C3 actions_not_restored 还原了 data，忘了 actions
  C4 order_dependent     跨集共享缓存，判定依赖打分顺序
  C5 saturated           恒定返回「通过」
  C6 db_blind            只看输出子串，完全忽略数据库终态
  C7 strict_format       输出匹配不做任何规范化（大小写/千分位/全角都不认）

C0 表示**不注入**（用审计对象自己的实现），是特异性对照。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from . import _paths  # noqa: F401

from tau_bench.types import RESPOND_ACTION_NAME  # noqa: E402


@dataclass
class Info:
    r_actions: Optional[bool] = None
    r_outputs: Optional[bool] = None


@dataclass
class Result:
    reward: float
    info: Info

    # 与 τ-bench 的 RewardResult 同形的便捷读取口（合成域直接读这两个字段）
    @property
    def r_actions(self):
        return self.info.r_actions

    @property
    def r_outputs(self):
        return self.info.r_outputs


def _norm(s: str) -> str:
    """本项目预注册的规范化：NFKC + 去千分位逗号 + 小写。"""
    return unicodedata.normalize("NFKC", str(s)).replace(",", "").lower()


def _respond_contents(env):
    return [str(a.kwargs.get("content", "")) for a in env.actions
            if a.name == RESPOND_ACTION_NAME]


def _check_outputs(env, normalize: bool = True) -> bool:
    outs = list(getattr(env.task, "outputs", []) or [])
    if not outs:
        return True
    contents = _respond_contents(env)
    f = _norm if normalize else (lambda s: str(s))
    for o in outs:
        if not any(f(o) in f(c) for c in contents):
            return False
    return True


def _replay(env) -> str:
    """重置为初始数据、按序回放参考答案，返回参考终态哈希。**调用方负责还原。**"""
    env.data = env.data_load_func()
    for a in env.task.actions:
        if a.name not in getattr(env, "terminate_tools", []):
            env.step(a)
    return env.get_data_hash()


def _snap(env):
    return (env.data, list(env.actions), getattr(env, "user", None))


def _restore(env, snap) -> None:
    env.data, env.actions = snap[0], snap[1]
    if snap[2] is not None:
        env.user = snap[2]


# ── C1 状态污染：重置+回放后不还原（τ-bench 的历史实现，逐字复刻）──────────────
def c1_state_mutation(env):
    data_hash = env.get_data_hash()
    gt = _replay(env)                       # ← 没有还原语句
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ── C2 异常路径泄漏：成功才还原 ───────────────────────────────────────────────
def c2_exception_leak(env):
    data_hash = env.get_data_hash()
    snap = _snap(env)
    try:
        gt = _replay(env)
    finally:
        pass                                # ← 故意空：异常时后面的还原不会执行
    _restore(env, snap)
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ── C3 只还原数据、不还原动作列表 ─────────────────────────────────────────────
def c3_actions_not_restored(env):
    data_hash = env.get_data_hash()
    snap = _snap(env)
    gt = _replay(env)
    env.data = snap[0]                      # ← 数据还原了
    if snap[2] is not None:                 #   动作列表**没有**还原
        env.user = snap[2]
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ── C4 跨集顺序依赖：模块级缓存「首次见到的智能体终态」 ────────────────────────
_ORDER_CACHE: Dict[object, str] = {}


def reset_state() -> None:
    """在每个 (target, defect) 组合开跑前清空注入变体的模块级状态。"""
    _ORDER_CACHE.clear()


def c4_order_dependent(env):
    tid = getattr(env, "task_index", None)
    if tid not in _ORDER_CACHE:
        _ORDER_CACHE[tid] = env.get_data_hash()      # 首次见到的那一集被缓存下来
    data_hash = _ORDER_CACHE[tid]
    snap = _snap(env)
    try:
        gt = _replay(env)
    finally:
        _restore(env, snap)                          # 状态完整性正常，缺陷只在缓存
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


# ── C5 饱和：恒定通过 ────────────────────────────────────────────────────────
def c5_saturated(env):
    return Result(1.0, Info(True, True))


# ── C6 忽略数据库分量 ────────────────────────────────────────────────────────
def c6_db_blind(env):
    r_outputs = _check_outputs(env)
    return Result(1.0 if r_outputs else 0.0, Info(True, r_outputs))


# ── C7 严格匹配：不做任何规范化 ──────────────────────────────────────────────
def c7_strict_format(env):
    data_hash = env.get_data_hash()
    snap = _snap(env)
    try:
        gt = _replay(env)
    finally:
        _restore(env, snap)                          # 状态完整性正常，缺陷只在匹配
    r_actions = data_hash == gt
    r_outputs = _check_outputs(env, normalize=False)
    return Result(1.0 if (r_actions and r_outputs) else 0.0, Info(r_actions, r_outputs))


VARIANTS: Dict[str, Optional[Callable]] = {
    "C0 none (as-shipped)": None,
    "C1 state_mutation": c1_state_mutation,
    "C2 exception_leak": c2_exception_leak,
    "C3 actions_not_restored": c3_actions_not_restored,
    "C4 order_dependent": c4_order_dependent,
    "C5 saturated": c5_saturated,
    "C6 db_blind": c6_db_blind,
    "C7 strict_format": c7_strict_format,
}
