#!/usr/bin/env python3
"""工作包 D · 生成 E3 证据包的清单（并复算校验）。

## 第二轮外部复审（2026-10-10）之后的变化

复审指出：上册增强包**不含**它自己 manifest 里点名的 212 条
`adjudication_inputs.jsonl`（只指向同级 `sqj/results/`），而复审手上那份 S2 包里也没有，
于是**无法核验**那份重构输入的哈希与逐条内容。

**处置**：这四个件体积都不大（合计约 1.16 MB），现在**随包交付**——
落在本目录（`evidence/e3_inputs/`），清单同时记**包内副本**与**原始路径**两套哈希，
且要求两者相等。此外新增一条**逐条对齐核验**：
`adjudication_inputs.jsonl` 与 `verdicts.csv` 必须在
`uid` 集合、`cell_id`、`task_id`、`match_level` 上逐条对齐——
这正是复审说「没有核验」的那一件事，现在可核验了。

只写清单与哈希，**不复制**大文件；`sqj/` 是已发布的只读包，它的自身哈希已经固定。

用法：python3 build_manifest.py [--check]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                       # sqj_enhancement_v1/
PROJECT = ROOT.parent
SQJ = PROJECT / "sqj"

#: (id, 原始路径, 包内副本名, 说明, 来源性质)
ARTIFACTS = [
    ("adjudication_inputs", SQJ / "results" / "e3_adjudication_inputs.jsonl",
     "adjudication_inputs.jsonl",
     "212 条送进裁定者的渲染文本（用户轮已替换为 [user turn]）", "reconstructed"),
    ("verdicts", SQJ / "runs" / "e3_blind" / "verdicts.csv", "verdicts.csv",
     "逐条裁定：机械标签、裁定标签、匹配层级、token、裁定者原始回复", "captured"),
    ("judge_calls", SQJ / "runs" / "e3_blind" / "judge_calls.jsonl", "judge_calls.jsonl",
     "逐次调用元数据：时间戳、模型、latency、token、重试（**无 prompt 字段**）", "captured"),
    ("adjudication_code", SQJ / "swe" / "e3_blind_adjudication.py", "e3_blind_adjudication.py",
     "固定判据与抽样口径所在的脚本（RUBRIC / SEED / MAX_TOKENS）", "captured"),
]

#: 逐条对齐要核验的字段：jsonl 键名 → verdicts.csv 列名
ALIGN_FIELDS = [("uid", "uid"), ("cell_id", "cell_id"), ("task_id", "task_id"),
                ("match_level", "match_level")]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def verify_alignment() -> tuple[bool, str]:
    """逐条核验重构输入与当场捕获的裁定表是否对齐（复审要求的那件事）。"""
    jp, vp = HERE / "adjudication_inputs.jsonl", HERE / "verdicts.csv"
    if not jp.exists() or not vp.exists():
        return False, "缺件：包内没有 adjudication_inputs.jsonl 或 verdicts.csv"
    inputs = [json.loads(ln) for ln in jp.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = list(csv.DictReader(vp.open(encoding="utf-8")))
    if len(inputs) != len(rows):
        return False, f"条数不等：输入 {len(inputs)} vs 裁定 {len(rows)}"
    by_uid = {r["uid"]: r for r in rows}
    if set(by_uid) != {r["uid"] for r in inputs}:
        miss = sorted({r["uid"] for r in inputs} - set(by_uid))[:4]
        return False, f"uid 集合不一致；输入里多出的样例 {miss}"
    bad = []
    for rec in inputs:
        row = by_uid[rec["uid"]]
        for jk, ck in ALIGN_FIELDS:
            if str(rec.get(jk)) != str(row.get(ck)):
                bad.append(f"{rec['uid']}.{jk}: {rec.get(jk)!r} vs {row.get(ck)!r}")
    if bad:
        return False, f"{len(bad)} 处字段不一致，样例：{bad[:3]}"
    fields = "、".join(jk for jk, _ in ALIGN_FIELDS)
    return True, f"{len(inputs)} 条逐条对齐（{fields}）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只复算比对既有清单")
    args = ap.parse_args()
    man_path = HERE / "manifest.json"

    entries, problems = [], []
    for eid, orig, local, desc, status in ARTIFACTS:
        lp = HERE / local
        if not lp.exists():
            problems.append(f"{eid}：包内副本缺失（{lp.name}）——复审要求的正是这一件")
            continue
        e = {"id": eid, "path": str(orig.relative_to(PROJECT)),
             "in_package": str(lp.relative_to(ROOT)),
             "bytes": lp.stat().st_size,
             "sha256": sha256(lp), "description": desc, "provenance": status}
        if orig.exists():
            e["source_sha256"] = sha256(orig)
            if e["source_sha256"] != e["sha256"]:
                problems.append(f"{eid}：包内副本与原始路径的哈希不一致")
        else:
            e["source_sha256"] = None
            e["_note"] = "原始路径在本机不可见；以包内副本为准"
        entries.append(e)

    ok, msg = verify_alignment()
    if not ok:
        problems.append(f"逐条对齐核验失败：{msg}")

    counts = _counts()
    manifest = {
        "_comment": ("E3 证据包清单。四个件**随包交付**（`in_package` 给出包内路径），"
                     "同时记原始路径哈希；两者必须相等。"),
        "generated": "2026-10-10",
        "generator": "ClawsGO Science Agent",
        "fixed_elements": {
            "judge_model": "glm-5.3",
            "channel": "token_plan（百炼）",
            "seed": 20261009,
            "max_tokens": 6000,
            "rubric": "e3_blind_adjudication.py 的 RUBRIC 常量（先写死、后执行）",
            "order": "random.Random(SEED).shuffle(items)",
            "design": "全量普查 106 崩塌 + 106 匹配对照（匹配层级见每条记录）",
        },
        "alignment_check": {"ok": ok, "detail": msg},
        "counts": counts,
        "artifacts": entries,
        "not_included": [
            "裁定者当时收到的原始请求字节（prompt 原文）——未单独落盘",
            "v1.0 的 runs/e2_main24/（271 MB 主轨迹）——按容量排除，见 sqj/V1_DEPENDENCY.md",
        ],
    }

    if args.check:
        if not man_path.exists():
            print("✗ 无既有清单可比对")
            return 1
        old = json.loads(man_path.read_text(encoding="utf-8"))
        om = {e["id"]: e["sha256"] for e in old["artifacts"]}
        bad = [e["id"] for e in entries if om.get(e["id"]) != e["sha256"]]
        if bad:
            print(f"✗ 以下条目与清单不符：{bad}")
            return 1
        print(f"✓ 清单复算一致（{len(entries)} 项）｜逐条对齐：{msg}")
        return 0 if not problems else 1

    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    (HERE / "MANIFEST.sha256").write_text(
        "".join(f"{e['sha256']}  {e['in_package']}\n" for e in entries), encoding="utf-8")
    print(f"已写 {man_path} 与 MANIFEST.sha256（{len(entries)} 项）")
    for e in entries:
        print(f"  {e['id']:<22}{e['provenance']:<15}{e['sha256'][:16]}…  {e['in_package']}")
    print(f"逐条对齐核验：{'✓' if ok else '✗'} {msg}")
    print(f"计数：{json.dumps(counts, ensure_ascii=False)}")
    if problems:
        print("✗ 有问题：")
        for p in problems:
            print(f"    · {p}")
        return 1
    return 0


def _counts() -> dict:
    vp = HERE / "verdicts.csv"
    rows = list(csv.DictReader(vp.open(encoding="utf-8"))) if vp.exists() else []
    ok = [r for r in rows if str(r.get("ok", "")).lower() == "true"]
    dis = [r for r in ok
           if bool(int(r["truth_collapse"])) != (str(r["judge_stalled"]).lower() == "true")]
    per_lang = {}
    for lang in sorted({r["user_lang"] for r in ok}):
        sub = [r for r in ok if r["user_lang"] == lang]
        agree = sum(1 for r in sub
                    if bool(int(r["truth_collapse"])) == (str(r["judge_stalled"]).lower() == "true"))
        per_lang[lang] = {"n": len(sub), "agree": agree}
    return {"records": len(rows), "valid": len(ok), "unparsed": len(rows) - len(ok),
            "agree": len(ok) - len(dis), "disagreements": len(dis),
            "per_language": per_lang}


if __name__ == "__main__":
    raise SystemExit(main())
