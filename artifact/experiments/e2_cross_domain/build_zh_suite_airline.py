#!/usr/bin/env python3
"""为 E2 构建 **τ-bench airline** 的中文任务套件，并做机器保真校验。

与 v1.0 的 `simglot/scripts/build_zh_suite.py` 同一套口径（那套用于 retail）：
译文由模型产出，**正确性由机器校验承担**，校验任一不过即报错、不做静默通过。

校验项
  A 硬 token 保全：id / 机场三字码 / 航班号 / ISO 日期 / 全部数字，必须**逐字**出现在中文里
  B 覆盖完整    ：50 条 airline 测试任务一条不漏、不多
  C 无游离英文  ：中文里的拉丁片段若不属于硬 token 集合，列为可疑（报出，人工复核）
  D 长度合理    ：中文/英文长度比落在合理区间，离群者列出

用法：
  cd sqj && python3 swe/build_zh_suite_airline.py --dry-run     # 只打印提示与规模
  cd sqj && python3 swe/build_zh_suite_airline.py               # 真跑（50 次调用，约数万 token）
产出：sqj/data/tasks_zh_airline.json（机器用）、sqj/data/tasks_zh_airline.md（人工复核用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQJ = HERE.parent
SIMGLOT = SQJ.parent / "simglot"
for _p in (str(SIMGLOT), str(SIMGLOT / "vendor" / "tau-bench")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _bootstrap  # noqa: E402,F401  离线引导：必须在 tau_bench / harness 之前

from tau_bench.envs.airline.tasks_test import TASKS as AIRLINE_TASKS  # noqa: E402

OUT_JSON = SQJ / "data" / "tasks_zh_airline.json"
OUT_MD = SQJ / "data" / "tasks_zh_airline.md"
TRANSLATOR = "qwen3.8-max"          # 译文质量优先；50 条短指令，成本可忽略

# 硬 token：必须逐字保留
PAT_ID = re.compile(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*_\d+\b")  # mia_li_3668 / certificate_7504069
PAT_ACRONYM = re.compile(r"\b[A-Z]{3}\b")                     # 三字母大写：可能是机场码，也可能是 DOB/EST/USD
PAT_FLIGHT = re.compile(r"\b[A-Z]{2,}\d+\b")                 # HAT136
PAT_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PAT_NUM = re.compile(r"\d+(?:\.\d+)?")
# 机场三字码：**不靠字形猜**——`[A-Z]{3}` 会把 DOB / EST / USD 这类缩写一起圈进来（踩过）。
# 真值取自数据集的航班表（origin/destination 的全集），只在它**也出现在英文指令里**时才要求保留。
# 反例：任务 #33 的英文正文一个机场码都没有（"any flights over 3 hours"），机场码只存在于
# 参考答案动作里——那种情况下译文当然不该出现机场码。

SYSTEM = (
    "You are a professional translator. Translate the user instruction below into natural, "
    "colloquial **Simplified Chinese** as spoken by a customer talking to a service agent.\n"
    "Rules:\n"
    "  1. Preserve VERBATIM (do not translate, do not reformat): every user id, every booking/"
    "certificate/credit-card id, every 3-letter airport code, every flight number, and every "
    "date given in ISO form (YYYY-MM-DD).\n"
    "  2. Translate month/day expressions into Chinese form (e.g. 'May 20' -> '5月20日').\n"
    "  3. Keep every other number unchanged (prices, counts, baggage counts).\n"
    "  4. Translate the whole instruction, INCLUDING the meta-instruction at the end about how "
    "you behave with the agent (e.g. 'You are reactive to the agent and will not say anything "
    "that is not asked') -- that part is part of what the user is told.\n"
    "  5. Do not add, remove, or explain anything. Do not add a preamble.\n"
    "Output STRICT JSON only: {\"zh\": \"<translation>\", \"notes\": \"<short note or empty>\"}"
)


def known_airports() -> set[str]:
    """数据集里真实出现过的机场三字码（取自航班的 origin/destination 全集）。"""
    data = SIMGLOT / "vendor" / "tau-bench" / "tau_bench" / "envs" / "airline" / "data" / "flights.json"
    flights = json.loads(data.read_text(encoding="utf-8"))
    out = set()
    for f in (flights.values() if isinstance(flights, dict) else flights):
        for k in ("origin", "destination"):
            if isinstance(f, dict) and f.get(k):
                out.add(str(f[k]))
    return out


_AIRPORTS: set[str] | None = None


def hard_tokens(text: str, task=None) -> list[str]:
    """必须逐字保留的 token：各种 id、ISO 日期、航班号、**正文里出现的**机场码、全部数字。"""
    global _AIRPORTS
    if _AIRPORTS is None:
        _AIRPORTS = known_airports()
    toks: set[str] = set()
    for pat in (PAT_ID, PAT_ISO, PAT_FLIGHT):
        toks.update(pat.findall(text))
    toks.update(PAT_NUM.findall(text))
    toks.update(t for t in PAT_ACRONYM.findall(text) if t in _AIRPORTS)
    return sorted(toks)


def latin_runs(text: str) -> list[str]:
    """抽拉丁片段。**必须剥掉句末的点**——`.` 在字符类里会把 "Texas." 整段吃进来，
    于是英文里是 `Texas.`、中文里是 `Texas`，两者对不上，会被误报成"可疑"（踩过）。"""
    out = []
    for m in re.findall(r"[A-Za-z][A-Za-z0-9_.@#-]*", text):
        m = m.rstrip(".").strip()
        if m and not m.isdigit():
            out.append(m)
    return out


def english_latin(text: str) -> set[str]:
    """英文原文里出现过的拉丁片段——它们是**数据**（人名/地名/支付方式缩写），
    译文中保留它们是**正确行为**，不算"游离英文"。"""
    return set(latin_runs(text))


def translate(client, instruction: str) -> tuple[str, str]:
    res = client.chat(model=TRANSLATOR,
                      messages=[{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": instruction}],
                      max_tokens=1200)
    m = re.search(r"\{.*\}", res.content, flags=re.S)
    if not m:
        raise ValueError(f"译文不是 JSON：{res.content[:200]!r}")
    d = json.loads(m.group(0))
    return str(d.get("zh", "")).strip(), str(d.get("notes", "")).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--revalidate", action="store_true",
                    help="不重新翻译，只对已有 JSON 重跑校验并重生成 .md（零 token）")
    args = ap.parse_args()

    tasks = list(AIRLINE_TASKS)
    print(f"airline 测试任务 {len(tasks)} 条｜翻译模型 {TRANSLATOR}")
    total_chars = sum(len(t.instruction) for t in tasks)
    print(f"英文合计 {total_chars:,} 字符 → 预估 ≈ {total_chars//3 + len(tasks)*220:,} token 输入"
          f" + ≈ {total_chars//2:,} token 输出")
    if args.dry_run:
        print("\n--- 样例指令 ---\n" + tasks[0].instruction[:400])
        print("\n硬 token（样例）:", hard_tokens(tasks[0].instruction, tasks[0])[:20])
        return 0

    if args.revalidate:
        rows = json.loads(OUT_JSON.read_text(encoding="utf-8"))["tasks"]
        errors, warns = [], []
        for i, t in enumerate(tasks):
            r = rows[i]
            zh = r["zh"]
            need = hard_tokens(t.instruction, t)
            missing = [h for h in need if h not in zh]
            allowed = {a.lower() for a in (set(need) | english_latin(t.instruction))}
            stray = sorted({x for x in latin_runs(zh) if x.lower() not in allowed})
            ratio = len(zh) / max(1, len(t.instruction))
            r.update({"invariants": need, "char_ratio": round(ratio, 3)})
            if missing:
                errors.append(f"#{i} A 硬 token 丢失：{missing}")
            if ratio < 0.25 or ratio > 1.2:
                warns.append(f"#{i} D 长度比 {ratio:.2f} 离群")
            if stray:
                warns.append(f"#{i} C 可疑拉丁片段：{stray[:8]}")
        return _finish(rows, errors, warns, tasks)

    from harness.client import BailianClient
    client = BailianClient(channel="token_plan", role="translator",
                           log_path=SQJ / "runs" / "zh_airline_translate_calls.jsonl")

    items = tasks[:args.limit] if args.limit else tasks
    rows, errors, warns = [], [], []
    for i, t in enumerate(items):
        zh, notes = translate(client, t.instruction)
        need = hard_tokens(t.instruction, t)
        missing = [h for h in need if h not in zh]
        allowed = {a.lower() for a in (set(need) | english_latin(t.instruction))}
        stray = sorted({r for r in latin_runs(zh) if r.lower() not in allowed})
        ratio = len(zh) / max(1, len(t.instruction))
        rows.append({"task_id": i, "en": t.instruction, "zh": zh, "invariants": need,
                     "notes": notes, "char_ratio": round(ratio, 3)})
        if missing:
            errors.append(f"#{i} A 硬 token 丢失：{missing}")
        if ratio < 0.25 or ratio > 1.2:
            warns.append(f"#{i} D 长度比 {ratio:.2f} 离群")
        if stray:
            warns.append(f"#{i} C 可疑拉丁片段：{stray[:8]}")
        print(f"  [{i+1:>2}/{len(items)}] #{i} zh={len(zh):>4}字 ratio={ratio:.2f}"
              f"{'  ✗ 缺 '+str(missing[:4]) if missing else ''}", flush=True)

    return _finish(rows, errors, warns, tasks)


def _finish(rows, errors, warns, tasks):
    # B 覆盖完整
    if len(rows) != len(tasks):
        errors.append(f"B 覆盖不完整：{len(rows)}/{len(tasks)}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"n": len(rows), "design": "τ-bench airline 测试集，逐条译自英文原指令",
         "translator": TRANSLATOR, "tasks": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    md = ["# airline 中文任务套件（人工复核用）", "",
          f"- 条数：{len(rows)}｜译自：τ-bench airline `tasks_test.py`｜模型：{TRANSLATOR}",
          "- **验收口径**：机器校验保真（硬 token 逐字保全 + 覆盖完整），语义等价由人工复核。", ""]
    for r in rows:
        md += [f"## 任务 {r['task_id']}（长度比 {r['char_ratio']}）", "",
               "**EN**", "", r["en"], "", "**ZH**", "", r["zh"], "",
               f"`硬 token`：{' '.join(r['invariants'])}", ""]
    if warns:
        md += ["## 可疑清单", ""] + [f"- {w}" for w in warns] + [""]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("=" * 78)
    print(f"写入 {OUT_JSON.relative_to(SQJ.parent)} ｜ {OUT_MD.relative_to(SQJ.parent)}")
    print(f"错误 {len(errors)} 项｜可疑 {len(warns)} 项")
    for e in errors[:20]:
        print("  ✗ " + e)
    for w in warns[:20]:
        print("  ! " + w)
    r = [x["char_ratio"] for x in rows]
    if r:
        print(f"长度比：min {min(r):.2f} 中位 {statistics.median(r):.2f} max {max(r):.2f}")
    if errors:
        print("\n**有保真错误 → 不可用于实验**，请修正后重跑。")
        return 1
    print("\n✓ 硬校验全过（硬 token 保全 + 覆盖完整）。语义等价仍需人工过一遍 .md。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
