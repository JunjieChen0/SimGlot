#!/usr/bin/env python3
"""SimGlot vFinal 冻结校验：**每一个角色只有一个对外修订版**。

## 这个脚本要回答的那句话

审稿人一定会问：「**哪个版本产生了论文里的数字？**」
本脚本的答案是一条条可复算的：见 `FREEZE_MANIFEST.json` 的 `released` 字段，
以及每个角色下面的 `retired` 列表（**已退役、不得引用、不得分发**）。

## 用法

```bash
python3 checks/verify_freeze.py            # 校验（默认）
python3 checks/verify_freeze.py --write    # 用当前 packages/ 里的文件重建清单
python3 checks/verify_freeze.py --which <sha256 前缀>
                                           # 反查某个哈希属于哪个角色/哪一版
```

退出码：0 = 全部角色与清单一致；1 = 有缺失或哈希不符；2 = 参数错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VF = HERE.parent                              # simglot_vfinal/


def _default_manifest() -> Path:
    """清单可能在 `../FREEZE_MANIFEST.json`（原目录）、`../hashes/`（复现包副本），
    或再上若干层（脚本被复制到 `replication/code/entry_points/` 时）。"""
    bases = [VF, HERE] + list(VF.parents)[:3]
    for base in bases:
        for cand in (base / "FREEZE_MANIFEST.json", base / "metadata" / "FREEZE_MANIFEST.json",
                     base / "hashes" / "FREEZE_MANIFEST.json",
                     base / "FINAL_RELEASE_MANIFEST.json"):
            if cand.exists():
                return cand
    return VF / "FREEZE_MANIFEST.json"


def _default_packages() -> Path | None:
    """归档目录可能在 `packages/` 或 `archives/`，也可能**根本不在这棵树里**。

    小体积投稿包只带记录、不带那四个 tar.gz（它们有 220 MB+）。返回 None 表示
    「本包内没有归档」，由 main() 给出明确说法——**不能**静默当成通过。
    """
    for base in [VF, HERE] + list(VF.parents)[:3]:
        for name in ("packages", "archives"):
            cand = base / name
            if cand.is_dir():
                return cand
    return None


MANIFEST = _default_manifest()
PKGS = _default_packages()

#: 角色 → (规范文件名, 说明, 数据范围, 退役的修订版 [(sha256 或前缀, 字节或 None, 说明)])
ROLES: dict[str, dict] = {
    "v1.0-full": {
        "file": "simglot-v1.0-final.tar.gz",
        "title": "SimGlot v1.0 完整留档包",
        "scope": "主矩阵 4,320 格原始记录 + 49 页稿源与 PDF；论文的 v1.0 全部数字出自此包",
        "paper": "v1.0 稿（paper/main.tex 及其 49 页 PDF）",
        "retired": [
            ["215d656fecd00d675d10dfdf0676dc2e475c18d58ab4c16ffc82a600376e03f2", 81482739,
             "2026-10-08 的第九轮（D21）构建；dist/superseded/README.txt 已标注「已被取代，不要投稿或分发」。"
             "第五轮复审手上核到的正是这一个哈希——**那不是我方对外发布版**。"],
        ],
    },
    "v1.0-anon": {
        "file": "simglot-v1.0-anon-final.tar.gz",
        "title": "SimGlot v1.0 匿名投稿包",
        "scope": "与完整包同内容的双盲版本，绑同一个最终 PDF",
        "paper": "同上（双盲提交用）",
        "retired": [
            ["13a6ffd20f4d8db8a593dff716e87bb5e7c2bd72882b6250ee6c025872929832", 80721503,
             "2026-10-08 构建，已被取代"],
        ],
    },
    "S2": {
        "file": "simglot-S2-final.tar.gz",
        "title": "SimGlot S2 自包含发布包",
        "scope": "E0 预言机审计套件 + E1 三组件消融（3,240 格）+ E2 跨域（1,200 格）"
                 "+ E3 遮蔽盲评（212 条）；含 sqj/ 全树与 vendored τ-bench",
        "paper": "EMSE 稿的 RQ1（E0）与 RQ3（E1/E2/E3）",
        "retired": [
            ["24e8f4c0c60e46aa4bd14cc0b105df81a31d5b93f83c9a567ae68f90640447c3", 69174713,
             "**本机查无此文件**。第五轮复审手上可访问的是这一个；它不是我方记录的这一版。"
             "本方**不**把它设为发布版——那会让既有独立审计的背书错配。"
             "若作者确认它才是对外发布的那一版，需按 FREEZE.md §4 重新出具冻结记录。"],
        ],
    },
    "enhancement": {
        "file": "simglot-enhancement-final.tar.gz",
        "title": "SimGlot 增强轮包（增量）",
        "scope": "A（AppWorld 迁移，负结果）+ B（预留变体/消融/基线/开销）"
                 "+ C（共时三臂功效与预算，未执行）+ D（E3 证据闭合）+ §7 发布工程",
        "paper": "EMSE 稿的 RQ2 边界、RQ1 的跨实现泛化边界、复现包",
        "retired": [
            ["b03b7c80eeaffdcfcea5a78cc642c6f938ca2f8dfd227d1cc9d95c5680ce10a0", 117105,
             "第二轮修订版（已取代）"],
            ["ffcfaa09cf9c73209a5fcfe1396921e742de3c5e0d82d9d46b65dca518b1dbb5", 361825,
             "第三轮修订版（已取代）"],
            ["2a82a8956e0a83bf2c92a927249f0d8dae638e2079f0b13de1aa02cf181f78c7", 385292,
             "第四轮修订版（已取代）"],
            ["9e8ffd8fbd81c40c6291fdde290be3b86680d39bc0d9311aebced38f7110d604", 399979,
             "第五轮修订版（已取代；R5 复审手上是这一个）"],
            ["628f47be", 86801, "第一版增强包（仅记前缀）"],
        ],
    },
}

#: 已退役、**不属于任何角色**的存档（供反查时给出解释，不参与校验）
ARCHIVE_NOTE = {
    "f2901900d387b438af2dfe96591d984afb120ac7fcfeed44108156b191f78a0a":
        "S2 *full* 开发存档（42.7 MB），不是对外发布包",
    "ff497ba69105e87dc020979f51ccae3a168c4592762252558fe8f80b48173aa7":
        "S2 *code* 存档（289 KB），不是对外发布包",
}


def die2(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    raise SystemExit(2)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest() -> dict:
    out = {"_comment": "SimGlot vFinal 冻结清单：每个角色**只有一个**对外修订版。由 checks/verify_freeze.py 生成。",
           "generated": "2026-10-10", "generator": "ClawsGO Science Agent", "roles": []}
    for role, meta in ROLES.items():
        p = PKGS / meta["file"]
        if not p.exists():
            print(f"✗ 缺件：{p}")
            raise SystemExit(1)
        out["roles"].append({
            "role": role, "title": meta["title"], "file": meta["file"],
            "bytes": p.stat().st_size, "sha256": sha256_of(p),
            "scope": meta["scope"], "paper": meta["paper"],
            "retired": meta["retired"],
        })
    return out


def main() -> int:
    global MANIFEST, PKGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="用当前 packages/ 重建清单")
    ap.add_argument("--which", metavar="HASH", help="反查哈希属于哪个角色/哪一版")
    ap.add_argument("--manifest", metavar="PATH", help="冻结清单路径（默认自动查找）")
    ap.add_argument("--packages", metavar="DIR", help="存放四个 tar.gz 的目录（默认自动查找）")
    args = ap.parse_args()
    if args.manifest:
        MANIFEST = Path(args.manifest).resolve()
    if args.packages:
        PKGS = Path(args.packages).resolve()
    if not MANIFEST.exists():
        die2(f"找不到冻结清单：{MANIFEST}")
    if args.packages and not PKGS.is_dir():
        die2(f"不是目录：{PKGS}")
    # `--which` 只查清单，不需要归档在不在。
    # 没有归档时**不能**当成通过：打印记录的身份，然后以退出码 3 说明「本次没有核验」。
    if not args.which and (PKGS is None or not PKGS.is_dir()):
        print("=" * 92)
        print("归档未随本包分发 —— 本次**没有核验任何文件**")
        print("=" * 92)
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for r in man["roles"]:
            print(f"  {r['role']:<12}{r['bytes']:>12,}  {r['sha256']}  {r['file']}")
        print()
        print("上面是**记录的身份**，不是校验结果。拿到四个归档后这样核：")
        print(f"  python3 {Path(__file__).name} --packages <存放四个 tar.gz 的目录>")
        print("退回 3 = 无法核验（归档不在场）；1 = 核了但对不上。两者意义不同。")
        return 3

    if args.which:
        want = args.which.lower()
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        hit = False
        for r in man["roles"]:
            if r["sha256"].startswith(want):
                print(f"✓ {want}… = **对外发布版**：{r['role']}（{r['title']}）")
                print(f"   {r['bytes']:,} 字节｜{r['file']}")
                hit = True
            for h, n, why in r["retired"]:
                if h.startswith(want):
                    print(f"✗ {want}… = **已退役**，属角色 {r['role']}：{why}")
                    hit = True
        for h, why in ARCHIVE_NOTE.items():
            if h.startswith(want):
                print(f"· {want}… = {why}")
                hit = True
        if not hit:
            print(f"? {want}… 不在冻结清单里——它既不是任一角色的对外发布版，也不在退役表里。")
            return 2
        return 0

    if args.write:
        man = build_manifest()
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = ["# SimGlot vFinal 冻结清单（包外）",
                 "#",
                 "# 每个角色**只有一个**对外修订版；retired 里的哈希一律不得引用、不得分发。",
                 "# 复核：python3 simglot_vfinal/checks/verify_freeze.py",
                 ""]
        for r in man["roles"]:
            lines.append(f"{r['sha256']}  {r['bytes']:>10}  {r['file']}")
        (VF / "FREEZE_CHECKSUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"已写 {MANIFEST.name} 与 FREEZE_CHECKSUMS.txt（{len(man['roles'])} 个角色）")
        for r in man["roles"]:
            print(f"  {r['role']:<12}{r['bytes']:>10}  {r['sha256'][:16]}…  {r['file']}")
        return 0

    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print("=" * 92)
    print("SimGlot vFinal 冻结校验：每个角色只有一个对外修订版")
    print("=" * 92)
    bad = []
    for r in man["roles"]:
        p = PKGS / r["file"]
        if not p.exists():
            print(f"  ✗ {r['role']:<12}MISSING      {r['file']}")
            bad.append(r["role"]); continue
        got, size = sha256_of(p), p.stat().st_size
        if got == r["sha256"] and size == r["bytes"]:
            print(f"  ✓ {r['role']:<12}VERIFIED     {got[:16]}…  {size:,} 字节")
        else:
            print(f"  ✗ {r['role']:<12}MISMATCH     实测 {got[:16]}…/{size:,}"
                  f" vs 记录 {r['sha256'][:16]}…/{r['bytes']:,}")
            bad.append(r["role"])
    print()
    n_ret = sum(len(r["retired"]) for r in man["roles"])
    print(f"  {len(man['roles'])} 个角色已核｜另有 {n_ret} 个**已退役**修订版明确列出，"
          f"不得引用、不得分发。")
    if bad:
        print(f"\n✗ 冻结校验失败：{', '.join(bad)}")
        return 1
    print("\n✓ 冻结校验通过：论文数字对应的四个包都是上面这四个哈希。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
