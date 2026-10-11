"""用户模拟器的系统提示（研究的操纵对象）。

**英文（基线）逐字取自 τ-bench 原仓库** `tau_bench/envs/user.py::LLMUserSimulationEnv.build_system_prompt`，
以保证英文条件与已发表基线（Sim2Real 63.6%、Lost in Simulation 9 pp）可比。

**中文版**是英文模板的**逐条忠实翻译**——两臂的差别仅在于语言，规则条目一一对应、
既不增删条款也不改变语气强度。这一条是本审计效度的前提：若中文模板顺带把要求写得
更松或更紧，"语言效应"就掺进了提示词设计效应。逐条对应关系见文件末尾的对照表。

除模板语言外，唯一的另一处语言相关差异是指令标签（`Instruction:` / `指令：`）与
注入的指令本身（英文用 τ-bench 原指令，中文用 `data/tasks_zh.json` 的重建版）。
"""

from __future__ import annotations

from typing import Optional

# ── 英文基线：与 τ-bench 原文逐字一致（勿改，改了对照组就不可比）──────────
EN_BASELINE = """You are a user interacting with an agent.{instruction_display}
Rules:
- Just generate one line at a time to simulate the user's message.
- Do not give away all the instruction at once. Only provide the information that is necessary for the current step.
- Do not hallucinate information that is not provided in the instruction. For example, if the agent asks for the order id but it is not mentioned in the instruction, do not make up an order id, just say you do not remember or have it.
- If the instruction goal is satisified, generate '###STOP###' as a standalone message without anything else to end the conversation.
- Do not repeat the exact instruction in the conversation. Instead, use your own words to convey the same information.
- Try to make the conversation as natural as possible, and stick to the personalities in the instruction."""

# ── 中文版：英文模板的逐条忠实翻译（顺序、条目数、语气强度均一一对应）──────
ZH_TEMPLATE = """你是一个正在和客服智能体交互的用户。{instruction_display}
规则：
- 每次只生成一句，用来模拟用户的发言。
- 不要一次把指令里的信息全部透露出去，只提供当前这一步需要的信息。
- 不要编造指令中没有提供的信息。例如，如果客服询问订单号，但指令里没有提到，就不要编造一个订单号，直接说你不记得或没有。
- 如果指令中的目标已经达成，就单独生成 '###STOP###' 作为一条消息来结束对话，不要附带其他任何内容。
- 不要在对话中重复指令的原话。改用你自己的话表达同样的信息。
- 尽量让对话显得自然，并保持指令中描述的性格。"""

INSTRUCTION_LABEL = {"en": "\n\nInstruction: ", "zh": "\n\n指令："}

TEMPLATES = {"en": EN_BASELINE, "zh": ZH_TEMPLATE}


def build_system_prompt(
    lang: str = "en",
    instruction: Optional[str] = None,
    template: Optional[str] = None,
) -> str:
    tpl = template or TEMPLATES[lang]
    if instruction is None:
        instruction_display = ""
    else:
        label = INSTRUCTION_LABEL.get(lang, INSTRUCTION_LABEL["en"])
        instruction_display = label + instruction + "\n"
    return tpl.format(instruction_display=instruction_display)


# 逐条对应表（供论文附录与人工复核）：
#   EN  "You are a user interacting with an agent."      ↔ ZH  "你是一个正在和客服智能体交互的用户。"
#   EN  "Just generate one line at a time…"              ↔ ZH  "每次只生成一句，用来模拟用户的发言。"
#   EN  "Do not give away all the instruction at once…"  ↔ ZH  "不要一次把指令里的信息全部透露出去…"
#   EN  "Do not hallucinate information that is not…"    ↔ ZH  "不要编造指令中没有提供的信息。例如…"
#   EN  "If the instruction goal is satisified…"         ↔ ZH  "如果指令中的目标已经达成…"
#   EN  "Do not repeat the exact instruction…"           ↔ ZH  "不要在对话中重复指令的原话…"
#   EN  "Try to make the conversation as natural as…"    ↔ ZH  "尽量让对话显得自然，并保持指令中描述的性格。"
# （原文拼写 "satisified" 为 τ-bench 自带笔误，英文模板照抄不改；该笔误不影响语义。）
