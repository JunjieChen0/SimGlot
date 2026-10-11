#!/usr/bin/env python3
"""§7 · 顶层来源绑定核验：把 v1.0 / S2 / E3 子包 / 增强包按哈希钉住。

与「包内 MANIFEST.sha256」的分工：
  * 包内 MANIFEST 回答「**这一份里有哪些文件、有没有被动过**」；
  * 本脚本回答「**这一份是不是就是当初那一份**」——它比的是**包级哈希**，
    因此哈希必须写在包外（包内文件无法记录自身哈希）。

## 状态词表（第四轮复审 §4 之后补，2026-10-10）

上一版的问题是**用词**：自指条目在只解包、未组装时被印成 `✓ 未组装`，
还被算进「已核 2 项」——那**不能**读成「增强包自身的包级哈希已复核」。
现在每条**只允许**落进下面五个状态之一，且**只有 `VERIFIED` 才算核过**：

| 状态 | 含义 | 算「已验证」吗 |
|---|---|---|
| `VERIFIED` | 取到文件、算出哈希、**与记录值相等** | ✅ 是 |
| `MISMATCH` | 取到文件但哈希**不等** | ❌ 否（必然导致非零退出） |
| `SKIPPED_EXTERNAL` | 该外部来源**不在这棵树里**（增量包按设计不含它） | ❌ 否 |
| `NOT_ASSEMBLED` | 自指条目：包还没组装，或包外清单缺失/为空 | ❌ 否 |
| `PENDING` | `sources.json` 里显式标 `PENDING`（声明为尚未组装） | ❌ 否 |

**自指条目**（`sha256: "SELF"`）：包哈希只能记在包**外**，记在包内会每次改包就失效
（自指闭环，实测会把组装门禁卡死）。因此它核的是：
「磁盘上的 `release/*.tar.gz` == 包外 `release/ENHANCEMENT_checksums.txt` 里记的值」。
**缺席时记 `NOT_ASSEMBLED`，绝不印勾、绝不计入已验证。**

## 用法

```bash
python3 verify_sources.py                        # 严格：缺件即失败
python3 verify_sources.py --available-only       # clean-room：外部缺席记 SKIPPED_EXTERNAL
python3 verify_sources.py --require-all-verified # 发布验收：任一条非 VERIFIED 即失败
python3 verify_sources.py --write-status out.txt # 另存逐条状态（发布记录用）
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT = ROOT.parent

#: `sha256` 取此值时表示「自指」——真值记在包外的 `ENHANCEMENT_checksums.txt`
SELF = "SELF"

VERIFIED = "VERIFIED"
MISMATCH = "MISMATCH"
SKIPPED_EXTERNAL = "SKIPPED_EXTERNAL"
NOT_ASSEMBLED = "NOT_ASSEMBLED"
PENDING = "PENDING"
MISSING = "MISSING"

#: 只有这个状态算「核过」
OK_STATUS = {VERIFIED}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_in_package(root: Path, project: Path, rel: str) -> Path | None:
    """把 `in_package` 解析成实际存在的路径。

    `sources.json` 里记的是**工作区相对**路径（`sqj_enhancement_v1/evidence/...`），
    但解包后的顶层目录叫 `simglot-enhancement-20261010`——直接拼就对不上。
    因此几种候选都试，取第一个存在的（clean-room 实测踩过）。
    """
    parts = Path(rel).parts
    cands = [project / rel, root / rel]
    if parts and parts[0] == root.name:
        cands.append(root.joinpath(*parts[1:]))
    if len(parts) > 1:
        cands.append(root.joinpath(*parts[1:]))
    for c in cands:
        if c.exists():
            return c
    return None


def _check_self(pkg: Path, got: str | None) -> tuple[str, str]:
    """自指条目：拿磁盘上的包去比**包外**清单里记的值。"""
    if got is None:
        return NOT_ASSEMBLED, "包不在本目录（只解包、未组装）——**不计为已验证**"
    rec = ROOT / "release" / "ENHANCEMENT_checksums.txt"
    if not rec.exists():
        return NOT_ASSEMBLED, "包在、但缺包外清单——自指条目的真值必须在包外"
    m = re.search(r"`([0-9a-f]{64})`", rec.read_text(encoding="utf-8"))
    if not m:
        return NOT_ASSEMBLED, "包外清单里找不到 64 位十六进制哈希"
    want = m.group(1)
    if want == got:
        return VERIFIED, f"{got[:16]}…（与包外清单一致）"
    return MISMATCH, f"与包外清单不一致：磁盘 {got[:16]}… vs 清单 {want[:16]}…"


def evaluate(available_only: bool) -> tuple[list[dict], Path]:
    man_path = ROOT / "manifests" / "sources.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for s in man["sources"]:
        p = PROJECT / s["path"]
        local = _resolve_in_package(ROOT, PROJECT, s["in_package"]) if s.get("in_package") else None
        used = p
        if local is not None and not p.exists():
            used = local
        e = {"id": s["id"], "path": str(s["path"]), "used": str(used),
             "in_package": s.get("in_package")}
        if s.get("sha256") == SELF:
            got = sha256_of(used) if used.exists() else None
            e["status"], e["detail"] = _check_self(used, got)
            e["recorded"] = "SELF（见包外清单）"
            e["actual"] = got
            out.append(e)
            continue
        e["recorded"] = s.get("sha256")
        if s.get("sha256") == "PENDING":
            e["status"] = PENDING
            e["detail"] = "sources.json 里标为 PENDING"
            e["actual"] = sha256_of(used) if used.exists() else None
            out.append(e)
            continue
        if not used.exists():
            e["status"] = SKIPPED_EXTERNAL if available_only else MISSING
            e["detail"] = ("外部来源不在本目录（增量包按设计不含它）" if available_only
                           else f"文件不存在：{used}")
            e["actual"] = None
            out.append(e)
            continue
        got = sha256_of(used)
        e["actual"] = got
        if got == s.get("sha256"):
            e["status"] = VERIFIED
            e["detail"] = got[:16] + "…" + ("（包内副本）" if used == local else "")
        else:
            e["status"] = MISMATCH
            e["detail"] = f"记录 {str(s.get('sha256'))[:16]}… vs 实测 {got[:16]}…"
        out.append(e)
    return out, man_path


def render(rows: list[dict], available_only: bool) -> str:
    lines = ["=" * 88,
             "顶层来源绑定核验" + ("（--available-only：外部缺席记 SKIPPED_EXTERNAL）"
                                   if available_only else "（严格：缺件即失败）"),
             "=" * 88]
    mark = {VERIFIED: "✓", MISMATCH: "✗", MISSING: "✗",
            SKIPPED_EXTERNAL: "·", NOT_ASSEMBLED: "·", PENDING: "·"}
    for e in rows:
        lines.append(f"  {mark[e['status']]} {e['id']:<26}{e['status']:<17}{e['detail']}")
    n = {k: sum(1 for e in rows if e["status"] == k)
         for k in (VERIFIED, SKIPPED_EXTERNAL, NOT_ASSEMBLED, PENDING, MISMATCH, MISSING)}
    lines.append("")
    lines.append(f"  状态统计：VERIFIED {n[VERIFIED]}｜SKIPPED_EXTERNAL {n[SKIPPED_EXTERNAL]}｜"
                 f"NOT_ASSEMBLED {n[NOT_ASSEMBLED]}｜PENDING {n[PENDING]}｜"
                 f"MISMATCH {n[MISMATCH]}｜MISSING {n[MISSING]}")
    lines.append(f"  **只有 VERIFIED 算核过** ⇒ 本次已核 {n[VERIFIED]}/{len(rows)} 条。")
    if n[SKIPPED_EXTERNAL] or n[NOT_ASSEMBLED]:
        lines.append("  · 跳过/未组装**不等于通过**：这些来源的包级哈希本次**没有**被核对。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="顶层来源绑定核验。只有 VERIFIED 算核过。")
    ap.add_argument("--available-only", action="store_true",
                    help="clean-room 用：外部来源不在本目录时记 SKIPPED_EXTERNAL 而非失败")
    ap.add_argument("--require-all-verified", action="store_true",
                    help="发布验收用：任一条不是 VERIFIED 即非零退出")
    ap.add_argument("--write-status", metavar="PATH", help="把逐条状态另存（发布记录用）")
    args = ap.parse_args()

    rows, man_path = evaluate(args.available_only)
    text = render(rows, args.available_only)
    print(text)

    if args.write_status:
        out = Path(args.write_status)
        out.write_text(
            "\n".join([
                "# 顶层来源绑定 · 逐条状态（由 checks/verify_sources.py --write-status 生成）",
                f"# 来源清单：{man_path}",
                "# 状态词表：VERIFIED（已核）／MISMATCH（不符）／SKIPPED_EXTERNAL（外部不在本树）",
                "#           ／NOT_ASSEMBLED（自指条目未组装）／PENDING／MISSING",
                "# **只有 VERIFIED 算核过。**",
                "",
            ] + [f"{e['status']:<17}{e['id']:<26}{e['detail']}" for e in rows]) + "\n",
            encoding="utf-8")
        print(f"\n逐条状态已写 {out}")

    bad = [e for e in rows if e["status"] in (MISMATCH, MISSING)]
    if bad:
        print("\n✗ 来源绑定核验失败：")
        for e in bad:
            print(f"    · {e['id']}：{e['detail']}")
        return 1
    if args.require_all_verified:
        notv = [e for e in rows if e["status"] not in OK_STATUS]
        if notv:
            print("\n✗ --require-all-verified：以下条目不是 VERIFIED：")
            for e in notv:
                print(f"    · {e['id']}：{e['status']}（{e['detail']}）")
            return 1
        print("\n✓ --require-all-verified：全部条目均已逐条核过包级哈希。")
        return 0
    if not args.available_only:
        na = [e for e in rows if e["status"] == NOT_ASSEMBLED]
        if na:
            print("\n✗ 严格模式下自指条目未组装（增强包不在本目录 / 包外清单缺失）：")
            for e in na:
                print(f"    · {e['id']}：{e['detail']}")
            return 1
    print(f"\n✓ 核验流程通过（已核 {sum(1 for e in rows if e['status'] == VERIFIED)}/{len(rows)} 条"
          f"{'；其余为跳过/未组装，**不是**通过' if len(rows) > sum(1 for e in rows if e['status'] == VERIFIED) else ''}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
