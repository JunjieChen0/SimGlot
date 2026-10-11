#!/usr/bin/env python3
"""把唯一的对外发行版钉下来（第四、五轮复审的「关闭方法」）。

**默认针对 S2**，但 `--id` 可指向 `manifests/sources.json` 里的**任何**来源——
第五轮复审发现 v1.0 完整包也是同一类情形（它核到的是 `215d656f…`，
本工作区绑定的是 `2380993a…`）。

## 为什么需要这个脚本

第四轮复审指出：增强包绑定的 S2 是 `8e41d28e…`（70,518,492 B），
而复审手上可用于 B 组的那一份是 `24e8f4c0…`（69,174,713 B）——**两个修订版**。
这**不能**由本方单方面对齐：把 `sources.json` 改成手上这一份，
等于**替作者决定**哪一版是对外发布版，而且会让既有独立审计的背书发生错配。

所以本脚本只做一件事：**测量一个候选 S2 tarball，并明确告诉你它是不是已绑定的那一版**，
再给出「要绑的话该改哪里」。**它不替任何人写入**——改 `sources.json` 是作者的发布决定。

## 用法

```bash
python3 checks/pin_s2.py --candidate /path/to/simglot-s2-release-20261009.tar.gz
python3 checks/pin_s2.py --id simglot-v1.0-full --candidate /path/to/simglot-full-20261009.tar.gz
python3 checks/pin_s2.py --candidate <tarball> --explain   # 多打印绑定点与影响面
```

退出码：
  0 = 候选与已绑定的哈希一致（这一版就是对外发布版，无需改动）；
  2 = 候选是**另一个修订版**（打印双方哈希/字节数，并说明改哪里、影响什么）；
  1 = 候选文件不存在或读不动。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # sqj_enhancement_v1/
PROJECT = ROOT.parent                   # 项目根

DEFAULT_ID = "sqj-s2-release"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True, help="候选发布包（.tar.gz）")
    ap.add_argument("--id", default=DEFAULT_ID,
                    help=f"manifests/sources.json 里的来源 id（默认 {DEFAULT_ID}）")
    ap.add_argument("--explain", action="store_true", help="多打印绑定点与影响面")
    args = ap.parse_args()

    cand = Path(args.candidate).expanduser()
    if not cand.is_file():
        print(f"✗ 找不到候选：{cand}")
        return 1

    got, size = sha256_of(cand), cand.stat().st_size
    man = json.loads((ROOT / "manifests" / "sources.json").read_text(encoding="utf-8"))
    s2 = next((s for s in man["sources"] if s["id"] == args.id), None)
    if s2 is None:
        ids = ", ".join(x["id"] for x in man["sources"])
        print(f"✗ `manifests/sources.json` 里没有 `{args.id}` 条目；可选：{ids}")
        return 1

    want = s2.get("sha256")
    print("=" * 88)
    print(f"来源定版核对（id={args.id}）")
    print("=" * 88)
    print(f"  候选文件：{cand}")
    print(f"  实测    ：{got}")
    print(f"           {size:,} 字节")
    print(f"  已绑定  ：{want}")
    print(f"           {s2.get('bytes', '?')} 字节"
          + (f"（记录于 {s2['recorded_in']}）" if s2.get("recorded_in") else ""))
    print()

    if got == want:
        print("✓ 一致：**这一版就是已绑定的那一版**，不需要改动。")
        print("  提示：可能仍有另一修订版在流通（见 manifests/RELEASE_PROVENANCE.md），"
              "对外只需发布这一个哈希。")
        return 0

    print("✗ **不一致——这是另一个修订版**。")
    print("  本工作区绑定的不是这一个。**本方不替你改**：哪一版对外发布是作者的发布决定。")
    print("  （第五轮复审实测：S2 与 v1.0 完整包**两者**都是这种情形。）")
    print()
    print("  要把它定为对外发布版，需要改三处（改完必须重跑一次组装，因为包哈希会变）：")
    print(f"    ① `manifests/sources.json` 的 `{args.id}` 条目："
          f"`sha256` → {got[:16]}…、`bytes` → {size}")
    print("    ② `manifests/RELEASE_PROVENANCE.md` 的「本机所持副本」表要改成本行的实测值，"
          "并把「未对齐项」一段改成已对齐（写清旧版不再是对外发布版）")
    print("    ③ 重跑 `release/package_enhancement.sh`（门 ② 是 --require-all-verified，"
          "任一条非 VERIFIED 都会让组装失败）")
    print()
    print("  ⚠ 两条不得越界的话：")
    print("     · 不得把**旧版的独立审计背书**顺延到新版（哪怕只差重新打包）；")
    print("     · 不得对外写「全部来源哈希已核」——在 worktree 里它们才是 VERIFIED，")
    print("       在 clean-room 里外部来源是 SKIPPED_EXTERNAL（不是通过）。")
    if args.explain:
        print()
        print("  绑定点（`grep -rn` 可自行复核）：")
        print("    · manifests/sources.json")
        print("    · manifests/RELEASE_PROVENANCE.md")
        print("    · sqj/dist/RELEASE_20261009_checksums.txt（S2 包自己的记录，在 S2 侧）")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
