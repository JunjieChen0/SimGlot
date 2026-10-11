"""单集闭环的执行体（命令行与批量驱动共用）。

一次调用 = 一个实验格：(任务 × 智能体模型 × 模拟器模型 × 语言 × 重复序号)。
产出三件套：calls.jsonl（逐次调用明细）、transcript.json（双方消息流与逐步 trace）、summary.json。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "tau-bench"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from tau_bench.envs.retail.env import MockRetailDomainEnv  # noqa: E402

from . import env_lang as EL  # noqa: E402
from .agent import ToolCallingAgent  # noqa: E402
from .client import BailianClient, now_utc  # noqa: E402
from .scoring import load_aliases, score  # noqa: E402
from .user_sim import OurUserSim  # noqa: E402

_ALIASES = None
_ZH_SUITE = None


def _aliases():
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = load_aliases()
    return _ALIASES


def _zh_suite():
    """E1 中文任务套件：{task_id: 中文指令}。缺失时明确报错，绝不静默回退到英文。"""
    global _ZH_SUITE
    if _ZH_SUITE is None:
        p = ROOT / "data" / "tasks_zh.json"
        if not p.exists():
            raise FileNotFoundError(
                f"中文条件需要 {p}，但它不存在。请先运行 "
                f"scripts/sample_tasks.py 与 scripts/build_zh_suite.py。"
            )
        payload = json.loads(p.read_text(encoding="utf-8"))
        _ZH_SUITE = {int(r["task_id"]): r["zh"] for r in payload["tasks"]}
    return _ZH_SUITE


@dataclass
class EpisodeSpec:
    task_id: int
    agent_model: str = "qwen3.8-flash"
    user_model: str = "qwen3.8-flash"
    user_lang: str = "en"
    # 环境语言（2×2 第二因子）：智能体读到的系统提示、工具说明、工具错误串的语言。
    # "en" 时全路径严格恒等（E2 主矩阵可比性的构造性保证），见 harness/env_lang.py。
    env_lang: str = "en"
    task_split: str = "test"
    channel: str = "token_plan"
    max_steps: int = 30
    seed: int = 0
    tag: str = "adhoc"
    out_root: Optional[Path] = None
    agent_thinking: Optional[bool] = None  # 对照实验用：强制开/关智能体侧思考模式
    agent_channel: Optional[str] = None    # 智能体单独走另一条通道；None 表示与 channel 相同

    def cell_id(self) -> str:
        # env_lang="en" 时不加后缀：E2 主矩阵的全部既有 run_dir 名与恢复逻辑逐字不变。
        suffix = "" if self.env_lang == "en" else f"_e{self.env_lang}"
        return (f"t{self.task_id}_{self.agent_model}_u-{self.user_model}"
                f"_{self.user_lang}_s{self.seed}{suffix}")

    def run_dir(self) -> Path:
        root = Path(self.out_root) if self.out_root else (ROOT / "runs" / self.tag)
        return root / self.cell_id()


def run_episode(spec: EpisodeSpec) -> Dict[str, Any]:
    run_dir = spec.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    calls_log = run_dir / "calls.jsonl"
    started = time.time()

    agent_client = BailianClient(
        channel=spec.agent_channel or spec.channel, role="agent", log_path=calls_log)
    user_client = BailianClient(channel=spec.channel, role="user", log_path=calls_log)

    # 对照实验：智能体侧思考模式若被显式指定，则覆盖厂商默认适配。
    # 用途是排除"结论由我们自己设的请求参数造成"这一嫌疑，正式矩阵不应使用。
    if spec.agent_thinking is not None:
        agent_client.override_extra_body(
            spec.agent_model, {"enable_thinking": bool(spec.agent_thinking)}
        )

    env = MockRetailDomainEnv(
        user_strategy="human",  # 占位，避免构造期发生模型调用
        task_split=spec.task_split,
        task_index=spec.task_id,
    )

    # 中文条件：把注入模拟用户的指令换成 E1 重建的中文版。
    # 用 model_copy 生成新对象，避免污染模块级共享的 TASKS_TEST；
    # 智能体的系统提示词、工具定义、数据库一律不动——两臂只差用户侧语言。
    instruction_lang = "en"
    if spec.user_lang == "zh":
        zh = _zh_suite().get(spec.task_id)
        if zh is None:
            raise KeyError(
                f"任务 #{spec.task_id} 不在 E1 中文套件内，无法在中文条件下运行。"
                f"（中文条件只允许在抽样出的任务上进行，以免样本与英文臂不一致。）"
            )
        env.tasks = list(env.tasks)
        env.tasks[spec.task_id] = env.tasks[spec.task_id].model_copy(
            update={"instruction": zh}
        )
        instruction_lang = "zh"

    task = env.tasks[spec.task_id]
    env.user = OurUserSim(user_client, spec.user_model, lang=spec.user_lang)

    # 环境侧语言（2×2 第二因子）：系统提示 + 工具说明 + 工具错误串。
    # env_lang="en" 时三个函数都原样返回输入对象，故此处对 E2 主矩阵是恒等变换。
    agent_system_prompt = EL.wiki(spec.env_lang)
    agent_tools_info = EL.tools_info(env.tools_info, spec.env_lang)

    agent = ToolCallingAgent(
        client=agent_client,
        model=spec.agent_model,
        tools_info=agent_tools_info,
        system_prompt=agent_system_prompt,
        temperature=0.0,
        max_num_steps=spec.max_steps,
        obs_lang=spec.env_lang,
    )

    error = ""
    result: Dict[str, Any] = {"reward": 0.0, "messages": [], "trace": [], "stop_reason": "error", "steps": 0}
    score_detail: Dict[str, Any] = {}
    try:
        result = agent.solve(env, task_index=spec.task_id)
        score_detail = score(env, aliases=_aliases(), task_id=spec.task_id)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"

    at, ut = agent_client.totals(), user_client.totals()
    summary = {
        "spec": {**asdict(spec), "out_root": str(spec.out_root) if spec.out_root else None},
        "cell_id": spec.cell_id(),
        "started_utc": now_utc(),
        "wall_clock_s": round(time.time() - started, 2),
        "instruction": task.instruction,
        "instruction_lang": instruction_lang,
        "instruction_source": ("data/tasks_zh.json（E1 重建）" if instruction_lang == "zh"
                               else "tau-bench 原指令"),
        # 环境侧语言因子及其实现指纹（zh 时与 en 必然不同，便于事后校验操纵确已生效）
        "env_lang": spec.env_lang,
        "env_impl_sha": EL.fingerprint(spec.env_lang),
        "reward": score_detail.get("reward", result["reward"]),
        "stop_reason": result["stop_reason"],
        "agent_steps": result["steps"],
        "user_turns": len(env.user.turns),
        "score": score_detail,
        "reward_detail": {
            "r_actions": score_detail.get("r_actions"),
            "r_outputs": score_detail.get("r_outputs"),
            "failure_mode": score_detail.get("failure_mode"),
        },
        "agent_totals": at,
        "user_totals": ut,
        "error": error,
    }

    (run_dir / "transcript.json").write_text(
        json.dumps(
            {
                "agent_messages": result["messages"],
                "user_messages": env.user.messages,
                "agent_trace": result["trace"],
                "user_turns": env.user.turns,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
