"""离线分析引导：把模型客户端挡在复现路径之外，并禁止一切网络访问尝试。

**为什么需要**：`vendor/tau-bench/tau_bench/envs/base.py` 经 `envs/user.py` 间接
`from litellm import completion`。本文的全部分析——重放数据库终态、重算评分、
重跑统计——都**不需要**模型客户端，却因此被迫安装 litellm（它首次导入还会去
`raw.githubusercontent.com` 拉价目表）。第七轮独立复核指出：在没有 litellm 的环境里
`scripts/repro_scorer_pollution.py` 直接导入失败，`scripts/compare_lenmatch.py` 还会
经 `harness.episode` 间接拖入 `openai`。

**本模块在被分析脚本导入时立即做三件事**：

1. 置 `LITELLM_LOCAL_MODEL_COST_MAP=True`，禁止 litellm 联网；
2. 若 `litellm` / `openai` **确实缺失**，装一个「禁用桩」：`from litellm import completion`
   这类导入成功，但任何真的去调用模型的动作立刻抛 `RuntimeError` 并说明这是离线分析。
   真包存在时**不做任何替换**（不掩盖真实错误）；
3. 置 `SIMGLOT_OFFLINE_STUB=1` 时**强制**使用桩，供「环境隔离的无 API 回归测试」
   （见 `scripts/offline_repro.sh --strict-offline`）在装了真包的机器上验证纯离线路径。

因此复现论文数字只需要：`python3` + `numpy/scipy/statsmodels/pandas/matplotlib`
（见 `requirements-analysis.txt`），**外加仓库自带的 vendored τ-bench 与环境数据**。
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# ── 1. 禁止 litellm 联网拉价目表 ────────────────────────────────────────────────
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# ── 2. 让仓库根与 vendored τ-bench 可导入（不必 import harness.episode）─────────
ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "vendor" / "tau-bench"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

FORCED = os.environ.get("SIMGLOT_OFFLINE_STUB") == "1"


def _blocked(name: str):
    """桩属性：调用即报错；以 Error 结尾的名字做成异常类，便于 except/isinstance。"""
    if name.endswith(("Error", "Exception")):
        return type(name, (Exception,), {})
    def _blocked_call(*_a, **_k):
        raise RuntimeError(
            f"离线分析不得调用模型客户端（试图调用 {name}）。"
            "本文全部数字来自 runs/ 中的既有轨迹与 results/frozen_table.csv，"
            "不需要也不允许发起任何模型请求。")
    _blocked_call.__name__ = name
    return _blocked_call


class _GuardModule(types.ModuleType):
    """缺失时顶替真包的模块：任何属性访问都给出禁用桩。"""

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _blocked(name)


def _install_stub(modname: str) -> bool:
    """缺失（或被强制）时装桩，返回是否装了。"""
    if not FORCED:
        try:
            __import__(modname)
            return False                      # 真包在，什么都不做
        except Exception:                     # noqa: BLE001
            pass
    sys.modules.pop(modname, None)
    sys.modules[modname] = _GuardModule(modname)
    return True


for _m in ("litellm", "openai"):
    _install_stub(_m)

# ── 3. 自检：确认凭据不会被离线分析读取 ─────────────────────────────────────────
CREDENTIAL_VARS = ("DASHSCOPE_API_KEY", "DMXAPI_API_KEY", "OPENAI_API_KEY")


def assert_no_credentials() -> None:
    """离线分析不应该出现任何通道密钥；出现即说明走错了路径。"""
    present = [v for v in CREDENTIAL_VARS if os.environ.get(v)]
    if present:
        raise RuntimeError(
            f"离线分析检测到通道密钥环境变量 {present}；"
            "本节不读密钥，请改用 analysis-only 环境复现。")
