"""增强轮的离线引导。**必须在任何 tau_bench / oracle_audit_kit 导入之前 import 它。**

做三件事（与 S2 的 `sqj/swe/_bootstrap.py` 同构，第三轮外审就是被这一条绊住的）：

1. 把 S2 工作区与 `./experiments/oracle_mutation_holdout` 放进 `sys.path`，
   使 `oracle_audit_kit`（E0 基础套件，**只读**）与本轮的实验模块可导入；
2. 借用 S2 的引导链，让 vendored τ-bench 与 v1.0 的 `_offline.py` 生效
   （禁联网 + 缺 `litellm`/`openai` 时装禁用桩）；
3. 把 `db_replay` 的重放缓存重定向到本目录，**不写** S2 与 v1.0 的目录。

本模块不读任何密钥，也不发起任何模型调用。

## clean-room（第三轮外审 §7 之后补，2026-10-10）

解包后的增强包**不含** S2（`oracle_audit_kit` + vendored τ-bench 在那里）。
因此引导按下面的顺序找 S2 根：

    ① 环境变量 `SIMGLOT_S2_ROOT`（clean-room 用这个；见包根 `REPRODUCE.md`）
    ② 默认 `../sqj`（在本工作区里直接跑时用这个）

**找不到就抛带说明的 `RuntimeError`，不再抛裸 `StopIteration`**——
第三轮复审实测「解包后直接 `python checks/validity_gate_regression.py`
立刻 `StopIteration`」，读者看不出该做什么。现在这条错误会直接告诉去哪里取依赖。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # sqj_enhancement_v1/
PROJECT = HERE.parent                           # 项目根

# ── S2 根：环境变量优先，其次同级 `sqj/` ──────────────────────────────────────
_env_s2 = os.environ.get("SIMGLOT_S2_ROOT", "").strip()
SQJ = Path(_env_s2).expanduser().resolve() if _env_s2 else (PROJECT / "sqj")
SIMGLOT = PROJECT / "simglot"

# **自动下探一层**：S2 发布包解包后，`oracle_audit_kit/` 在包根的 `sqj/` 子目录里，
# 而 `SIMGLOT_S2_ROOT` 指的是「含 `oracle_audit_kit` 的那一层」。
# 第三轮复审之后实测踩过一次（给了包根 → 被判缺件），故这里替调用者下探。
if not (SQJ / "oracle_audit_kit").is_dir() and (SQJ / "sqj" / "oracle_audit_kit").is_dir():
    SQJ = SQJ / "sqj"

if not (SQJ / "oracle_audit_kit").is_dir():
    raise RuntimeError(
        "找不到 E0 基础套件 `oracle_audit_kit`。\n"
        f"  当前 S2 根：{SQJ}（来源：{'环境变量 SIMGLOT_S2_ROOT' if _env_s2 else '默认 ../sqj'}）\n"
        "  增强**增量包不含 S2**——离线分析需要它。两种做法：\n"
        "    ① clean-room：解包 S2 发布包，然后\n"
        "         bash checks/clean_room.sh /路径/to/simglot-s2-release   ← 给**包根**即可\n"
        "       （或 SIMGLOT_S2_ROOT=/路径/to/s2 的 sqj 目录 python3 <脚本>）\n"
        "    ② 在本工作区里跑：保证同级目录 `../sqj/oracle_audit_kit` 存在。\n"
        "  详见包根 `REPRODUCE.md`。")

# 重放缓存只落本工作区：S2 已发布且哈希已固定，v1.0 是冻结基线。
os.environ.setdefault("SIMGLOT_REPLAY_CACHE", str(HERE / "results" / ".cache" / "replay_db"))

for _p in (SQJ, HERE / "experiments" / "oracle_mutation_holdout", HERE / "adapters",
           HERE / "experiments" / "oracle_transfer"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import oracle_audit_kit._paths  # noqa: E402,F401  只读引导（sys.path → vendored τ-bench + _offline）

# 给实验模块起个稳定的顶层名字（目录名里带连字符，包导入不便）
import types as _types  # noqa: E402

_hold = _types.ModuleType("holdout")
_hold.__path__ = [str(HERE / "experiments" / "oracle_mutation_holdout")]  # type: ignore[attr-defined]
sys.modules.setdefault("holdout", _hold)

EXPERIMENT_ROOT = HERE
