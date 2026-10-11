"""审计对象（target）：一个「测试预言机」连同它所属的环境族。

套件对 target 的要求很小，只有四条鸭子类型契约：

  make(task_index)        → 一个干净环境
  state(env)              → 被判分状态的**内容签名**（可比较）
  oracle(env, task_index) → 给该环境打分，返回 Verdict
  env_class               → 预言机所在类（故障注入时在其中替换 calculate_reward）

有意做成**不依赖 τ-bench 的形状**：`TauBenchTarget` 与 `MiniTarget` 共享同一套
检测器，用以证明这套方法不是为某一个基准定制的。
"""

from __future__ import annotations

import dataclasses  # noqa: F401  （保留：审计对象为 dataclass 风格）
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import _paths  # noqa: F401

from tau_bench.envs.base import to_hashable, consistent_hash  # noqa: E402
from tau_bench.envs.retail.env import MockRetailDomainEnv  # noqa: E402
from tau_bench.envs.airline.env import MockAirlineDomainEnv  # noqa: E402
from tau_bench.types import Action, RESPOND_ACTION_NAME  # noqa: E402


@dataclass
class Verdict:
    """预言机对一集的判定。"""
    reward: float
    r_actions: Optional[bool] = None
    r_outputs: Optional[bool] = None

    @property
    def solved(self) -> bool:
        return self.reward == 1.0


class StopUser:
    """立刻道别的占位模拟器：智能体的第一条 respond 就会在观察里看到 ###STOP###。

    审计不需要模型——会话的**结束路径**才是要害，这条路径由 env.step 触发。
    """

    def __init__(self, reply: str = "Thanks, that's all I needed. ###STOP###") -> None:
        self.reply = reply

    def reset(self, instruction=None) -> str:  # noqa: ANN001
        return instruction or "hello"

    def step(self, content) -> str:  # noqa: ANN001
        return self.reply

    def get_total_cost(self) -> float:
        return 0.0


class QuietUser:
    """永不结束会话的占位模拟器：便于把环境置入某个终态而**不触发**预言机。

    与 StopUser 的区别很要紧：`_solved_env` 要构造「已被做对」的环境，若用 StopUser，
    respond 会立刻结束会话并**顺带**调用一次预言机——那会把审计对象的状态搅乱，
    让「顺序无关」这类检测测到别的东西。
    """

    def reset(self, instruction=None) -> str:  # noqa: ANN001
        return instruction or "hello"

    def step(self, content) -> str:  # noqa: ANN001
        return "Sure, anything else?"

    def get_total_cost(self) -> float:
        return 0.0


class Target:
    """审计对象的基类。子类只需给出 make/state/oracle 与 env_class。"""

    name: str = "target"
    respond: str = "respond"

    def make(self, task_index: int) -> Any:  # pragma: no cover
        raise NotImplementedError

    def state(self, env) -> Any:  # pragma: no cover
        raise NotImplementedError

    def oracle(self, env, task_index: int) -> Verdict:  # pragma: no cover
        raise NotImplementedError

    # ── 以下由基类提供，子类一般不需要改写 ──────────────────────────────────

    def reference_actions(self, env) -> List[Action]:
        """参考答案里的**工具**动作（不含 respond，也不含终止型工具）。"""
        return [a for a in env.task.actions
                if a.name != self.respond and a.name not in getattr(env, "terminate_tools", [])]

    def has_writes(self, env) -> bool:
        return bool(self.reference_actions(env))

    def task_ids(self) -> List[int]:
        raise NotImplementedError

    def accepted_variants(self, task_index: int) -> Dict[str, List[str]]:
        """该 target **声明**接受的等价写法：{要求的输出: [可接受的写法, ...]}。

        默认空 = 「除规范化形式外什么都不接受」。这是**规格**，不是推断：
        一个预言机只能按它自己声明接受集来判「该接受而没接受」。
        """
        return {}

    # ── 驱动器 ─────────────────────────────────────────────────────────────

    def do_nothing(self, env, task_index: int, contents: Sequence[str] = ()) -> None:
        """把环境驱动到「什么正经事都没做」的会话结束态（会真实触发结束路径）。"""
        env.user = StopUser()
        env.reset(task_index=task_index)
        for c in (contents or ["All done, goodbye!"]):
            env.step(Action(name=self.respond, kwargs={"content": c}))

    def reference_solved(self, env, task_index: int,
                         contents: Sequence[str] = ()) -> None:
        """把环境驱动到「做对了参考写操作」的会话结束态。"""
        env.user = StopUser()
        env.reset(task_index=task_index)
        for a in self.reference_actions(env):
            env.step(Action(name=a.name, kwargs=dict(a.kwargs)))
        for c in (contents or ["All done, goodbye!"]):
            env.step(Action(name=self.respond, kwargs={"content": c}))

    def expected_terminal_hash(self, env, task_index: int) -> str:
        """**独立重建**智能体自己的终态：干净数据 + 按序施加它做过的工具动作。

        这就是 `db_replay.py` 的同一个想法，只是这里不需要落盘轨迹——动作还在内存里。
        """
        clean = env.data_load_func()
        for a in env.actions:
            if a.name == self.respond or a.name in getattr(env, "terminate_tools", []):
                continue
            tool = env.tools_map.get(a.name)
            if tool is None:
                continue
            try:
                tool.invoke(data=clean, **a.kwargs)
            except Exception:  # noqa: BLE001  与 τ-bench 的容错口径一致
                pass
        return consistent_hash(to_hashable(clean))


