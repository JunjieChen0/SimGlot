#!/usr/bin/env python3
"""评分器口径的三方对照（独立代码审计 P0-1）。

**问题**：`harness/scoring.py` 在 τ-bench 原生评分之上做了两处改动——
文本归一化（NFKC、去千分位逗号、小写）与 `data/output_aliases.json` 的双语同义说法表——
而论文 §3.4 曾写「preserve the canonical scorer without modification」。审计指出该表述不实。

**本脚本**：直接从 `runs/` 的 `transcript.json`（智能体所有 RESPOND 内容）与
`summary.json`（要求输出的字符串）逐集重算三种口径下的标签：

  A. **Canonical τ-bench**：`output.lower() in content.lower().replace(",", "")`
     逐字复刻 `vendor/tau-bench/tau_bench/envs/base.py:145-152`，无归一化、无别名。
  B. **SimGlot 扩展**：NFKC 归一 + 去逗号 + 小写 + 别名表（即论文实际使用的口径）。
     若与 summary 中存档的 `r_outputs` 不一致，脚本会报出——这是内部一致性自检。
  C. **DB-only**：只取 `r_actions`（与语言无关的那一半）。

对每种口径报告：标签与存档口径不同的条数、四智能体 × 两臂的成功率、以及语言效应。

用法：python3 scripts/scorer_variants.py
"""

from __future__ import annotations

import collections
import glob
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import _offline  # noqa: E402,F401  离线分析引导
from db_replay import replay_db  # noqa: E402  （D17 修正后的 DB 判定）

TAGS = ["e2_main24", "e2_main"]          # 主矩阵（含 1 格补入的重跑）
OUT = ROOT / "results" / "scorer_variants.txt"
ALIAS = ROOT / "data" / "output_aliases.json"

AGENTS = ["deepseek-v4.1-flash", "qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash"]
LABEL = {"deepseek-v4.1-flash": "DeepSeek-V4.1-Flash", "qwen3.7-plus": "Qwen3.7-Plus",
         "qwen3.8-max": "Qwen3.8-Max", "qwen3.8-flash": "Qwen3.8-Flash"}


def canon_hit(required: str, contents: list[str]) -> bool:
    """τ-bench 原生匹配：逐字复刻 base.py，只在 content 侧去逗号。"""
    needle = required.lower()
    return any(needle in c.lower().replace(",", "") for c in contents)


def norm(text: str) -> str:
    """SimGlot 扩展的归一化：NFKC + 去逗号 + 小写。"""
    return unicodedata.normalize("NFKC", str(text or "")).replace(",", "").lower()


def ext_hit(required: str, contents: list[str], aliases: list[str]) -> bool:
    needles = [norm(required)] + [norm(a) for a in aliases]
    return any(n and n in norm(c) for c in contents for n in needles)


def load_aliases() -> dict:
    if not ALIAS.exists():
        return {}
    raw = json.loads(ALIAS.read_text(encoding="utf-8"))
    return {str(k): v for k, v in (raw.get("aliases") or {}).items()}


def respond_contents(tr: dict) -> list[str]:
    out = []
    for st in tr.get("agent_trace", []):
        if st.get("action") == "respond":
            c = (st.get("kwargs") or {}).get("content")
            if c:
                out.append(str(c))
    return out


