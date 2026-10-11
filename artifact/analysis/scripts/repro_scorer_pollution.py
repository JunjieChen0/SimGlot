#!/usr/bin/env python3
"""会话结束时的数据库污染：**最小可复现反证** + **回归测试**。

## 缺陷

`vendor/tau-bench/tau_bench/envs/base.py` 的 `Env.calculate_reward()`：

    data_hash = self.get_data_hash()       # ① 读智能体真实终态
    self.data = self.data_load_func()      # ② 重置为初始数据
    for action in self.task.actions:       # ③ 回放**参考答案**动作
        if action.name not in self.terminate_tools:
            self.step(action)
    gt_data_hash = self.get_data_hash()    # ④ 参考终态
    # ⑤ 从来没有把 self.data 还原成 ① 的状态

它在会话结束（`###STOP###`）时被 `Env.step()` 调用。于是 `run_episode()` 在
`agent.solve()` 之后调用的 `harness.scoring.score(env)` 里
`agent_hash = env.get_data_hash()` 读到的是 ③ 之后的**参考答案状态**，
与同一函数随后算出的 `gt_hash` 恒等 → `r_actions` 恒为 True。

**后果**：以 `conversation_done` 结束的 episode，其归档 DB / Full 标签被抬高；
以 `max_steps` 结束的（未走该路径）标签是对的。

## 本脚本

1. `reproduce()`：构造「智能体什么都不改就结束会话」的格，展示打分路径给出
   `r_actions=True`（假通过），而**独立重放**的终态哈希表明它并未完成任务。
2. `regression()`：把 `calculate_reward` 改成算完还原数据后，同一场景给出
   `r_actions=False`（正确）。这就是修复方案与它的回归测试。

## 退出码契约（D21）

回归检查**不是只打印 ✓/✗**：任何一项断言失败，`main()` 返回**非零**，
`offline_repro.sh` 的 `set -e` 会就此停下——否则「修补被回滚」这件事会悄无声息地
通过整条发布流水线。本节覆盖四种场景：

| 场景 | 期望 |
|---|---|
| 已修补代码 + 什么都没写就结束会话 | `r_actions = False`，退出码 0 |
| 参考写操作确实做对 | 参考路径返回 True，且事后安全重评分同样为 True |
| 参考路径内部抛异常 | 异常向外传播（不被 `finally` 吞掉），且 `env.data` 已还原 |
| 有人把旧的污染逻辑放回来 | 回归断言失败 → **退出码非零** |

最后一种由 `scripts/check_regression_failure_propagation.py` 用**内存注入**验证
（外部注入 `buggy_calculate_reward` 后，本脚本必须非零退出）。

用法：python3 scripts/repro_scorer_pollution.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "tau-bench"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _offline  # noqa: E402,F401  离线分析引导：缺 litellm/openai 时装禁用桩

from tau_bench.envs.base import Env, to_hashable, consistent_hash  # noqa: E402
from tau_bench.envs.retail.env import MockRetailDomainEnv  # noqa: E402
from tau_bench.types import (  # noqa: E402
    Action, RESPOND_ACTION_NAME, RewardActionInfo, RewardOutputInfo, RewardResult)

from harness.scoring import score  # noqa: E402

OUT = ROOT / "results" / "scorer_pollution_repro.txt"
LINES: list[str] = []


def P(s: str = "") -> None:
    LINES.append(s)
    print(s)


class _StopUser:
    """用户立刻道别：智能体第一条 respond 就会在观察里看到 ###STOP### 并结束会话。"""

    def reset(self, instruction=None):  # noqa: ANN001
        return instruction or "hello"

    def step(self, content):  # noqa: ANN001
        return "Thanks, that's all I needed. ###STOP###"

    def get_total_cost(self) -> float:
        return 0.0


def do_nothing_episode(task_index: int) -> MockRetailDomainEnv:
    """一个「只说话、不做任何写操作」的 episode，走真实的 env.step 结束路径。"""
    env = MockRetailDomainEnv(user_strategy="human", task_split="test",
                              task_index=task_index)
    env.user = _StopUser()
    env.reset(task_index=task_index)
    env.step(Action(name=RESPOND_ACTION_NAME, kwargs={"content": "All done, goodbye!"}))
    return env


def true_terminal_hash(task_index: int, tool_actions: list[tuple[str, dict]]) -> str:
    """独立重放：干净数据 + 按序施加智能体真实工具调用。"""
    env = MockRetailDomainEnv(user_strategy="human", task_split="test",
                              task_index=task_index)
    env.data = env.data_load_func()
    for name, kw in tool_actions:
        try:
            env.tools_map[name].invoke(data=env.data, **kw)
        except Exception:
            pass
    return env.get_data_hash()


