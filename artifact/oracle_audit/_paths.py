"""离线引导：把 sqj 的审计套件接到**只读**的 v1.0 树上。

本模块的作用只有两件：
1. 让 `tau_bench`（vendored）与 `harness`（v1.0 源码）可导入——**只导入，不写入**；
2. 借用 v1.0 的 `scripts/_offline.py`：禁止 litellm 联网、缺包时装禁用桩，
   使套件在**无密钥、无网络**的环境里也能跑完（与 `offline_repro.sh` 同一套约束）。

套件**不读任何密钥**，也不发起任何模型调用。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# sqj/oracle_audit_kit/_paths.py → parents[0]=oracle_audit_kit, [1]=sqj, [2]=project root
PROJECT = Path(__file__).resolve().parents[2]
SIMGLOT = PROJECT / "simglot"
SQJ = PROJECT / "sqj"

for _p in (SIMGLOT, SIMGLOT / "vendor" / "tau-bench", SIMGLOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _offline  # noqa: E402,F401  离线约束（联网禁令 + 缺包禁用桩）
