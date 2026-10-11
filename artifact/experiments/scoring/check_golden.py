#!/usr/bin/env python3
"""**Golden 断言**：核对复算产物里的关键数字是否与论文/报告发布的一致。

`reproduce_s2.sh` 跑完全部分析后调用本脚本。任何一项不符即**退出码非零**——
复现入口因此不是一个"打印一堆东西"的脚本，而是一个**会失败的检查**。

覆盖：E0 矩阵的形状与两类计数、E1 六臂的崩塌率与区间（含组件直接对比）、
E2 的跨域数字与精确 Welch 区间、E3 的符合率与 κ。

用法：cd sqj && python3 swe/check_golden.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQJ = HERE.parent
RES = SQJ / "results"
KIT = SQJ / "oracle_audit_kit" / "results"

FAILS: list[str] = []
N = 0


def fold(x: str) -> str:
    """**删掉全部空白**再比对。

    产物里区间用 `{:6.2f}` 右对齐，负号位数不同会带出不同的前导空格
    （`[-11.61,` 与 `[ -9.46,`）。逐字或只折叠连续空白都会误报，
    直接去空白最稳——数字本身没有歧义。
    """
    return re.sub(r"\s+", "", x)


def has(hay: str, needle: str) -> bool:
    """折叠空白后判断包含（期望串与产物串用同一套折叠）。"""
    return fold(needle) in hay


def want(cond: bool, label: str, got: str = "") -> None:
    global N
    N += 1
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}" + (f"  （实际：{got}）" if got else ""))
        FAILS.append(label)


def text(p: Path) -> str:
    """读产物并把**连续空白折叠成一个空格**。

    产物里的区间用 `{:6.2f}` 右对齐，负号的位数不同会带出不同的前导空格
    （`-11.61` 不带、` -9.46` 带一个）。逐字比对会因此误报——折叠空白后再比。
    """
    if not p.exists():
        raise SystemExit(f"缺产物 {p}；请先跑 reproduce_s2.sh 的前置步骤")
    return re.sub(r"\s+", " ", p.read_text(encoding="utf-8"))


# ── E0 ──────────────────────────────────────────────────────────────────────
print("\nE0 · 预言机审计矩阵")
rows = list(csv.DictReader((KIT / "oracle_audit_matrix.csv").open(encoding="utf-8")))
targets = sorted({r["target"] for r in rows})
defects = sorted({r["defect"] for r in rows})
detectors = sorted({r["detector"] for r in rows})
want(len(rows) == 192, f"矩阵 192 行（3 目标 × 8 缺陷 × 8 检测器）", str(len(rows)))
want(len(targets) == 3, f"三个目标：{targets}", str(targets))
want(len(defects) == 8 and len(detectors) == 8, "8 类缺陷 × 8 个检测器")
for t in targets:
    as_ship = [r for r in rows if r["target"] == t and r["defect"].startswith("C0")]
    inj = [r for r in rows if r["target"] == t and not r["defect"].startswith("C0")]
    alarms0 = sum(1 for r in as_ship if r["violated"] == "1")
    caught = sorted({r["defect"] for r in inj if r["violated"] == "1"})
    want(alarms0 == 0, f"{t}：修复基线 0 项报警", f"{alarms0} 项")
    want(len(caught) == 7, f"{t}：7/7 注入类均有报警", f"{len(caught)} 类")

# ── E1 ──────────────────────────────────────────────────────────────────────
print("\nE1 · 组件消融（retail）")
e1 = text(RES / "e1_full_analysis.txt")
CH_RATE = {  # 臂 -> (崩塌率字符串, 计数)
    "en":   ("9.81%", "106/1080"),
    "zh_t": ("0.65%", "7/1080"),
    "zh_p": ("2.59%", "28/1080"),
    "zh_e": ("4.54%", "49/1080"),
    "zh":   ("1.76%", "19/1080"),
    "zhp":  ("1.30%", "14/1079"),
}
for arm, (rate, cnt) in CH_RATE.items():
    want(has(e1, rate) and has(e1, cnt), f"崩塌率 {arm} = {rate} ({cnt})")
# 注意：**逐个数字**断言，不要把「点估计 + 区间」当成连续串——
# 产物里两点之间夹着 `95%CI`、`SE=` 等字段，连续串匹配会假失败（踩过）。
DELTA = {  # 臂 -> (点估计, 下界, 上界)
    "zh_t": ("-9.17", "-11.61", "-6.73"),
    "zh_p": ("-7.22", "-9.46", "-4.98"),
    "zh_e": ("-5.28", "-8.03", "-2.52"),
    "zh":   ("-8.06", "-10.57", "-5.54"),
    "zhp":  ("-8.52", "-10.77", "-6.28"),
}
for arm, (d, lo, hi) in DELTA.items():
    want(has(e1, d) and has(e1, lo) and has(e1, hi),
         f"Δ vs en · {arm} = {d} pp [{lo}, {hi}]")
PAIRS = {  # 组件直接对比（第二轮外审要求的可检验形式）
    "zh_t - zh": ("-1.11", "-1.86", "-0.36"),
    "zh_e - zh": ("+2.78", "+1.21", "+4.34"),
    "zh_p - zh": ("+0.83", "-0.36", "+2.03"),
}
for label, (d, lo, hi) in PAIRS.items():
    want(has(e1, d) and has(e1, lo) and has(e1, hi),
         f"直接对比 {label} = {d} pp [{lo}, {hi}]")

# ── E2 ──────────────────────────────────────────────────────────────────────
print("\nE2 · 跨域（airline vs retail）")
e2 = text(RES / "e2_full_analysis.txt")
want(has(e2, "58/600") and has(e2, "9.67%"), "airline 用户 en 崩塌 58/600 = 9.67%")
want(has(e2, "26/600") and has(e2, "4.33%"), "airline 用户 zh 崩塌 26/600 = 4.33%")
want(has(e2, "-5.33") and has(e2, "-8.15") and has(e2, "-2.51"),
     "airline Δ(zh−en) = −5.33 pp [−8.15, −2.51]")
want(has(e2, "+6.67"), "retail Δ(zh−en) = +6.67 pp（与 v1.0 发表值一致）")
want(has(e2, "-12.00") and has(e2, "-16.33") and has(e2, "-7.67"),
     "跨域直接对比 = −12.00 pp [−16.33, −7.67]")
want(has(e2, "65.76"), "Welch 自由度 = 65.76（精确分位数，非分段近似）")

# ── E3 ──────────────────────────────────────────────────────────────────────
print("\nE3 · 遮蔽盲评")
e3 = text(RES / "e3_blind_adjudication.txt")
want(has(e3, "210") and has(e3, "212"), "有效裁定 210/212")
want(has(e3, "0.981") and has(e3, "0.962"), "一致率 0.981 / Cohen's κ 0.962")
want(has(e3, "流失率"), "流失率已报告")

# ── 汇总 ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
if FAILS:
    print(f"✗ golden 断言失败 {len(FAILS)}/{N} 项：")
    for f in FAILS:
        print("   · " + f)
    sys.exit(1)
print(f"✓ golden 断言全过（{N} 项）。复算产物与已发布数字一致。")