def main() -> int:
    aliases = load_aliases()
    rows, mismatch, missing = [], 0, 0
    # 与 frozen_table.py 同一套去重规则：e2_main24 为基准，
    # 其中失败/未评分的格用 e2_main 的同名成功重跑补入；e2_main 其余记录不参与。
    specs = []
    failed = []
    for sp in sorted(glob.glob(str(ROOT / "runs" / "e2_main24" / "*" / "summary.json"))):
        d = json.loads(Path(sp).read_text(encoding="utf-8"))
        if d.get("error"):
            failed.append(d["cell_id"])
            continue
        specs.append(sp)
    for cid in failed:
        sp = ROOT / "runs" / "e2_main" / cid / "summary.json"
        if sp.exists():
            specs.append(str(sp))
    for sp in specs:
            d = json.loads(Path(sp).read_text(encoding="utf-8"))
            spec = d.get("spec") or {}
            if spec.get("env_lang", "en") != "en":      # 主矩阵只取 en 环境
                continue
            tp = Path(sp.replace("summary.json", "transcript.json"))
            if not tp.exists() or d.get("error"):
                missing += 1
                continue
            sc = d.get("score") or {}
            outputs = sc.get("outputs") or {}
            if not outputs:                              # 该任务无 output 约束
                r_out_c = r_out_e = True
            else:
                tr = json.loads(tp.read_text(encoding="utf-8"))
                contents = respond_contents(tr)
                r_out_c = all(canon_hit(req, contents) for req in outputs)
                r_out_e = all(ext_hit(req, contents, outputs[req].get("accepted_as", [])[1:])
                              for req in outputs)
                if r_out_e != bool(sc.get("r_outputs")):
                    mismatch += 1
            # D17：DB 判定改用轨迹重放；归档的 r_actions 在会话结束路径上被污染
            r_act = bool(replay_db((spec or {}).get("task_split", "test"),
                                   spec["task_id"],
                                   json.loads(tp.read_text(encoding="utf-8")).get("agent_trace", [])))
            r_act_arch = bool(sc.get("r_actions"))
            rows.append({
                "cell": d.get("cell_id"),
                "task": spec.get("task_id"),
                "agent": spec.get("agent_model"),
                "lang": spec.get("user_lang"),
                "canon": 1.0 if (r_act and r_out_c) else 0.0,
                "ext": 1.0 if (r_act and r_out_e) else 0.0,
                "db": 1.0 if r_act else 0.0,
                "db_arch": 1.0 if r_act_arch else 0.0,
                "out_c": r_out_c, "out_e": r_out_e,
            })

    out = []

    def P(s=""):
        out.append(s)
        print(s)

    P("=" * 80)
    P("评分器口径三方对照 · 主矩阵（en 环境）")
    P("=" * 80)
    P(f"\n  可用评分记录 {len(rows)}｜缺 transcript/异常 {missing}"
      f"｜扩展口径与存档 r_outputs 不一致 {mismatch}")
    if mismatch:
        P("  ** 不一致说明实现与脚本有差异，须先排查 **")

    by_lang = collections.Counter(r["lang"] for r in rows)
    P(f"  每臂集数：{dict(by_lang)}")

    P("\n── 1. 标签在不同口径下是否改变 ──")
    chg_ce = sum(1 for r in rows if r["canon"] != r["ext"])
    chg_cd = sum(1 for r in rows if r["canon"] != r["db"])
    chg_ed = sum(1 for r in rows if r["ext"] != r["db"])
    P(f"  canonical vs 扩展   ：{chg_ce:>5} 集不同（{100*chg_ce/len(rows):.2f}%）")
    P(f"  canonical vs DB-only：{chg_cd:>5} 集不同（{100*chg_cd/len(rows):.2f}%）")
    P(f"  扩展      vs DB-only：{chg_ed:>5} 集不同（{100*chg_ed/len(rows):.2f}%）")
    P(f"\n  输出侧单独看（不含 DB）：canonical 命中 {sum(r['out_c'] for r in rows)}"
      f"｜扩展命中 {sum(r['out_e'] for r in rows)}｜差 {sum(r['out_e'] for r in rows)-sum(r['out_c'] for r in rows)}")
    for lang in ("en", "zh"):
        sub = [r for r in rows if r["lang"] == lang]
        P(f"    {lang}: canonical {sum(r['out_c'] for r in sub)}/{len(sub)}"
          f"｜扩展 {sum(r['out_e'] for r in sub)}/{len(sub)}")

    # ── 1b. 与修正后总数的对账（第八轮评审 P0-1 的回归检查）──────────────────
    # 评审发现：论文 §3.4 曾写 (A) 与 (C) 有 121 集不同，而本脚本给出 54。
    # 两个数分别对应两套评分标签：121 = 4,194 − 4,073 是**归档（受污染）**口径下的
    # DB-only 与 Full 之差；54 = 2,883 − 2,829 是**修正后**的同一种差。
    # 这里把它显式算出来并断言，使「论文与产物不一致」这类错误在脚本层就能暴露。
    n_full, n_db = sum(r["ext"] for r in rows), sum(r["db"] for r in rows)
    P("\n── 1b. (A) vs (C) 的差 = 修正后 DB-only − Full Reward（对账）──")
    P(f"  修正后：DB-only {n_db}｜Full(扩展) {n_full}｜差 {n_db - n_full}"
      f"（论文 §3.4 应引用此数；本行 = 上文 canonical vs DB-only 的 {chg_cd}）")
    P(f"  归档（受污染，已作废）：DB 4,194 − Full 4,073 = 121 —— 论文旧稿误引此数。")
    assert n_db - n_full == chg_cd, (
        f"(A) vs (C) 的差 {chg_cd} 与 DB-only−Full 的差 {n_db - n_full} 必须相等")
    P("  ✓ 断言通过：(A) vs (C) 的差与「DB-only − Full」逐集一致。")

    P("\n── 2. 三种口径下的成功率与语言效应 ──")
    P(f"  {'agent':<22}{'口径':<11}{'en':>9}{'zh':>9}{'Δ(zh−en)':>11}")
    for ag in AGENTS:
        for key, name in (("canon", "canonical"), ("ext", "extended"), ("db", "DB-only")):
            en = [r[key] for r in rows if r["agent"] == ag and r["lang"] == "en"]
            zh = [r[key] for r in rows if r["agent"] == ag and r["lang"] == "zh"]
            if not en or not zh:
                continue
            a, b = 100 * sum(en) / len(en), 100 * sum(zh) / len(zh)
            P(f"  {LABEL[ag]:<22}{name:<11}{a:>8.1f}%{b:>8.1f}%{b-a:>+10.2f}")
    P("")
    for key, name in (("canon", "canonical"), ("ext", "extended"), ("db", "DB-only")):
        en = [r[key] for r in rows if r["lang"] == "en"]
        zh = [r[key] for r in rows if r["lang"] == "zh"]
        a, b = 100 * sum(en) / len(en), 100 * sum(zh) / len(zh)
        P(f"  {'POOLED':<22}{name:<11}{a:>8.1f}%{b:>8.1f}%{b-a:>+10.2f}")

    P("\n  读法：canonical 与 extended 的差就是「同义说法表 + 归一化」的净影响；")
    P("        两者都在 DB 之上，故 DB-only 列与前两列不可直接比。")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    P(f"\n  已写 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
