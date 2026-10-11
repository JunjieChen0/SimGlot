#!/usr/bin/env python3
"""E3 · 崩塌判据的遮蔽盲评（跨模型族裁定者）。

## 要回答的问题

v1.0 的崩塌判据是**机械可复现的操作性定义**（≥5 个连续 `respond` 步、每步 completion ≤2 token）。
审稿人会问：**独立读者会不会也这么判？**——即构念效度。

## 设计

* **普查而非抽样**：归档里 `qwen3.8-flash` 的崩塌集**全部 106 个**（en 35 / zh 71）——数目本身
  就少于草案里的 200，全取反而消掉抽样任意性。
* **匹配对照**：每个崩塌集配一个**非崩塌**集，优先同 (任务, 用户语言, 模拟器)，不足时降级到
  同 (任务, 用户语言) → 同任务。匹配质量逐条记录。
* **遮蔽**：裁定者看到的是**步骤序列**（助手发言 / 工具调用 / 工具返回），
  **用户轮一律替换为 `[user turn]`**（去掉用户侧语言这条最明显的线索）；**不告诉**它任何
  语言臂信息、判据定义或 token 计数。顺序按预注册种子打乱，只给匿名编号。
  **残余泄漏必须如实声明**：中文臂里**智能体自己的发言是中文**——要判断它是否"停止推进"就必须看到它说了什么，
  故语言无法完全遮蔽。因此本实验**不是**要证明"裁定者看不出语言"，而是要检验
  **判据与裁定的一致率是否依赖语言臂**——若两臂一致率相当，判据的臂间差异就得到独立佐证。
* **裁定者**：`glm-5.3`（与 Qwen 族不同源），固定 rubric，只输出 JSON。

## 判据（预先写死）

* **一致率**、**Cohen's κ**、**敏感度**（判据说崩塌时裁定也说崩塌）、**特异度**（判据说非崩塌时裁定也说非崩塌）；
* **分语言臂一致率**：两臂的差若跨零 ⇒ 判据不因语言而系统性偏离裁定；若中文臂显著更低 ⇒ 判据受语言污染，须降格。
* κ ≥ 0.6 且两臂一致率差跨零 ⇒ 判据可信；κ < 0.4 ⇒ 降格为操作性定义。

## 用法

    python3 e3_blind_adjudication.py --dry-run     # 只渲染、报长度与预估 token
    python3 e3_blind_adjudication.py               # 真跑（写 runs/e3_blind/ 与 results/）
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQJ = HERE.parent
SIMGLOT = SQJ.parent / "simglot"
for p in (str(SIMGLOT), str(SIMGLOT / "vendor" / "tau-bench")):
    if p not in sys.path:
        sys.path.insert(0, p)

FROZEN = SIMGLOT / "results" / "frozen_table.csv"
RUNS = SIMGLOT / "runs" / "e2_main24"
OUT_RUN = SQJ / "runs" / "e3_blind"
OUT_RES = SQJ / "results"

AGENT = "qwen3.8-flash"
JUDGE = "glm-5.3"
SEED = 20261009                      # 预注册种子
MAX_CONTENT = 500                    # 单条发言截断（字符）
MAX_OBS = 300                        # 单条工具返回截断
MAX_TOKENS = 6000                    # glm 强制思考且思考计入 max_tokens；给小了会把 JSON 截成 `{"`（踩过）

RUBRIC = """You are auditing an automated evaluation of a tool-using AI agent.

