#!/usr/bin/env python3
"""冻结分析表：从全部 summary.json 重建一份唯一可信的分析数据，供所有主表使用。

**动因（评审 P0-1 / P0-2）**：正文 Table 1、附录 Table 11、Figure 2 之间的
成功率数字出现不一致（如 Qwen3.8-Max 的 Δ 一处 +2.0、一处 +2.22）。根因已查明：

  · `e2_main24` 是权威主矩阵（4,320 格），其中恰好 **1 格**因 provider 超时而失败
    且未评分：`t5_qwen3.8-max_u-glm-5.3_zh_s1`；
  · `e2_main` 目录里存有该格的**成功重跑**（以及另外 179 格重复记录，其中
    143 格时间戳逐字相同、36 格同批不同记录、仅 1 格 reward 不同——即本次补的那格）；
  · 一个脚本把这格**计入分母当失败**（qwen3.8-max Δ = +2.037 → 显示 +2.0），
    另一个把它**剔除**（Δ = +2.217 → +2.22）。两者都不是"算错"，而是分母不同。

**本表的权威规则**：以 `e2_main24` 为基准，对其中失败/未评分的格，
若 `e2_main` 有评分版本则**补入该重跑**（补的是真实观测，不是插值）。
结果恰好 4,320 格、每智能体每语言 540 格、零失败。

每行一条 episode，字段：
  cell_id, tag, task_id, agent, sim, user_lang, env_lang, seed,
  reward_full, reward_db, reward_sub, collapse, status,
  agent_steps, user_turns, tokens_total, first_tok, n_err

`reward_db` = τ-bench 的 `r_actions`（数据库终态哈希），`reward_sub` = `r_outputs`
（英文子串匹配）。**恒有 reward_db ≥ reward_full**（full = db AND sub）。

用法：
  python3 scripts/frozen_table.py                 # 建表并打印对账摘要
  python3 scripts/frozen_table.py --write         # 落盘 results/frozen_table.csv
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db_replay import replay_db  # noqa: E402  （修正后的 DB 判定，见 DEVIATIONS D17）

# 权威主矩阵：e2_main24 为基准；其中失败/未评分的格用 e2_main 里的成功重跑补入。
# 其余 e2_main 内容（143 格逐字重复 + 36 格同批重记）不参与——避免重复计数。
BASE_TAG, PATCH_TAG = "e2_main24", "e2_main"
RUN_NEED, TOK_NEED = 5, 2


def collapsed(tr: dict, run_need: int = RUN_NEED, tok: int = TOK_NEED) -> int:
    run = best = 0
    for st in tr.get("agent_trace", []):
        if st.get("action") == "respond" and st.get("completion_tokens", 0) <= tok:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return int(best >= run_need)


def row_of(sp: str) -> dict | None:
    d = json.loads(Path(sp).read_text(encoding="utf-8"))
    spec = d.get("spec") or {}
    if d.get("error"):
        return None  # 失败格不进冻结表（另计）
    tp = Path(sp.replace("summary.json", "transcript.json"))
    tr = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
    rd = d.get("reward_detail") or {}
    trace = tr.get("agent_trace", [])
    obs = [s.get("observation") or "" for s in trace if s.get("action") != "respond"]
    at = d.get("agent_totals") or {}
    ut = d.get("user_totals") or {}
    # 修正后的 DB 判定：从 agent_trace 重放工具调用，不依赖被污染的 env.data。
    db_true = replay_db(spec.get("task_split", "test"), spec["task_id"], trace)
    sub_true = rd.get("r_outputs")
    return {
        "cell_id": d["cell_id"],
        "tag": spec.get("tag"),
        "task_id": spec["task_id"],
        "agent": spec["agent_model"],
        "sim": spec["user_model"],
        "user_lang": spec["user_lang"],
        "env_lang": spec.get("env_lang", "en"),
        "seed": spec["seed"],
        # 权威列 = 重放修正后的值（D17）
        "reward_full": int(bool(db_true) and bool(sub_true)),
        "reward_db": db_true,
        "reward_sub": int(bool(sub_true)),
        # 归档列：跑批当时写入的值，保留以便对账（会话结束路径受污染）
        "reward_full_archived": int(bool(d.get("reward"))),
        "reward_db_archived": int(bool(rd.get("r_actions"))),
        "collapse": collapsed(tr),
        "status": d.get("stop_reason"),
        "agent_steps": d.get("agent_steps", 0),
        "user_turns": d.get("user_turns", 0),
        "tokens_total": at.get("total_tokens", 0) + ut.get("total_tokens", 0),
        "first_tok": (trace[0].get("prompt_tokens") if trace else None),
        "n_err": sum(1 for o in obs
                     if o.startswith("Error: ") or o.startswith("错误：")),
    }


def build() -> tuple[list[dict], list[str]]:
    """返回 (冻结表行, 被补入的失败格 id 列表)。"""
    rows: dict[str, dict] = {}
    failed: list[str] = []
    for sp in sorted(glob.glob(str(ROOT / "runs" / BASE_TAG / "*" / "summary.json"))):
        r = row_of(sp)
        if r is None:
            d = json.loads(Path(sp).read_text(encoding="utf-8"))
            failed.append(d["cell_id"])
            continue
        r["batch"] = BASE_TAG
        rows[r["cell_id"]] = r
    patched = []
    for cid in failed:
        sp = ROOT / "runs" / PATCH_TAG / cid / "summary.json"
        if not sp.exists():
            continue
        r = row_of(str(sp))
        if r is None:
            continue
        r["batch"] = f"{PATCH_TAG}(补)"
        rows[cid] = r
        patched.append(cid)
    return list(rows.values()), patched


def audit(rows: list[dict], patched: list[str]) -> None:
    print("=" * 78)
    print("冻结分析表 · 对账摘要")
    print("=" * 78)
    n = len(rows)
    print(f"\n  总格数 {n}")
    by_tag = collections.Counter(r["batch"] for r in rows)
    for t, c in sorted(by_tag.items()):
        print(f"    {t:<14}{c:>6}")
    print(f"\n  补入的失败格重跑（{len(patched)}）：")
    for c in patched:
        print(f"    {c}")

    # 关键不变量：full reward ⟺ (db AND sub)，且 db ≥ full
    viol = [r for r in rows
            if r["reward_db"] is not None and r["reward_sub"] is not None
            and int(r["reward_db"] and r["reward_sub"]) != int(r["reward_full"])]
    print(f"\n  [不变量] full == (db AND sub) 的违例：{len(viol)}")
    bad_le = [r for r in rows
              if r["reward_db"] is not None and r["reward_full"] is not None
              and r["reward_db"] < r["reward_full"]]
    print(f"  [不变量] db ≥ full 的违例：{len(bad_le)}")
    miss = [r for r in rows if r["reward_db"] is None or r["reward_sub"] is None]
    print(f"  未记录 db/sub 分量的格：{len(miss)}")

    # 归档 vs 重放（D17）
    arch_db = sum(1 for r in rows if r["reward_db_archived"])
    arch_full = sum(1 for r in rows if r["reward_full_archived"])
    print("\n  [D17] 归档值 vs 重放修正值：")
    print(f"    DB-only 通过：归档 {arch_db} → 修正 {sum(1 for r in rows if r['reward_db'])}")
    print(f"    Full    通过：归档 {arch_full} → 修正 {sum(1 for r in rows if r['reward_full'])}")
    print(f"    会话结束路径（conversation_done）的格："
          f"{sum(1 for r in rows if r['status'] == 'conversation_done')}")

    # 每 (agent, user_lang) 的整数计数
    print("\n  按智能体 × 用户语言（整数计数）：")
    print(f"    {'agent':<22}{'lang':<6}{'n':>6}{'full':>7}{'db':>7}{'sub':>7}{'col':>6}")
    key = ("agent", "user_lang")
    grp = collections.defaultdict(list)
    for r in rows:
        grp[(r["agent"], r["user_lang"])].append(r)
    for a in sorted({r["agent"] for r in rows}):
        for lang in ("en", "zh"):
            rs = grp.get((a, lang), [])
            if not rs:
                continue
            full = sum(1 for r in rs if r["reward_full"])
            db = sum(1 for r in rs if r["reward_db"])
            sub = sum(1 for r in rs if r["reward_sub"])
            col = sum(r["collapse"] for r in rs)
            print(f"    {a:<22}{lang:<6}{len(rs):>6}{full:>7}{db:>7}{sub:>7}{col:>6}")
            # db 只应 ≥ full
            assert db >= full, f"{a}/{lang}: db {db} < full {full}"

    print("\n  Δ(zh−en) 用**未四舍五入的整数计数**算：")
    print(f"    {'agent':<22}{'Δfull':>9}{'Δdb':>9}{'Δsub':>9}")
    for a in sorted({r["agent"] for r in rows}):
        en, zh = grp.get((a, "en"), []), grp.get((a, "zh"), [])
        if not en or not zh:
            continue
        df = 100 * (sum(1 for r in zh if r["reward_full"]) / len(zh)
                    - sum(1 for r in en if r["reward_full"]) / len(en))
        dd = 100 * (sum(1 for r in zh if r["reward_db"]) / len(zh)
                    - sum(1 for r in en if r["reward_db"]) / len(en))
        ds = 100 * (sum(1 for r in zh if r["reward_sub"]) / len(zh)
                    - sum(1 for r in en if r["reward_sub"]) / len(en))
        print(f"    {a:<22}{df:>+9.3f}{dd:>+9.3f}{ds:>+9.3f}")
    en_all = [r for r in rows if r["user_lang"] == "en"]
    zh_all = [r for r in rows if r["user_lang"] == "zh"]
    if en_all and zh_all:
        df = 100 * (sum(1 for r in zh_all if r["reward_full"]) / len(zh_all)
                    - sum(1 for r in en_all if r["reward_full"]) / len(en_all))
        dd = 100 * (sum(1 for r in zh_all if r["reward_db"]) / len(zh_all)
                    - sum(1 for r in en_all if r["reward_db"]) / len(en_all))
        print(f"    {'POOLED':<22}{df:>+9.3f}{dd:>+9.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    rows, patched = build()
    audit(rows, patched)
    if a.write:
        cols = ["cell_id", "tag", "batch", "task_id", "agent", "sim", "user_lang",
                "env_lang", "seed", "reward_full", "reward_db", "reward_sub",
                "reward_full_archived", "reward_db_archived",
                "collapse", "status", "agent_steps", "user_turns", "tokens_total",
                "first_tok", "n_err"]
        out = ROOT / "results" / "frozen_table.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in cols})
        print(f"\n  已写 {out}（{len(rows)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
