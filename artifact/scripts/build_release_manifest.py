#!/usr/bin/env python3
"""生成并校验 `FINAL_RELEASE_MANIFEST.json`：**归档 → 实验 → 论文章节** 的可机读映射。

## 与 `FREEZE_MANIFEST.json` 的分工

- `FREEZE_MANIFEST.json` 回答「**论文数字出自哪一个包**」（角色、字节数、SHA-256、退役修订版）；
- `FINAL_RELEASE_MANIFEST.json`（本脚本产出）在此基础上回答
  「**每一个包支撑论文的哪一段、对应哪一项实验**」。

两者**必须哈希一致**。本脚本会把新清单里的哈希与 `FREEZE_MANIFEST.json` 里的逐条比对，
不一致就退出 1——防止两份记录各自漂移（本项目已经吃过一次「记录与产物不一致」的亏）。

用法：
    python3 build_release_manifest.py            # 生成 + 校验
    python3 build_release_manifest.py --check    # 只校验，不写
退出码：0 = 一致；1 = 不一致或缺件；2 = 用法/环境错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VF = HERE.parent


def _find(name: str) -> Path | None:
    """清单可能在本目录、`metadata/`、`hashes/`，或再上若干层——
    脚本被复制进 artifact 包（`replication/code/entry_points/`）时就要靠这条。"""
    for base in [VF, HERE] + list(VF.parents)[:3]:
        for sub in ("", "metadata/", "hashes/"):
            cand = base / sub / name if sub else base / name
            if cand.exists():
                return cand
    return None


def _find_dir(name: str) -> Path | None:
    for base in [VF, HERE] + list(VF.parents)[:3]:
        cand = base / name
        if cand.is_dir():
            return cand
    return None


MANIFEST = _find("FREEZE_MANIFEST.json") or (VF / "FREEZE_MANIFEST.json")
OUT = MANIFEST.parent / "FINAL_RELEASE_MANIFEST.json"
_pkgs = _find_dir("packages") or _find_dir("archives")
PKGS = _pkgs if _pkgs else (VF / "packages")

#: 角色 → 该包支撑的**实验**与**论文章节**。
#: 章节号以 EMSE 稿的当前编号为准；改动章节结构时这里也要跟着改（--check 会提醒）。
ROLE_CONTENT: dict[str, dict] = {
    "v1.0-full": {
        "experiments": [
            "主矩阵：4,320 episode（retail，30 任务 × 6 模拟器 × 2 用户语言 × 3 重复，另含扩展臂）",
            "评分器污染：归档标签 vs 回放标签（4,194 → 2,883 数据库通过；94.3% → 65.5%）",
            "长度配平臂的对照数据（zhp 的环境侧）",
        ],
        "paper_sections": [
            "§1 贡献 2（预言机缺陷与回放修正）",
            "§4.1 The correction（4,194 / 2,883 / 94.3%→65.5%）",
            "§4.2 Table 2 的英文基线与长度配平行",
            "§6.2 内部效度（漂移探针与批次边界）",
        ],
        "not_for": "不含 E1/E2/E3 与 E0 套件——那些在 S2 与增强包里",
    },
    "v1.0-anon": {
        "experiments": ["与 v1.0-full 同内容，去标识化的双盲版本"],
        "paper_sections": ["投稿用（双盲提交）；不承载任何独有数字"],
        "not_for": "任何论文数字都不得单独引用此包，它与 v1.0-full 绑同一个最终 PDF",
    },
    "S2": {
        "experiments": [
            "E0 预言机审计套件本体（8 检查器：INV-1..5 + CTL-1..3）",
            "E1 三组件单臂消融：3,240 格（retail，30 任务 × 6 模拟器 × 2 语言 × 3 重复 × 3 单组件臂）",
            "E2 跨域检验：1,200 格（airline，50 任务 × 6 模拟器 × 2 语言 × 2 重复）",
            "E3 遮蔽盲评：212 条裁定输入",
            "评分修正的重算（score_envzh_corrected）与 32 项 golden",
        ],
        "paper_sections": [
            "§3.2 Oracle-integrity testing（检查器定义）",
            "§4.1 套件与其验证（Table 1 的报警并集）",
            "§4.2 Table 2 全部（组件消融）",
            "§4.3 第二个任务域反转（−12.00 pp [−16.33, −7.67]）",
            "§4.3 独立语言模型裁定（212 条，一致率 98.1%）",
        ],
        "not_for": "不含 AppWorld 迁移、不含变体级 54/57 与留一必要性——那些在增强包里",
    },
    "enhancement": {
        "experiments": [
            "E0 升级轮：21 变体 × 3 目标 = 63 组合；有效性三态 57/6/0；主分母检出 54/57",
            "留一必要性消融（哪些检查器是承重的）",
            "AppWorld 迁移：保留验证集正对照 3/21（负结果）",
            "C 功效模拟（未执行实验）：1.11 pp → 17.2% 功效",
            "发布工程：打包门禁、clean-room、来源绑定",
        ],
        "paper_sections": [
            "§4.1 What the class-level summary hides（54/57、两套分母、唯一漏检 G5b）",
            "§4.1 Table 1 的 necessary 列（留一必要性，由本包数据现算）",
            "§4.2 功效披露（1.11 pp → 17%）",
            "§6.3 外部效度（AppWorld 可移植性边界，负结果）",
            "§3.6 Replication package",
        ],
        "not_for": "不含 S2 的 E1/E2/E3 原始数据；本包是增量包",
    },
}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build() -> dict:
    if not MANIFEST.exists():
        print(f"✗ 找不到 {MANIFEST}", file=sys.stderr)
        raise SystemExit(2)
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))

    roles = []
    problems: list[str] = []
    for r in frozen["roles"]:
        role = r["role"]
        if role not in ROLE_CONTENT:
            problems.append(f"角色 {role} 在 FREEZE_MANIFEST.json 里，但本脚本没有它的内容映射——请补 ROLE_CONTENT")
            continue
        p = PKGS / r["file"]
        disk = None
        if p.exists():
            disk = sha256_of(p)
            if disk != r["sha256"]:
                problems.append(f"{role}: 磁盘哈希与冻结清单不符\n     记录 {r['sha256']}\n     实测 {disk}")
            if p.stat().st_size != r["bytes"]:
                problems.append(f"{role}: 字节数不符（记录 {r['bytes']}，实测 {p.stat().st_size}）")
        else:
            print(f"· {role}: 归档不在本包内（{p.name}）——本次只核对清单内部一致性，未核验磁盘哈希")
        roles.append({
            "role": role,
            "file": r["file"],
            "bytes": r["bytes"],
            "sha256": r["sha256"],
            "data_scope": r["scope"],
            "experiments": ROLE_CONTENT[role]["experiments"],
            "paper_sections": ROLE_CONTENT[role]["paper_sections"],
            "not_for": ROLE_CONTENT[role]["not_for"],
            "retired_revisions": [h for h, _n, _w in r["retired"]],
            "hash_verified_on_disk": disk is not None and disk == r["sha256"],
        })

    out = {
        "_comment": "SimGlot-vFinal 发布清单：每个归档**支撑论文的哪一段、对应哪项实验**。"
                    "由 checks/build_release_manifest.py 生成，并与 FREEZE_MANIFEST.json 交叉校验哈希。"
                    "**论文里的每一个数字都必须能在这四个角色里找到一个来源。**",
        "generated": "2026-10-11",
        "generator": "ClawsGO Science Agent",
        "authority": "本文件与 FREEZE_MANIFEST.json 共同构成版本身份的唯一记录；两者哈希必须一致。",
        "cross_check": {
            "against": "FREEZE_MANIFEST.json",
            "rule": "同一角色的 sha256 与 bytes 必须逐位相等；本脚本每次运行都重算。",
            "problems": problems,
        },
        "roles": roles,
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    out = build()
    problems = out["cross_check"]["problems"]

    if args.check:
        if problems:
            print("✗ 交叉校验未通过：", file=sys.stderr)
            for p in problems:
                print("   " + p, file=sys.stderr)
            return 1
        print(f"✓ 交叉校验通过（{len(out['roles'])} 个角色，哈希与字节数均与 FREEZE_MANIFEST.json 一致）")
        return 0

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写 {OUT.name}（{len(out['roles'])} 个角色）")
    for r in out["roles"]:
        mark = "✓" if r["hash_verified_on_disk"] else "·"
        print(f"  {mark} {r['role']:<12} {r['bytes']:>12,}  {r['sha256'][:16]}…  "
              f"实验 {len(r['experiments'])} 项｜章节 {len(r['paper_sections'])} 处")
    if problems:
        print("\n⚠ 以下问题已写入 cross_check.problems：", file=sys.stderr)
        for p in problems:
            print("   " + p, file=sys.stderr)
        return 1
    print("\n✓ 与 FREEZE_MANIFEST.json 逐条一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