# ═══════════════════════════════════════════════════════════════════════════
# τ-bench（真实基准的预言机）
# ═══════════════════════════════════════════════════════════════════════════

class TauBenchTarget(Target):
    """τ-bench 的 `Env.calculate_reward()` —— 本项目的头号缺陷正是在这里。

    注意审计对象是**基准自带的预言机**，不是本项目的 `harness.scoring.score`：
    后者已经带 try/finally 修补，把它当成「正确的参照」是没有意义的。
    """

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.name = f"tau-bench/{domain}"
        self.respond = RESPOND_ACTION_NAME
        self._cls = {"retail": MockRetailDomainEnv, "airline": MockAirlineDomainEnv}[domain]

    @property
    def env_class(self):
        return self._cls

    def make(self, task_index: int):
        return self._cls(user_strategy="human", task_split="test", task_index=task_index)

    def state(self, env):
        return (env.get_data_hash(),
                tuple(repr((a.name, a.kwargs)) for a in env.actions),
                id(getattr(env, "user", None)))

    def oracle(self, env, task_index: int) -> Verdict:
        res = env.calculate_reward()
        info = getattr(res, "info", None)
        return Verdict(
            reward=float(res.reward),
            r_actions=getattr(info, "r_actions", None),
            r_outputs=getattr(info, "r_outputs", None),
        )

    def task_ids(self) -> List[int]:
        env = self.make(0)
        return list(range(len(env.tasks)))


# ═══════════════════════════════════════════════════════════════════════════
# 合成域（证明套件不依赖 τ-bench 的形状）
# ═══════════════════════════════════════════════════════════════════════════

class _Tool:
    def __init__(self, fn: Callable[..., str]) -> None:
        self.fn = fn

    def invoke(self, data, **kwargs) -> str:  # noqa: ANN003
        return self.fn(data, **kwargs)


def _set_value(data, key, value):  # noqa: ANN001
    data["kv"][key] = value
    return f"set {key}={value}"


def _del_value(data, key):  # noqa: ANN001
    data["kv"].pop(key, None)
    return f"deleted {key}"


@dataclass
class MiniTask:
    id: int
    instruction: str
    actions: List[Action]
    outputs: List[str]
    initial: Dict[str, Any] = None          # 该任务的初始键值对


@dataclass
class _MiniObs:
    observation: str
    reward: float
    done: bool


@dataclass
class _MiniResult:
    reward: float
    r_actions: bool
    r_outputs: bool

    @property
    def info(self):
        return self


