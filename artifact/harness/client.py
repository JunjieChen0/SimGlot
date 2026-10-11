"""百炼 Token Plan 通道客户端（SimGlot 的模型层）。

要点：
  * 按模型族适配请求参数：qwen / deepseek 默认开思考模式，会无视 max_tokens、把预算烧在
    推理上（2026-10-07 实测延迟 1.8–11 s、completion token 超限 4–25 倍），必须显式关闭；
    glm 不支持 enable_thinking（传了报 400），故不加该参数。
  * 未知参数导致 400 时，剥离 extra_body 重试一次。
  * 每次调用写一行 JSONL（角色、模型、延迟、token、重试、错误），供成本核算与复现审计。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

ROOT = Path(__file__).resolve().parents[1]
RETRYABLE = (APIConnectionError, APITimeoutError, RateLimitError)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def family_of(model: str) -> str:
    m = model.lower()
    for fam in ("qwen", "deepseek", "glm"):
        if m.startswith(fam):
            return fam
    return "other"


@dataclass
class ChatResult:
    content: str
    tool_calls: List[Dict[str, Any]]
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    raw_message: Dict[str, Any]


class BailianClient:
    """面向单次实验运行的通道客户端；role 用于区分 agent / user 两类调用。"""

    def __init__(
        self,
        channel: str = "token_plan",
        role: str = "model",
        log_path: Optional[Path] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        cfg = config_dir or (ROOT / "config")
        load_env_file(cfg / ".env")
        import yaml  # 延后导入，缺包时报错更明确

        providers = yaml.safe_load((cfg / "providers.yaml").read_text(encoding="utf-8"))
        ch = providers["channels"][channel]
        self.channel = channel
        self.base_url = ch.get("base_url") or os.environ[ch["base_url_env"]]
        self.api_key = os.environ[ch["api_key_env"]]
        self.adapters = providers.get("adapters", {})
        self.adapters_by_channel = providers.get("adapters_by_channel", {}) or {}
        d = providers.get("request_defaults", {})
        self.temperature = d.get("temperature", 0.0)
        self.max_tokens = d.get("max_tokens", 512)
        self.max_attempts = int(d.get("max_retries", 3))
        self.backoff = list(d.get("retry_backoff_s", [1, 4, 12]))
        self.role = role
        self.log_path = log_path
        self.calls: List[Dict[str, Any]] = []
        budgets = providers.get("simulator_max_tokens", {}) or {}
        self._sim_budget_default = int(budgets.get("default", self.max_tokens))
        self._sim_budgets = {k: int(v) for k, v in budgets.items() if k != "default"}
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=float(d.get("timeout_s", 90)),
            max_retries=0,  # 重试由我们自己做，才能记录次数
        )

    # ---------- 内部 ----------
    def simulator_max_tokens(self, model: str) -> int:
        """该模型作为**模拟用户**时的每轮 token 预算（按厂商设定，见 providers.yaml）。"""
        return self._sim_budgets.get(family_of(model), self._sim_budget_default)

    def _extra_body(self, model: str) -> Dict[str, Any]:
        """按『通道 → 模型族』取请求参数适配。

        同一模型族在不同通道上关思考的写法不同，故通道级配置优先：
          * 百炼：qwen / deepseek 用 `enable_thinking: false`；glm 强制思考、无参数可关。
          * DMXAPI 聚合站：`enable_thinking: false` **被静默忽略**（不报 400，故剥离重试
            兜底也不会触发），实测须用 `thinking: {"type": "disabled"}`（或
            `reasoning_effort: "none"`），否则思考 token 吃光 max_tokens、可见输出为空。
        通道未配置时回落到扁平的家庭族配置，行为与改动前完全一致。
        """
        fam = family_of(model)
        per_channel = (self.adapters_by_channel.get(self.channel) or {})
        if fam in per_channel:
            return dict(per_channel[fam].get("extra_body") or {})
        return dict(self.adapters.get(fam, {}).get("extra_body") or {})

    def override_extra_body(self, model: str, extra_body: Dict[str, Any]) -> None:
        """对照实验用：覆盖某模型族的 extra_body（例如把智能体侧的思考模式打开），
        以检验某个结论是否由我们自己设的请求参数造成。只影响本客户端实例。"""
        self.adapters = dict(self.adapters)
        self.adapters[family_of(model)] = {"extra_body": dict(extra_body)}

    def _log(self, rec: Dict[str, Any]) -> None:
        self.calls.append(rec)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- 对外 ----------
    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatResult:
        extra = self._extra_body(model)
        last_err: Optional[Exception] = None

        for attempt in range(1, self.max_attempts + 1):
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": self.temperature if temperature is None else temperature,
                "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if extra:
                kwargs["extra_body"] = extra

            t0 = time.time()
            try:
                res = self._client.chat.completions.create(**kwargs)
            except APIStatusError as e:
                dt = time.time() - t0
                last_err = e
                if e.status_code == 400 and extra:
                    self._log({
                        "ts": now_utc(), "role": self.role, "model": model, "ok": False,
                        "latency_s": round(dt, 2), "adapted": "strip_extra_body",
                        "error": f"400，剥离 extra_body 后重试：{str(e)[:160]}",
                    })
                    extra = {}
                    continue
                self._log({
                    "ts": now_utc(), "role": self.role, "model": model, "ok": False,
                    "latency_s": round(dt, 2), "retries": attempt,
                    "error": f"HTTP {e.status_code}: {str(e)[:200]}",
                })
                if e.status_code not in (429, 500, 502, 503, 504):
                    raise
            except RETRYABLE as e:  # type: ignore[misc]
                dt = time.time() - t0
                last_err = e
                self._log({
                    "ts": now_utc(), "role": self.role, "model": model, "ok": False,
                    "latency_s": round(dt, 2), "retries": attempt,
                    "error": f"{type(e).__name__}: {str(e)[:200]}",
                })
            else:
                dt = time.time() - t0
                msg = res.choices[0].message
                usage = res.usage
                tcs = [tc.model_dump() for tc in (msg.tool_calls or [])]
                rec = {
                    "ts": now_utc(), "role": self.role, "model": model, "ok": True,
                    "latency_s": round(dt, 2),
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    "n_tool_calls": len(tcs), "retries": attempt - 1,
                    "adapted": (json.dumps(extra, ensure_ascii=False) if extra else ""),
                }
                self._log(rec)
                return ChatResult(
                    content=msg.content or "",
                    tool_calls=tcs,
                    prompt_tokens=rec["prompt_tokens"],
                    completion_tokens=rec["completion_tokens"],
                    latency_s=dt,
                    raw_message=msg.model_dump(exclude_none=True),
                )

            if attempt < self.max_attempts:
                time.sleep(self.backoff[min(attempt - 1, len(self.backoff) - 1)])

        raise RuntimeError(f"模型 {model} 在 {self.max_attempts} 次尝试后仍失败：{last_err}")

    def totals(self) -> Dict[str, Any]:
        ok = [c for c in self.calls if c.get("ok")]
        return {
            "role": self.role,
            "calls": len(self.calls),
            "ok_calls": len(ok),
            "failed_calls": len(self.calls) - len(ok),
            "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in ok),
            "completion_tokens": sum(c.get("completion_tokens", 0) for c in ok),
            "total_tokens": sum(c.get("total_tokens", 0) for c in ok),
            "latency_s_sum": round(sum(c.get("latency_s", 0.0) for c in self.calls), 2),
        }
