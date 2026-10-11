#!/usr/bin/env python3
"""从原始轨迹**重放数据库操作**，重建不受会话结束评分污染的 DB 标签。

## 为什么需要这个脚本

τ-bench 的 `Env.calculate_reward()`（`vendor/tau-bench/tau_bench/envs/base.py:124`）在
会话结束（`###STOP###` 或终结工具）时被 `Env.step()` 调用，它做的是：

    data_hash = self.get_data_hash()      # 读智能体的真实终态
    self.data = self.data_load_func()     # 把环境数据**重置**为初始态
    for action in self.task.actions:      # 回放**参考答案**动作
        if action.name not in self.terminate_tools:
            self.step(action)
    gt_data_hash = self.get_data_hash()   # 参考终态
    ...

**它从不把 `self.data` 还原成智能体的真实终态。** 于是 `run_episode()`
（`harness/episode.py`）在 `agent.solve()` 之后调用的 `score(env)` 里，
`agent_hash = env.get_data_hash()` 读到的是**参考答案执行后的**数据库状态，
而不是智能体真正达到的状态；`scorer.py` 随后又把数据重置并回放同一套参考动作得到
`gt_hash`，两者恒等 → `r_actions` 恒为 True。

因此：**以 `conversation_done` 结束的 episode，其 DB 标签在归档里被污染**；
以 `max_steps` 结束的 episode 未走该路径，标签是对的。

## 本脚本做什么

只读地重放：对每个 episode，把 `transcript.json` 的 `agent_trace` 里的**工具动作**
按顺序施加到一个干净的环境数据副本上，得到智能体真实的终态哈希，再与参考终态哈希比较。
同时把每次回放产生的观察串与归档观察串逐条比对，作为**回放保真度**的自检。

用法：python3 scripts/replay_db_rescore.py
"""

from __future__ import annotations

import collections
import csv
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "tau-bench"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import _offline  # noqa: E402,F401  离线分析引导：缺 litellm/openai 时装禁用桩

from tau_bench.envs.retail.env import MockRetailDomainEnv  # noqa: E402

OUT_CSV = ROOT / "results" / "replay_rescore.csv"
OUT_TXT = ROOT / "results" / "replay_rescore.txt"

_ENV_CACHE: dict[tuple[str, int], MockRetailDomainEnv] = {}
_GT_CACHE: dict[tuple[str, int], str] = {}


def env_for(task_split: str, task_id: int) -> MockRetailDomainEnv:
    key = (task_split, task_id)
    if key not in _ENV_CACHE:
        e = MockRetailDomainEnv(user_strategy="human", task_split=task_split,
                                task_index=task_id)
        _ENV_CACHE[key] = e
    return _ENV_CACHE[key]


def gt_hash(task_split: str, task_id: int) -> str:
    """参考终态哈希：干净数据 + 回放任务参考答案（跳过终结工具）。"""
    key = (task_split, task_id)
    if key not in _GT_CACHE:
        e = env_for(task_split, task_id)
        e.data = e.data_load_func()
        for action in e.task.actions:
            if action.name not in e.terminate_tools:
                try:
                    e.tools_map[action.name].invoke(data=e.data, **action.kwargs)
                except Exception:
                    pass
        _GT_CACHE[key] = e.get_data_hash()
    return _GT_CACHE[key]


def replay_trace(task_split: str, task_id: int, trace: list[dict]) -> tuple[str, int, int]:
    """在干净数据上按序回放工具动作。

    返回 (智能体终态哈希, 工具步数, 观察串与归档不一致的步数)。
    """
    e = env_for(task_split, task_id)
    e.data = e.data_load_func()
    n_tools = 0
    n_obs_mismatch = 0
    for st in trace:
        name = st.get("action")
        if not name or name == "respond" or name not in e.tools_map:
            continue
        n_tools += 1
        kwargs = st.get("kwargs") or {}
        try:
            obs = e.tools_map[name].invoke(data=e.data, **kwargs)
        except Exception as exc:  # 与 Env.step 的兜底一致
            obs = f"Error: {exc}"
        # 保真度自检：归档里若记了未翻译的原始串则用它比对
        archived = st.get("observation_raw", st.get("observation"))
        if archived != obs:
            n_obs_mismatch += 1
    return e.get_data_hash(), n_tools, n_obs_mismatch


def load_specs(tags: list[str], base_tag: str | None = None) -> list[tuple[str, Path]]:
    """按 frozen_table.py 的同一套去重规则取出待评分 episode。

    base_tag 给定且为 BASE_TAG 时，失败格用 fallback 标签下的同名成功重跑补入。
    """
    specs: list[tuple[str, Path]] = []
    failed: list[str] = []
    for tag in tags:
        for sp in sorted(glob.glob(str(ROOT / "runs" / tag / "*" / "summary.json"))):
            d = json.loads(Path(sp).read_text(encoding="utf-8"))
            if d.get("error"):
                failed.append(d["cell_id"])
                continue
            specs.append((tag, Path(sp)))
    if base_tag:
        for cid in failed:
            sp = ROOT / "runs" / base_tag / cid / "summary.json"
            if sp.exists():
                specs.append((base_tag, sp))
    return specs


