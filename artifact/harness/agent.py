"""固定 scaffold 的工具调用智能体。

对齐 τ-bench 原 `ToolCallingAgent.solve` 的控制流（包括"只取第一个 tool_call"），
但模型调用走我们自己的通道客户端，以保证：请求参数可控、每次都记 token 与延迟、
并且 scaffold 在全部实验条件之间严格不变。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from tau_bench.envs.base import Env
from tau_bench.types import RESPOND_ACTION_NAME, Action

from . import env_lang as EL
from .client import BailianClient


def message_to_action(message: Dict[str, Any]) -> tuple[Action, str]:
    """把模型返回的消息转成 env 能执行的动作，并返回原始参数串（用于审计空参数现象）。"""
    tcs = message.get("tool_calls") or []
    if tcs and tcs[0].get("function"):
        fn = tcs[0]["function"]
        raw = fn.get("arguments") or ""
        try:
            kwargs = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            kwargs = {}
        return Action(name=fn["name"], kwargs=kwargs), raw
    return Action(name=RESPOND_ACTION_NAME, kwargs={"content": message.get("content") or ""}), ""


class ToolCallingAgent:
    def __init__(
        self,
        client: BailianClient,
        model: str,
        tools_info: List[Dict[str, Any]],
        system_prompt: str,
        temperature: float = 0.0,
        max_num_steps: int = 30,
        obs_lang: str = "en",
    ) -> None:
        self.client = client
        self.model = model
        self.tools_info = tools_info
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_num_steps = max_num_steps
        self.obs_lang = obs_lang

    def solve(self, env: Env, task_index: Optional[int] = None) -> Dict[str, Any]:
        reset_res = env.reset(task_index=task_index)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": reset_res.observation},
        ]

        reward, stop = 0.0, "max_steps"
        trace: List[Dict[str, Any]] = []

        for _ in range(self.max_num_steps):
            res = self.client.chat(
                self.model, messages, tools=self.tools_info, temperature=self.temperature
            )
            message = res.raw_message
            action, raw_args = message_to_action(message)
            env_res = env.step(action)
            reward = env_res.reward

            # 环境语言：智能体**看到**的观察串。en 恒等；zh 只翻工具错误串，
            # 数据库内容（订单/商品/用户 JSON）与用户发言一律原样。
            obs_seen = EL.observation(env_res.observation, self.obs_lang)
            # 账本：只在两版不同时记原始串，避免 E2 既有轨迹的 schema 膨胀
            entry = {
                "step": len(trace) + 1,
                "action": action.name,
                "kwargs": action.kwargs,
                "raw_arguments": raw_args,
                "observation": obs_seen,
                "done": env_res.done,
                "prompt_tokens": res.prompt_tokens,
                "completion_tokens": res.completion_tokens,
                "latency_s": round(res.latency_s, 2),
            }
            if obs_seen != env_res.observation:
                entry["observation_raw"] = env_res.observation
            trace.append(entry)

            if action.name != RESPOND_ACTION_NAME:
                tcs = (message.get("tool_calls") or [])[:1]
                message["tool_calls"] = tcs
                messages.append(message)
                if tcs:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tcs[0]["id"],
                        "name": tcs[0]["function"]["name"],
                        "content": obs_seen,
                    })
            else:
                messages.append(message)
                messages.append({"role": "user", "content": obs_seen})

            if env_res.done:
                stop = "conversation_done"
                break

        return {
            "reward": reward,
            "messages": messages,
            "trace": trace,
            "stop_reason": stop,
            "steps": len(trace),
        }
