"""我们的用户模拟器实现。

与 τ-bench 原实现的行为差异（有意为之，需写进论文的方法章节）：
  1. 原实现在 `__init__` 里先 `reset()` 一次（此时 instruction 为 None），产生一次无用调用；
     我们不复制这次浪费，只在 env 给出 instruction 时生成首句。
  2. 原实现把模型返回的 assistant 消息原样追加进历史；我们同样保留完整历史，
     但额外记录每一步的 token 与延迟，便于逐轮分析模拟器行为。
  3. **预算与截断兜底**：每轮的 token 上限按厂商设定（见 providers.yaml），并检测
     "撞上限"（completion ≥ 0.98×预算）或"可见内容为空"。命中时按 3 倍预算重试一次，
     并把该轮标记为 `budget_escalated`。这一条针对 glm-5.3：它的思考模式由平台强制开启，
     思考 token 计入上限，预算不足会导致"想完了却没说出话"——那是仪器故障，不是模型行为。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import BailianClient
from .prompts import build_system_prompt

# τ-bench 原实现用于播种的固定首句（注意：它在 user 角色下，内容却是客服的口吻）。
# 这句只存在于模拟器自己的历史里、不会展示给智能体，故随语言切换，
# 以免中文臂的模拟器提示词里混入英文（两臂只应差语言）。
SEED_MESSAGE = {
    "en": "Hi! How can I help you today?",
    "zh": "你好！请问有什么可以帮您的？",
}


class OurUserSim:
    """可切换语言的用户模拟器；接口对齐 τ-bench 的 BaseUserSimulationEnv。"""

    def __init__(
        self,
        client: BailianClient,
        model: str,
        lang: str = "en",
        template: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self.client = client
        self.model = model
        self.lang = lang
        self.template = template
        # 不传则按厂商取预算（glm 需要更大预算，理由见模块文档）
        self.max_tokens = (max_tokens if max_tokens is not None
                           else client.simulator_max_tokens(model))
        self.messages: List[Dict[str, Any]] = []
        self.turns: List[Dict[str, Any]] = []

    # 与 τ-bench 的 BaseUserSimulationEnv 对齐
    def reset(self, instruction: Optional[str] = None) -> str:
        self.messages = [
            {"role": "system", "content": build_system_prompt(self.lang, instruction, self.template)},
            {"role": "user", "content": SEED_MESSAGE[self.lang]},
        ]
        self.turns = []
        return self._generate()

    def step(self, content: str) -> str:
        self.messages.append({"role": "user", "content": content})
        return self._generate()

    def get_total_cost(self) -> float:
        # Token Plan 按 Credits 计费；成本统一在 calls.jsonl 里按 token 记账
        return 0.0

    # ---------- 内部 ----------
    def _generate(self) -> str:
        """生成一句用户发言；预算不足时循环扩容，确保不会出现空发言或半句话。

        判据：`completion_tokens ≥ 0.98×预算` 即视为被上限切断（思考模型尤其常见），
        或可见内容为空。命中则把预算乘 3 重试，最多 3 次扩容。
        仍不满足时把该轮标为 `truncated_final`，供分析阶段识别与排除。
        """
        budget = self.max_tokens
        escalations = 0
        res = self.client.chat(self.model, self.messages, max_tokens=budget)
        text = res.content or ""
        while (not text.strip() or res.completion_tokens >= budget * 0.98) and escalations < 3:
            escalations += 1
            budget *= 3
            res = self.client.chat(self.model, self.messages, max_tokens=budget)
            text = res.content or ""

        truncated_final = res.completion_tokens >= budget * 0.98
        self.messages.append({"role": "assistant", "content": text})
        self.turns.append({
            "turn": len(self.turns) + 1,
            "text": text,
            "prompt_tokens": res.prompt_tokens,
            "completion_tokens": res.completion_tokens,
            "latency_s": round(res.latency_s, 2),
            "budget": budget,
            "budget_escalations": escalations,
            "budget_escalated": escalations > 0,
            "empty": not text.strip(),
            "truncated_final": truncated_final,
        })
        return text