def gt_hash(task_index: int) -> str:
    env = MockRetailDomainEnv(user_strategy="human", task_split="test",
                              task_index=task_index)
    env.data = env.data_load_func()
    for a in env.task.actions:
        if a.name not in env.terminate_tools:
            env.tools_map[a.name].invoke(data=env.data, **a.kwargs)
    return env.get_data_hash()


def buggy_calculate_reward(env: Env):
    """**原版**的逐字复现：算完**不还原**，`env.data` 留在参考答案终态。

    只在第 1 节使用，用来展示归档数据是怎么被污染的。补丁已提交在
    `vendor/tau-bench/tau_bench/envs/base.py`（D17），故这里显式重放旧行为，
    使反证在任何时候都能重跑。
    """
    data_hash = env.get_data_hash()
    reward = 1.0
    actions = [a for a in env.task.actions if a.name != RESPOND_ACTION_NAME]
    env.data = env.data_load_func()                 # 重置
    for action in env.task.actions:                 # 回放参考答案
        if action.name not in env.terminate_tools:
            env.step(action)
    gt_data_hash = env.get_data_hash()
    info = RewardActionInfo(
        r_actions=data_hash == gt_data_hash, gt_data_hash=gt_data_hash
    )
    if not info.r_actions:
        reward = 0.0
    if len(env.task.outputs) > 0:
        r_outputs = 1.0
        outputs = {}
        for output in env.task.outputs:
            found = any(
                a.name == RESPOND_ACTION_NAME
                and output.lower() in a.kwargs["content"].lower().replace(",", "")
                for a in env.actions
            )
            outputs[output] = found
            if not found:
                r_outputs = 0.0
                reward = 0.0
        info = RewardOutputInfo(r_outputs=r_outputs, outputs=outputs)
    return RewardResult(reward=reward, info=info, actions=actions)   # ← 没有还原


FAILURES: list[str] = []


def check(cond: bool, ok: str, bad: str) -> None:
    """回归断言：失败要**留下来**，最后变成非零退出码（只打印红叉是不够的）。"""
    if cond:
        P(f"  ✓ {ok}")
    else:
        FAILURES.append(bad)
        P(f"  ✗ {bad}")


def reference_episode(task_index: int) -> MockRetailDomainEnv:
    """智能体**做对了**参考写操作，再以会话结束收尾（触发 calculate_reward）。"""
    env = MockRetailDomainEnv(user_strategy="human", task_split="test",
                              task_index=task_index)
    env.user = _StopUser()
    env.reset(task_index=task_index)
    for a in env.task.actions:
        if a.name not in env.terminate_tools:
            env.step(Action(name=a.name, kwargs=dict(a.kwargs)))
    env.step(Action(name=RESPOND_ACTION_NAME, kwargs={"content": "All done, goodbye!"}))
    return env