class MiniEnv:
    """~50 行的最小「数据库 + 工具 + 预言机」，接口与 τ-bench 的 Env 同形。"""

    terminate_tools: List[str] = []

    def __init__(self, task_index: int, tasks: List[MiniTask]) -> None:
        self.tasks = tasks
        self.task_index = task_index
        self.task = tasks[task_index]
        self.data_load_func = lambda: {"kv": dict(self.task.initial or {})}
        self.data = self.data_load_func()
        self.actions: List[Action] = []
        self.user = None
        self.tools_map = {"set_value": _Tool(_set_value), "del_value": _Tool(_del_value)}

    def get_data_hash(self) -> str:
        return consistent_hash(to_hashable(self.data))

    def reset(self, task_index: int | None = None):
        """与 τ-bench 的 Env.reset 同形：换任务、重置数据与动作列表。"""
        if task_index is not None:
            self.task_index = task_index
        self.task = self.tasks[self.task_index]
        self.data = self.data_load_func()
        self.actions = []
        if self.user is not None:
            self.user.reset(instruction=self.task.instruction)
        return _MiniObs(self.task.instruction, 0.0, False)

    def step(self, action: Action):
        self.actions.append(action)
        done = False
        if action.name == RESPOND_ACTION_NAME:
            obs = self.user.step(action.kwargs["content"]) if self.user else "###STOP###"
            done = "###STOP###" in obs
        elif action.name in self.tools_map:
            try:
                obs = self.tools_map[action.name].invoke(data=self.data, **action.kwargs)
            except Exception as e:  # noqa: BLE001
                obs = f"Error: {e}"
        else:
            obs = f"Unknown action {action.name}"
        reward = 0.0
        if done:
            reward = self.calculate_reward().reward
        return _MiniObs(obs, reward, done)

    # 正确的参考实现：与修补后的 τ-bench 同构（重置 → 回放 → **finally 还原**）
    def calculate_reward(self):
        data_hash = self.get_data_hash()
        snap_data, snap_actions, snap_user = self.data, list(self.actions), self.user
        try:
            self.data = self.data_load_func()
            for a in self.task.actions:
                if a.name not in self.terminate_tools:
                    self.step(a)
            gt = self.get_data_hash()
        finally:
            self.data, self.actions, self.user = snap_data, snap_actions, snap_user
        r_actions = data_hash == gt
        r_outputs = True
        for out in self.task.outputs:
            hit = any(a.name == RESPOND_ACTION_NAME
                      and out.lower() in str(a.kwargs.get("content", "")).lower().replace(",", "")
                      for a in self.actions)
            if not hit:
                r_outputs = False
        reward = 1.0 if (r_actions and r_outputs) else 0.0
        return _MiniResult(reward, r_actions, r_outputs)


class MiniTarget(Target):
    """合成域：自带 4 条任务，其中两条声明了等价写法（供「该接受而没接受」探针使用）。"""

    name = "synthetic/tiny"

    def __init__(self) -> None:
        T = MiniTask
        self._tasks = [
            # 0：一次写 + 一个数字型输出（供格式化容忍度探针使用）
            T(0, "set k1 to 1", [Action(name="set_value", kwargs={"key": "k1", "value": 1})],
              ["4810"]),
            # 1：两次写 + 一个文本输出，声明一条等价写法
            T(1, "set k2/k3",
              [Action(name="set_value", kwargs={"key": "k2", "value": "a"}),
               Action(name="set_value", kwargs={"key": "k3", "value": "b"})],
              ["DONE"]),
            # 2：一次真实删除（有写操作、**无输出**）——负对照 ① 用
            T(2, "delete k9", [Action(name="del_value", kwargs={"key": "k9"})], [],
              initial={"k9": 7}),
            # 3：无写操作（不参与写任务取样）
            T(3, "nothing", [], []),
        ]
        self._variants = {0: {"4810": ["4,810", "4 810"]}, 1: {"DONE": ["Done", "done"]}}

    @property
    def env_class(self):
        return MiniEnv

    def make(self, task_index: int) -> MiniEnv:
        return MiniEnv(task_index, self._tasks)

    def state(self, env):
        return (env.get_data_hash(),
                tuple(repr((a.name, a.kwargs)) for a in env.actions),
                id(getattr(env, "user", None)))

    def oracle(self, env, task_index: int) -> Verdict:
        res = env.calculate_reward()
        return Verdict(float(res.reward), bool(res.r_actions), bool(res.r_outputs))

    def task_ids(self) -> List[int]:
        return list(range(len(self._tasks)))

    def accepted_variants(self, task_index: int) -> Dict[str, List[str]]:
        return self._variants.get(task_index, {})

    # 合成域的「参考解」对超出声明接受集的写法不做要求，故这里复用基类实现


TARGETS: Dict[str, Callable[[], Target]] = {
    "tau-bench/retail": lambda: TauBenchTarget("retail"),
    "tau-bench/airline": lambda: TauBenchTarget("airline"),
    "synthetic/tiny": lambda: MiniTarget(),
}