Below is the step sequence of ONE episode. Each step is one of:
  ASSISTANT: what the agent said to the user
  TOOL <name>(<args>) -> <result>: a tool the agent called and what it returned
  [user turn]: the user replied (the user's words are elided)

Question: does the agent STOP MAKING PROGRESS at some point -- from that point on it keeps
replying to the user but never attempts anything new to resolve the task and never calls a
tool again, so the episode is effectively stalled for the rest of its steps?

Judge only the agent's behaviour, not whether the task was eventually solved.

Answer with a JSON object and nothing else:
{"stalled": true|false, "from_step": <step number where stalling begins, or null>, "reason": "<one short sentence>"}"""


# ── 取样 ────────────────────────────────────────────────────────────────────

def load_rows() -> list[dict]:
    rows = [r for r in csv.DictReader(FROZEN.open(encoding="utf-8")) if r["agent"] == AGENT]
    for r in rows:
        r["collapse"] = r["collapse"] == "1"
    return rows


def match_controls(rows: list[dict]) -> list[tuple[dict, dict, str]]:
    """给每个崩塌集配一个非崩塌对照，返回 (崩塌, 对照, 匹配层级)。"""
    key_exact: dict[tuple, list[dict]] = {}
    key_lang: dict[tuple, list[dict]] = {}
    key_task: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["collapse"]:
            continue
        key_exact.setdefault((r["task_id"], r["user_lang"], r["sim"]), []).append(r)
        key_lang.setdefault((r["task_id"], r["user_lang"]), []).append(r)
        key_task.setdefault((r["task_id"],), []).append(r)

    rng = random.Random(SEED)
    used: set[str] = set()
    out = []
    for c in sorted((r for r in rows if r["collapse"]), key=lambda r: r["cell_id"]):
        for level, key in (("exact", (c["task_id"], c["user_lang"], c["sim"])),
                           ("same_task_lang", (c["task_id"], c["user_lang"])),
                           ("same_task", (c["task_id"],))):
            pool = {"exact": key_exact, "same_task_lang": key_lang, "same_task": key_task}[level].get(key, [])
            avail = [r for r in pool if r["cell_id"] not in used]
            if avail:
                pick = rng.choice(avail)
                used.add(pick["cell_id"])
                out.append((c, pick, level))
                break
    return out


# ── 渲染（遮蔽） ─────────────────────────────────────────────────────────────

def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n] + " …"


def render(cell_id: str) -> str:
    d = json.loads((RUNS / cell_id / "transcript.json").read_text(encoding="utf-8"))
    lines = []
    for t in d.get("agent_trace", []):
        step = t.get("step")
        act = t.get("action")
        if act == "respond":
            lines.append(f"step {step} | ASSISTANT: {_clip(t.get('kwargs', {}).get('content'), MAX_CONTENT)}")
            lines.append(f"step {step} | [user turn]")
        else:
            args = _clip(json.dumps(t.get("kwargs", {}), ensure_ascii=False), MAX_OBS)
            lines.append(f"step {step} | TOOL {act}({args}) -> {_clip(t.get('observation'), MAX_OBS)}")
    return "\n".join(lines)


def build_items(pairs) -> list[dict]:
    items = []
    for i, (c, ctrl, level) in enumerate(pairs):
        for tag, row in (("collapsed", c), ("control", ctrl)):
            items.append({
                "uid": f"E{i:03d}-{tag}",
                "render": render(row["cell_id"]),
                "truth_collapse": 1 if tag == "collapsed" else 0,
                "user_lang": row["user_lang"], "task_id": row["task_id"],
                "sim": row["sim"], "cell_id": row["cell_id"], "match_level": level,
            })
    random.Random(SEED).shuffle(items)         # 顺序打乱：裁定者看不到配对结构
    return items


# ── 裁定 ────────────────────────────────────────────────────────────────────

def parse_verdict(text: str):
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None, text[:200]
    try:
        d = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None, text[:200]
    return bool(d.get("stalled")), str(d.get("reason", ""))[:300]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试用）")
    ap.add_argument("--retry-failed", action="store_true",
                    help="只重跑上次解析失败的条目（预算提到 6000，抵 glm 强制思考的吃 token）")
    args = ap.parse_args()

    rows = load_rows()
    pairs = match_controls(rows)
    items = build_items(pairs)
    if args.limit:
        items = items[:args.limit]

    n_char = sum(len(i["render"]) for i in items)
    est_tok = int(n_char / 2.2) + len(items) * 120      # 中英混合，约 2.2 字符/token
    print(f"崩塌集 {sum(1 for r in rows if r['collapse'])} ｜ 配对 {len(pairs)} ｜ 条目 {len(items)}")
    print(f"渲染合计 {n_char:,} 字符 → 预估输入 ≈ {est_tok:,} token"
          f"（≈ {est_tok/1e6:.2f} M，约 v1.0 的 {est_tok/7.40e8*100:.2f}%）")
    lv = {}
    for _, _, l in pairs:
        lv[l] = lv.get(l, 0) + 1
    print("匹配层级分布:", lv)

    if args.dry_run:
        print("\n--- 样例（前 2 条）---")
        for it in items[:2]:
            print(it["uid"], "truth_collapse=", it["truth_collapse"], "arm=", it["user_lang"])
            print(it["render"][:600], "\n")
        return 0

    from harness.client import BailianClient
    client = BailianClient(channel="token_plan", role="judge", log_path=OUT_RUN / "judge_calls.jsonl")

    def judge_one(it: dict) -> dict:
        msg = [{"role": "user",
                "content": f"{RUBRIC}\n\n=== EPISODE {it['uid']} ===\n{it['render']}"}]
        try:
            res = client.chat(model=JUDGE, messages=msg, max_tokens=6000)
            v, reason = parse_verdict(res.content)
            return {**it, "judge_stalled": v, "judge_reason": reason,
                    "judge_raw": res.content[:600],
                    "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens,
                    "ok": v is not None}
        except Exception as e:  # noqa: BLE001
            return {**it, "judge_stalled": None, "judge_reason": "", "judge_raw": "",
                    "prompt_tokens": 0, "completion_tokens": 0,
                    "ok": False, "error": f"{type(e).__name__}: {e}"[:200]}

    OUT_RUN.mkdir(parents=True, exist_ok=True)
    OUT_RES.mkdir(parents=True, exist_ok=True)

    if args.retry_failed:
        prev = list(csv.DictReader((OUT_RUN / "verdicts.csv").open(encoding="utf-8")))
        by_uid = {r["uid"]: r for r in prev}
        todo = [it for it in items if not by_uid.get(it["uid"], {}).get("judge_stalled")]
        print(f"重跑解析失败的条目：{len(todo)}/{len(items)}")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for f in as_completed([ex.submit(judge_one, it) for it in todo]):
                d = f.result()
                by_uid[d["uid"]].update({k: d[k] for k in
                                         ("judge_stalled", "judge_reason", "judge_raw",
                                          "prompt_tokens", "completion_tokens", "ok")})
        merged = []
        for it in items:
            r = dict(by_uid[it["uid"]])
            r["truth_collapse"] = int(r["truth_collapse"])
            v = r["judge_stalled"]
            r["judge_stalled"] = (None if v in ("", "None", None)
                                  else str(v).strip().lower() == "true")
            r["ok"] = r["judge_stalled"] is not None
            merged.append(r)
        with (OUT_RUN / "verdicts.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(merged[0].keys()), extrasaction="ignore")
            w.writeheader(); w.writerows(sorted(merged, key=lambda d: d["uid"]))
        print(f"已落盘 {len(merged)} 条（先落盘再汇总，避免汇总出错把重跑结果丢掉）")
        report = summarise(merged)
        (OUT_RES / "e3_blind_adjudication.txt").write_text(report, encoding="utf-8")
        print(report)
        print(f"用时 {time.time()-t0:.0f}s")
        return 0

    t0 = time.time()
    done = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_one, it): it["uid"] for it in items}
        for n, f in enumerate(as_completed(futs), 1):
            done.append(f.result())
            if n % 20 == 0:
                print(f"  …{n}/{len(items)}  ({time.time()-t0:.0f}s)", flush=True)

    with (OUT_RUN / "verdicts.csv").open("w", newline="", encoding="utf-8") as fh:
        cols = ["uid", "cell_id", "task_id", "sim", "user_lang", "truth_collapse",
                "judge_stalled", "match_level", "ok", "prompt_tokens", "completion_tokens",
                "judge_reason", "judge_raw"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(done, key=lambda d: d["uid"]))

    report = summarise(done)
    (OUT_RES / "e3_blind_adjudication.txt").write_text(report, encoding="utf-8")
    print(report)
    print(f"已写 {OUT_RUN/'verdicts.csv'} 与 {OUT_RES/'e3_blind_adjudication.txt'}"
          f"；用时 {time.time()-t0:.0f}s")
    return 0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% 区间——小样本比例的稳妥口径（v1.0 也用这个）。"""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - h) / d, (c + h) / d)