def main() -> int:
    # 选一个有真实写操作、且参考答案确实会改变数据库的任务
    tasks = []
    for idx in range(len(__import__("tau_bench.envs.retail.tasks_test",
                                    fromlist=["TASKS_TEST"]).TASKS_TEST)):
        e = MockRetailDomainEnv(user_strategy="human", task_split="test", task_index=idx)
        ref_write = [a for a in e.task.actions if a.name not in e.terminate_tools]
        if not ref_write:
            continue
        clean = e.data_load_func()
        before = consistent_hash(to_hashable(clean))   # 先取初始态哈希，再施加参考动作
        e.data = clean
        for a in ref_write:
            e.tools_map[a.name].invoke(data=e.data, **a.kwargs)
        if e.get_data_hash() != before:
            tasks.append(idx)
        if len(tasks) >= 4:
            break

    P("=" * 82)
    P("会话结束时的数据库污染 · 最小反证与回归测试")
    P("=" * 82)
    P(f"\n  选用任务（参考答案会真实改写数据库）：{tasks}")

    P("\n── 1. 反证：智能体**一个写操作都没做**，直接道别结束会话 ──")
    P(f"  {'task':<6}{'真实重放终态 == 参考终态':>26}{'原版路径 r_actions':>20}{'原版路径 reward':>18}")
    orig_cr = Env.calculate_reward
    try:
        Env.calculate_reward = lambda self: buggy_calculate_reward(self)
        for t in tasks:
            env = do_nothing_episode(t)
            got = score(env, task_id=t)
            tgt = gt_hash(t)
            truth = true_terminal_hash(t, [])
            P(f"  {t:<6}{str(truth == tgt):>26}{str(got['r_actions']):>20}"
              f"{got['reward']:>18.1f}")
    finally:
        Env.calculate_reward = orig_cr
    P("\n  读法：真实重放一致为 False（什么都没做当然不等于参考答案），")
    P("        但原版路径给的 r_actions 全是 True —— 这就是归档数据的污染来源。")

    P("\n── 2. 对照：同一条轨迹若以 max_steps 结束（不触发 calculate_reward） ──")
    for t in tasks[:2]:
        env = MockRetailDomainEnv(user_strategy="human", task_split="test", task_index=t)
        env.user = _StopUser()
        env.reset(task_index=t)
        got = score(env, task_id=t)          # 未走 env.step 的结束路径
        P(f"  task {t}: r_actions = {got['r_actions']}（应为 False，因为没做任何写操作）")

    P("\n── 3. 回归测试：现行（已修补）的 calculate_reward ──")
    P("     断言：什么都没写就结束会话，r_actions 必须为 False。")
    for t in tasks:
        env = do_nothing_episode(t)
        got = score(env, task_id=t)
        check(got["r_actions"] is False,
              f"task {t}: r_actions = {got['r_actions']}（应为 False）",
              f"task {t}: r_actions = {got['r_actions']}，应为 False —— 污染回归了")

    P("\n── 3b. 正向控制：智能体确实做对了参考写操作 ──")
    P("     断言：参考路径给 1.0，且事后读 env.data 的安全重评分给出同一个奖励")
    P("     （若 finally 没有还原，这里会读到参考终态而「碰巧」也通过；")
    P("       故同时核对 env.data 已回到智能体自己的终态）")
    for t in tasks[:2]:
        env = reference_episode(t)
        written = true_terminal_hash(t, [(a.name, dict(a.kwargs))
                                         for a in env.task.actions
                                         if a.name not in env.terminate_tools])
        res = env.calculate_reward()
        after = env.get_data_hash()
        got = score(env, task_id=t)
        check(res.reward == 1.0,
              f"task {t}: 参考路径 reward = {res.reward}（做对了，应为 1.0）",
              f"task {t}: 参考路径 reward = {res.reward}，做对了却判 0")
        check(after == written,
              f"task {t}: 事后 env.data 仍是智能体自己的终态（哈希与独立重放一致）",
              f"task {t}: 事后 env.data 不是智能体终态 —— 说明数据没被还原")
        check(got["reward"] == res.reward and got["r_actions"] is True,
              f"task {t}: 安全重评分 reward = {got['reward']}、r_actions = "
              f"{got['r_actions']}，与参考路径一致",
              f"task {t}: 安全重评分 reward = {got['reward']}、r_actions = "
              f"{got['r_actions']}，与参考路径的 {res.reward} 不一致")

    P("\n── 3c. 参考评分路径内部抛异常：finally 必须还原，且异常不得被吞 ──")
    _t = tasks[0]
    env = MockRetailDomainEnv(user_strategy="human", task_split="test", task_index=_t)
    env.user = _StopUser()
    env.reset(task_index=_t)
    before = env.data

    def _boom(*_a, **_k):  # 回放参考答案时 self.step(action) 会走到这里
        raise RuntimeError("injected failure inside calculate_reward")

    env.step = _boom
    raised = False
    try:
        env.calculate_reward()
    except RuntimeError:
        raised = True
    check(raised, "异常如期向外传播（没有被 finally 吞掉）",
          "异常被吞掉了 —— finally 里的还原代码把异常也吃掉了")
    check(env.data is before, "异常路径下 env.data 也还原为进入函数时的快照",
          "异常路径下 env.data 未被还原")
    del env.step

    P("\n  结论：修复点是在 `Env.calculate_reward()` 里用 try/finally 把")
    P("        `self.data`、`self.actions`、`self.user` 还原为进入函数时的快照。")
    P("        该修复不改变参考答案的算法，只让`agent_hash`读到智能体的真实终态。")
    P("\n  注意：归档里的 4,320 集是用**有缺陷的路径**跑出来的，故其标签需要")
    P("        离线重放重建（`scripts/replay_db_rescore.py`），而不是重跑模型。")

    OUT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    P(f"\n  已写 {OUT}")

    if FAILURES:
        P(f"\n  ✗ 回归检查失败 {len(FAILURES)} 项 —— 退出码 1，"
          f"流水线应就此停下（防止修补被回滚后静默发布）：")
        for f in FAILURES:
            P(f"      · {f}")
        return 1
    P("  ✓ 回归检查全部通过（退出码 0）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
