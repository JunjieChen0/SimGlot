"""SimGlot 评分器：纯规则、零模型调用，中英两臂共用同一套匹配逻辑。

为什么要自己写而不直接用 τ-bench 的 `Env.calculate_reward()`：

1. **中文条件下的假失败**。τ-bench 判 outputs 用的是纯子串匹配
   `output.lower() in content.lower().replace(",", "")`。绝大多数 outputs 是数字或订单号，
   语言中立；但有 16 个是英文词（`camera`、`polyester`、`mastercard`、`20 hours` …）。
   中文条件下智能体用中文回答（"这颗是佳能相机"）会匹配不到，被记为失败——
   这样测出来的"中文惩罚"是评分器的假象，不是模型行为。
2. **τ-bench 的 r_actions 丢失**。含 outputs 的任务里，`info` 被 `RewardOutputInfo` 整体
   覆盖（基类 `calculate_reward` 中 `info = RewardOutputInfo(...)`），`r_actions` 字段消失。
   而中英差异必须能拆成"数据库终态错"与"该说的话没说"两类，否则无法解释机制。
3. **中英必须同尺**。本审计的因变量是"换语言后排名/分数如何变"，
   若两臂用不同匹配器，差异就不再是语言效应。因此别名表在**两臂都生效**，
   且别名只由任务本身已要求的内容生成（英文原词的等价说法），不新增任何语义要求。

评分口径（与 τ-bench 保持一致的部分，逐字复刻）：
  r_actions : 智能体跑完后的数据库终态哈希 == 回放 ground-truth 动作后的终态哈希
  r_outputs : 任务要求的每个 output 字符串，都能在某条 RESPOND 动作的内容里找到
  reward    : r_actions AND r_outputs（等价于二者同时为真）

在此之上的唯一改动是"匹配"这一步做了归一化 + 别名，见 `match_output`。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from tau_bench.types import RESPOND_ACTION_NAME

ROOT = Path(__file__).resolve().parents[1]
ALIAS_PATH = ROOT / "data" / "output_aliases.json"

# 无别名的兜底：这些 outputs 本身语言中立（数字/订单号/邮箱），不需要翻译
_LANG_NEUTRAL = ("0123456789")


def normalize(text: str) -> str:
    """NFKC 归一 + 去千分位逗号 + 小写。

    NFKC 会把全角数字（４８１.５）、全角逗号（，）、全角字母折成半角，
    这样中文回答里的全角数字不会造成假阴性；τ-bench 原有的去 "," 保留。
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    return s.replace(",", "").lower()


def load_aliases(path: Optional[Path] = None) -> Dict[str, Dict[str, List[str]]]:
    """读取预注册的别名表：{task_id: {要求输出的原词: [接受的等价说法, ...]}}。"""
    p = Path(path) if path else ALIAS_PATH
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {str(k): v for k, v in raw.get("aliases", {}).items()}


def match_output(required: str, contents: Sequence[str],
                 aliases: Optional[Iterable[str]] = None) -> bool:
    """要求输出的原词或其任一预注册别名出现在任一条回应里，即算命中。"""
    needle_set = [normalize(required)] + [normalize(a) for a in (aliases or [])]
    for c in contents:
        hay = normalize(c)
        if any(n and n in hay for n in needle_set):
            return True
    return False


def respond_contents(env_or_actions) -> List[str]:
    """取出所有 RESPOND 动作的内容（智能体真正对用户说的话）。"""
    actions = getattr(env_or_actions, "actions", env_or_actions)
    out = []
    for a in actions:
        if a.name == RESPOND_ACTION_NAME:
            out.append(str(a.kwargs.get("content") or ""))
    return out


class _SilentUser:
    """真值回放期的占位模拟器。

    τ-bench 的算分会把任务参考答案逐条回放给 env.user。若回放里含 respond 动作而
    user 是真实 LLM，算分本身就会产生隐藏调用并污染模拟器历史。评分必须是纯规则的，
    故回放期间用沉默替身隔离（当前 retail 测试集的真值均不含 respond，此处为兜底）。
    """

    def reset(self, instruction=None) -> str:  # noqa: ANN001
        return "###STOP###"

    def step(self, content) -> str:  # noqa: ANN001
        return "###STOP###"

    def get_total_cost(self) -> float:
        return 0.0


def score(env, responses: Optional[Sequence[str]] = None,
          aliases: Optional[Dict[str, List[str]]] = None,
          task_id: Optional[int] = None) -> Dict[str, Any]:
    """给一集打分，返回可分解的明细。

    只读地使用 env：算完把 env.data 还原成智能体跑完时的终态、env.actions 还原快照、
    env.user 还原原对象，以免影响后续任何读取。
    """
    task = env.task
    tid = str(task_id if task_id is not None else (env.task_index if hasattr(env, "task_index") else ""))
    alias_map = (aliases or {}).get(tid, {})

    # ── 1) 动作侧：逐字复刻 τ-bench 的终态哈希比对 ──────────────────────────
    agent_hash = env.get_data_hash()
    actions_snapshot = list(env.actions)
    data_snapshot = env.data
    user_snapshot = getattr(env, "user", None)

    env.data = env.data_load_func()
    if user_snapshot is not None:
        env.user = _SilentUser()
    try:
        for action in task.actions:
            if action.name not in env.terminate_tools:
                env.step(action)
        gt_hash = env.get_data_hash()
    finally:
        env.data = data_snapshot
        env.actions = actions_snapshot
        if user_snapshot is not None:
            env.user = user_snapshot

    r_actions = bool(agent_hash == gt_hash)

    # ── 2) 输出侧：归一化 + 别名匹配 ────────────────────────────────────────
    contents = list(responses) if responses is not None else respond_contents(env)
    outputs_detail: Dict[str, Dict[str, Any]] = {}
    r_outputs = True
    for required in task.outputs:
        al = alias_map.get(required, [])
        hit = match_output(required, contents, al)
        outputs_detail[required] = {"found": hit, "accepted_as": [required] + list(al)}
        if not hit:
            r_outputs = False
    if not task.outputs:
        r_outputs = True

    # ── 3) 合并 ─────────────────────────────────────────────────────────────
    reward = 1.0 if (r_actions and r_outputs) else 0.0
    return {
        "reward": reward,
        "r_actions": r_actions,
        "r_outputs": r_outputs,
        "gt_data_hash": gt_hash,
        "agent_data_hash": agent_hash,
        "outputs": outputs_detail,
        "n_respond_actions": len(contents),
        "failure_mode": (
            None if reward == 1.0
            else "actions" if not r_actions and r_outputs
            else "outputs" if r_actions and not r_outputs
            else "both"
        ),
    }
