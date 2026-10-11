#!/usr/bin/env python3
"""区间与 p 值共用的临界值（独立代码审计 P1-4）。

审计指出：任务聚类区间用正态 1.96，而聚类 p 值用 t(G−1)，两者**参照分布不一致**，
不能既用 1.96 的区间说「不跨零」、又用 t(29) 的 p 说「显著」。

集群数 G = 30，聚类稳健推断的标准做法是用 **t(G−1)** 临界值（Cameron–Gelbach–Miller）。
本模块提供一个常量，供所有出区间的脚本引用，使 CI 与 p 值落在同一参照分布上。

用法：from critval import CRIT
"""

from __future__ import annotations

CLUSTERS = 30                      # 任务数（重抽单位）
DF = CLUSTERS - 1                  # t 自由度 = 29

try:                               # 有 scipy 就精确算
    from scipy.stats import t as _t
    CRIT = float(_t.ppf(0.975, DF))            # ≈ 2.0452
except Exception:                              # 无 scipy 时的硬编码值
    CRIT = 2.0452

Z = 1.96                           # 仅用于非聚类的两比例区间

if __name__ == "__main__":
    print(f"G = {CLUSTERS}｜df = {DF}｜t(29) 0.975 分位 = {CRIT:.4f}｜正态 = {Z}")