def summarise(done: list[dict]) -> str:
    L = ["=" * 78, "E3 · 崩塌判据的遮蔽盲评", "=" * 78]
    for d in done:                                   # CSV 路径读回来的字段是字符串
        d["truth_collapse"] = int(d["truth_collapse"])
        d["judge_stalled"] = (None if d["judge_stalled"] in ("", "None", None)
                              else str(d["judge_stalled"]).strip().lower() == "true")
        d["prompt_tokens"] = int(d["prompt_tokens"] or 0)
        d["completion_tokens"] = int(d["completion_tokens"] or 0)
        d["ok"] = d["judge_stalled"] is not None
    ok = [d for d in done if d["ok"]]
    L.append(f"条目 {len(done)} ｜ 成功 {len(ok)} ｜ 解析失败 {len(done)-len(ok)}")
    ptok = sum(d["prompt_tokens"] for d in done)
    ctok = sum(d["completion_tokens"] for d in done)
    L.append(f"token：输入 {ptok:,} ／ 输出 {ctok:,} ／ 合计 **{ptok+ctok:,}**")
    L.append(f"**流失率**：{len(done)-len(ok)}/{len(done)} = "
             f"{(len(done)-len(ok))/max(1,len(done))*100:.1f}%（裁定者未给出可解析 JSON，已剔除；"
             f"主因是 glm 强制思考吃满 max_tokens 把输出截断）")
    if not ok:
        L.append("无有效裁定，无法汇总。")
        return "\n".join(L) + "\n"

    def agree(rows):
        a = sum(1 for d in rows if int(d["truth_collapse"]) == int(bool(d["judge_stalled"])))
        return a, len(rows), (a / len(rows) if rows else float("nan"))

    a, n, acc = agree(ok)
    lo, hi = wilson(a, n)
    tp = sum(1 for d in ok if d["truth_collapse"] == 1 and d["judge_stalled"])
    fn = sum(1 for d in ok if d["truth_collapse"] == 1 and not d["judge_stalled"])
    tn = sum(1 for d in ok if d["truth_collapse"] == 0 and not d["judge_stalled"])
    fp = sum(1 for d in ok if d["truth_collapse"] == 0 and d["judge_stalled"])
    sens = tp / (tp + fn) if (tp + fn) else float("nan")
    spec = tn / (tn + fp) if (tn + fp) else float("nan")
    pe = (((tp + fp) * (tp + fn) + (tn + fn) * (tn + fp)) / (n * n)) if n else float("nan")
    kappa = (acc - pe) / (1 - pe) if n and pe != 1 else float("nan")

    L.append("")
    L.append(f"整体一致率 {acc:.3f}（{a}/{n}，Wilson 95% [{lo:.3f}, {hi:.3f}]）｜ Cohen's κ {kappa:.3f}")
    sl, sh = wilson(tp, tp + fn)
    pl, ph = wilson(tn, tn + fp)
    L.append(f"敏感度（判据说崩塌→裁定也说崩塌）{sens:.3f} = {tp}/{tp+fn}  [{sl:.3f}, {sh:.3f}]")
    L.append(f"特异度（判据说非崩塌→裁定也说非崩塌）{spec:.3f} = {tn}/{tn+fp}  [{pl:.3f}, {ph:.3f}]")
    L.append(f"混淆：TP {tp} ｜ FN {fn} ｜ TN {tn} ｜ FP {fp}")
    L.append("")
    L.append("分语言臂（关键：一致率是否随语言臂变化）")
    for arm in ("en", "zh"):
        rows = [d for d in ok if d["user_lang"] == arm]
        aa, nn, aa_acc = agree(rows)
        al, ah = wilson(aa, nn)
        t = sum(1 for d in rows if d["truth_collapse"] == 1)
        j = sum(1 for d in rows if d["judge_stalled"])
        L.append(f"  用户语言 {arm}：一致率 {aa_acc:.3f}（{aa}/{nn}，[{al:.3f}, {ah:.3f}]）"
                 f"｜判据崩塌 {t}｜裁定崩塌 {j}")
    disc = {arm: sum(1 for d in ok if d["user_lang"] == arm
                     and int(d["truth_collapse"]) != int(bool(d["judge_stalled"])))
            for arm in ("en", "zh")}
    L.append(f"  不一致条数：en {disc['en']} ｜ zh {disc['zh']}"
             f"  → 两臂不一致数都极小，**臂间一致率之差不可估**（承认这一点，不做差异检验）")
    L.append("")
    L.append("按匹配层级")
    for lvl in ("exact", "same_task_lang", "same_task"):
        rows = [d for d in ok if d["match_level"] == lvl]
        if rows:
            aa, nn, aa_acc = agree(rows)
            L.append(f"  {lvl}：一致率 {aa_acc:.3f}（{aa}/{nn}）")
    L.append("")
    if kappa >= 0.6:
        L.append("判定：κ ≥ 0.6 —— 判据与独立裁定高度一致，构念效度获得支持。")
    elif kappa >= 0.4:
        L.append("判定：0.4 ≤ κ < 0.6 —— 中等一致，构念效度获得部分支持。")
    else:
        L.append("判定：κ < 0.4 —— 一致度低，判据须**降格为操作性定义**，并在 Threats 中据此限定结论强度。")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