def main() -> int:
    BASE = "e2_main24"
    specs = load_specs([BASE], base_tag="e2_main")

    rows = []
    obs_mismatch_total = 0
    for i, (tag, sp) in enumerate(specs):
        if i % 500 == 0:
            print(f"  … {i}/{len(specs)}", flush=True)
        d = json.loads(sp.read_text(encoding="utf-8"))
        spec = d.get("spec") or {}
        if spec.get("env_lang", "en") != "en":
            continue
        tp = sp.with_name("transcript.json")
        if not tp.exists():
            continue
        trace = json.loads(tp.read_text(encoding="utf-8")).get("agent_trace", [])
        tid = int(spec["task_id"])
        split = spec.get("task_split", "test")
        true_hash, n_tools, n_bad = replay_trace(split, tid, trace)
        obs_mismatch_total += n_bad
        gt = gt_hash(split, tid)
        sc = d.get("score") or {}
        rows.append({
            "cell_id": d.get("cell_id"),
            "tag": tag,
            "task_id": tid,
            "agent": spec.get("agent_model"),
            "sim": spec.get("user_model"),
            "user_lang": spec.get("user_lang"),
            "env_lang": spec.get("env_lang", "en"),
            "seed": spec.get("seed"),
            "status": d.get("stop_reason"),
            "archived_db": int(bool(sc.get("r_actions"))),
            "replay_db": int(true_hash == gt),
            "archived_full": int(float(d.get("reward") or 0) == 1.0),
            "archived_agent_hash": sc.get("agent_data_hash"),
            "replay_agent_hash": true_hash,
            "gt_hash": gt,
            "hash_equals_gt": int(sc.get("agent_data_hash") == gt),
            "n_tools": n_tools,
            "obs_mismatch": n_bad,
        })

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    out = []

    def P(s=""):
        out.append(s)
        print(s)

    P("=" * 84)
    P("从原始轨迹重放数据库操作 · 主矩阵（en 环境）")
    P("=" * 84)
    n = len(rows)
    P(f"\n  episode {n}｜回放工具步合计 {sum(r['n_tools'] for r in rows)}"
      f"｜观察串与归档不一致 {obs_mismatch_total} 步")

    # 1) 污染的直接证据
    eq = sum(r["hash_equals_gt"] for r in rows)
    P(f"\n── 1. 归档 agent_data_hash 与参考 gt_hash 相等的条数 ──")
    P(f"  {eq}/{n}（{100*eq/n:.1f}%）——两者本应几乎从不相等")
    bys = collections.Counter((r["status"], r["hash_equals_gt"]) for r in rows)
    for k, v in sorted(bys.items()):
        P(f"    status={k[0]:<20} hash==gt: {k[1]}  {v}")

    # 2) DB 标签改变
    chg = [r for r in rows if r["archived_db"] != r["replay_db"]]
    P(f"\n── 2. DB-only 标签变化 ──")
    P(f"  归档 DB 通过 {sum(r['archived_db'] for r in rows)}"
      f"｜重放 DB 通过 {sum(r['replay_db'] for r in rows)}"
      f"｜改变 {len(chg)}（{100*len(chg)/n:.1f}%）")
    P(f"  按终止状态：")
    for st in ("conversation_done", "max_steps"):
        sub = [r for r in rows if r["status"] == st]
        if not sub:
            continue
        P(f"    {st:<20} n={len(sub):<5} 归档通过 {sum(r['archived_db'] for r in sub):<5}"
          f"重放通过 {sum(r['replay_db'] for r in sub):<5}"
          f"改变 {sum(1 for r in sub if r['archived_db'] != r['replay_db'])}")

    # 3) 修正后的成功率与语言效应
    P(f"\n── 3. 修正后的成功率与语言效应 ──")
    P(f"  整体 Full  归档 {100*sum(r['archived_full'] for r in rows)/n:.1f}%"
      f" → 修正（DB 重放 ∧ 输出不变，下同）见下表")

    agents = sorted({r["agent"] for r in rows})
    P(f"\n  {'agent':<22}{'臂':<4}{'n':>5}{'归档 DB':>10}{'重放 DB':>10}"
      f"{'归档 Δ':>10}{'重放 Δ':>10}")
    for ag in agents:
        vals = {}
        for lang in ("en", "zh"):
            sub = [r for r in rows if r["agent"] == ag and r["user_lang"] == lang]
            a = 100 * sum(r["archived_db"] for r in sub) / len(sub)
            b = 100 * sum(r["replay_db"] for r in sub) / len(sub)
            vals[lang] = (len(sub), a, b)
            P(f"  {ag:<22}{lang:<4}{len(sub):>5}{a:>9.1f}%{b:>9.1f}%")
        P(f"  {'':<22}{'Δ':<4}{'':>5}{'':>10}{'':>10}"
          f"{vals['zh'][1]-vals['en'][1]:>+9.2f}{vals['zh'][2]-vals['en'][2]:>+9.2f}")
    for key in ("archived_db", "replay_db"):
        sub_en = [r for r in rows if r["user_lang"] == "en"]
        sub_zh = [r for r in rows if r["user_lang"] == "zh"]
        a = 100 * sum(r[key] for r in sub_en) / len(sub_en)
        b = 100 * sum(r[key] for r in sub_zh) / len(sub_zh)
        P(f"  {'POOLED':<22}{key:<10}{a:>9.1f}%{b:>9.1f}%{b-a:>+10.2f}")

    OUT_TXT.write_text("\n".join(out) + "\n", encoding="utf-8")
    P(f"\n  已写 {OUT_CSV} 与 {OUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
