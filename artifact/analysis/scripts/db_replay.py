#!/usr/bin/env python3
"""从 `agent_trace` 重放数据库操作 —— 修正后的 DB 终态判定（唯一入口）。

## 为什么需要

τ-bench 的 `Env.calculate_reward()` 被 `Env.step()` 在会话结束时调用：它先把环境数据
**重置**为初始态、回放**参考答案**动作、算出 `gt_data_hash`，然后**不还原** `self.data`。
于是此后任何读 `env.data` 的打分（`harness/scoring.score`）都会把参考答案的终态
当成智能体的终态，`r_actions` 恒为 True，而 `reward = r_actions ∧ r_outputs`。

受影响的是**以 `conversation_done` 结束**的 episode（主矩阵 4,183/4,320）；
以 `max_steps` 结束的未走该路径，标签是对的。

反证与回归测试：`scripts/repro_scorer_pollution.py`。
修复已提交在 `vendor/tau-bench/tau_bench/envs/base.py`（DEVIATIONS D17）。

## 本模块

只读地、确定性地重放：干净数据 + 按序施加 `agent_trace` 里的工具调用 → 智能体真实终态哈希；
与「干净数据 + 参考动作」的哈希比较，得到**修正后的** DB 判定。

保真度自检：主矩阵 33,402 个工具步的观察串与归档**逐字一致**（0 处不符），
说明重放确实复现了智能体与数据库的真实交互。

用法：
    from db_replay import replay_db, gt_hash
    ok = replay_db("test", task_id, trace)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "tau-bench"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import _offline  # noqa: E402,F401  离线分析引导：缺 litellm/openai 时装禁用桩

from tau_bench.envs.retail.env import MockRetailDomainEnv  # noqa: E402

# ── 磁盘缓存 ──────────────────────────────────────────────────────────────
# 一次重放 = 重载零售数据库 + 逐个工具调用（每次深拷贝整库）+ 整库哈希，
# 单集约 50–100 ms；4,320 集要 5 分钟以上，而下游有十几个脚本都读同一批集。
# 重放是 (split, task_id, trace) 的**确定性**函数，故按 trace 内容做键缓存。
# 改动重放逻辑时把 CACHE_VERSION 加一，缓存即整体失效。
CACHE_VERSION = 1
CACHE_DIR = Path(os.environ.get("SIMGLOT_REPLAY_CACHE",
                                ROOT / "results" / ".cache" / "replay_db"))
_USE_CACHE = os.environ.get("SIMGLOT_NO_REPLAY_CACHE", "") != "1"


def _cache_key(task_split: str, task_id: int, trace: list[dict[str, Any]]) -> str:
    blob = json.dumps([task_split, task_id, trace], sort_keys=True,
                      ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _cache_get(task_split: str, task_id: int,
               trace: list[dict[str, Any]]) -> int | None:
    if not _USE_CACHE:
        return None
    p = CACHE_DIR / f"v{CACHE_VERSION}_{_cache_key(task_split, task_id, trace)}.json"
    try:
        return int(json.loads(p.read_text(encoding="utf-8"))["db"])
    except Exception:  # noqa: BLE001
        return None


def _cache_put(task_split: str, task_id: int,
               trace: list[dict[str, Any]], db: int) -> None:
    if not _USE_CACHE:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = CACHE_DIR / f"v{CACHE_VERSION}_{_cache_key(task_split, task_id, trace)}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"db": db}), encoding="utf-8")
        tmp.replace(p)                      # 原子替换，避免半写文件被后续进程读到
    except Exception:  # noqa: BLE001
        pass


class _SilentUser:
    """占位模拟器：重放期间不得触发任何模型调用。"""

    def reset(self, instruction=None):  # noqa: ANN001
        return "###STOP###"

    def step(self, content):  # noqa: ANN001
        return "###STOP###"

    def get_total_cost(self) -> float:
        return 0.0


_ENV: dict[tuple[str, int], MockRetailDomainEnv] = {}
_GT: dict[tuple[str, int], str] = {}


def _env(task_split: str, task_id: int) -> MockRetailDomainEnv:
    key = (task_split, task_id)
    if key not in _ENV:
        e = MockRetailDomainEnv(user_strategy="human", task_split=task_split,
                                task_index=task_id)
        e.user = _SilentUser()
        _ENV[key] = e
    return _ENV[key]


def gt_hash(task_split: str, task_id: int) -> str:
    """参考答案的终态哈希（干净数据 + 回放 task.actions，跳过终结工具）。"""
    key = (task_split, task_id)
    if key not in _GT:
        e = _env(task_split, task_id)
        e.data = e.data_load_func()
        for action in e.task.actions:
            if action.name not in e.terminate_tools:
                try:
                    e.tools_map[action.name].invoke(data=e.data, **action.kwargs)
                except Exception:  # noqa: BLE001
                    pass
        _GT[key] = e.get_data_hash()
    return _GT[key]


def replay_hash(task_split: str, task_id: int, trace: list[dict[str, Any]]) -> str:
    """智能体真实终态哈希：干净数据 + 按序施加 trace 里的工具调用。"""
    e = _env(task_split, task_id)
    e.data = e.data_load_func()
    for st in trace:
        name = st.get("action")
        if not name or name == "respond" or name not in e.tools_map:
            continue
        try:
            e.tools_map[name].invoke(data=e.data, **(st.get("kwargs") or {}))
        except Exception:  # noqa: BLE001  与 Env.step 的兜底一致
            pass
    return e.get_data_hash()


def replay_db(task_split: str, task_id: int, trace: list[dict[str, Any]]) -> int:
    """修正后的 `r_actions`：智能体真实终态 == 参考终态。"""
    hit = _cache_get(task_split, task_id, trace)
    if hit is not None:
        return hit
    val = int(replay_hash(task_split, task_id, trace) == gt_hash(task_split, task_id))
    _cache_put(task_split, task_id, trace, val)
    return val


def replay_obs_mismatch(task_split: str, task_id: int,
                        trace: list[dict[str, Any]]) -> int:
    """保真度自检：回放产生的观察串与归档观察串不一致的步数（应为 0）。"""
    e = _env(task_split, task_id)
    e.data = e.data_load_func()
    bad = 0
    for st in trace:
        name = st.get("action")
        if not name or name == "respond" or name not in e.tools_map:
            continue
        try:
            obs = e.tools_map[name].invoke(data=e.data, **(st.get("kwargs") or {}))
        except Exception as exc:  # noqa: BLE001
            obs = f"Error: {exc}"
        if st.get("observation_raw", st.get("observation")) != obs:
            bad += 1
    return bad
