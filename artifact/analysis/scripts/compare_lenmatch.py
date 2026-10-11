#!/usr/bin/env python3
"""长度配平对照：三臂比较（环境 en / zh / zhp）。

环境语言这一维附带一个无法用措辞消除的混杂：中文政策文档与工具说明比英文短
7.6%。`zhp` 臂把中文系统提示补到英文的长度（标定偏差 -0.79%），于是：

    env=en  ：长提示 · 英文
    env=zh  ：短提示 · 中文
    env=zhp ：长提示 · 中文   ← 本实验

  · zhp ≈ zh 且都 ≪ en  → **环境语言**是主因，长度无关（语言效应被净化）
  · zhp ≈ en            → 效应来自**提示长度**，语言是伪因（必须这样报告）

逐格配对：同一 (任务, 模拟器, 用户语言, 种子) 下的三臂可比。所有区间都是
**任务聚类**自助法（重抽任务 5,000 次）。

用法：python3 scripts/compare_lenmatch.py
输出：results/compare_lenmatch.txt
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

import numpy as np
from scipy.stats import fisher_exact

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import _offline  # noqa: E402,F401  离线分析引导（含 vendor 入 sys.path 与客户端禁用桩）
from analyze_2x2 import load, parse, rate  # noqa: E402

AGENT = "qwen3.8-flash"
# 第 1 个标签提供 env=en 与 env=zh 的参照格；第 2 个只提供 env=zhp
TAGS = [("e2_main24", "en"), ("ez2_envzh", "zh"), ("ez2_lenmatch", "zhp")]
NBOOT = 5000

LINES: list[str] = []


def p(x: str = "") -> None:
    LINES.append(x)
    print(x)


def cell(cells: list[dict], user: str, env: str) -> list[dict]:
    return [r for r in cells if r["user"] == user and r["env"] == env]


def boot_diff(bytask: dict, statfn, nboot: int = NBOOT, seed: int = 20261008):
    """任务聚类自助法：返回 (观测值, lo, hi, 跨零?)。statfn(池化后的 episode 列表) -> float。

    **重复权重必须保留**：有放回重抽时同一任务可能被抽中多次，其 episode 也要按
    抽中次数重复计入。早期实现把重抽结果塞回以 task id 为键的字典，重复次数被字典
    吃掉（30 次抽取平均只剩约 19 个不同任务），区间因此失真（独立复核 P0）。
    现改为先展开成 episode 列表再交给 statfn。
    """
    tasks = sorted(bytask)
    obs = statfn([r for t in tasks for r in bytask[t]])
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(nboot):
        pick = [tasks[i] for i in rng.integers(0, len(tasks), len(tasks))]
        sub = [r for t in pick for r in bytask[t]]      # 重复任务按次数展开
        if sub:
            draws.append(statfn(sub))
    a = np.array(draws, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        return obs, float("nan"), float("nan"), True
    lo, hi = np.percentile(a, [2.5, 97.5])
    return obs, float(lo), float(hi), bool(lo <= 0 <= hi)


def main() -> int:
    cells: dict = {}
    have = {}
    for tag, env in TAGS:
        got = load(tag, AGENT)
        got = {k: v for k, v in got.items() if k[4] == env}
        have[env] = bool(got)
        for k, v in got.items():
            cells.setdefault(k, v)
    if not have.get("zhp"):
        p("尚无 env=zhp 的格，先跑 scripts/run_lenmatch.sh")
        return 1
    if not (have.get("en") and have.get("zh")):
        p("缺少 env=en 或 env=zh 的参照格")
        return 1

    # 只保留三臂齐全的配对点
    grp = collections.defaultdict(dict)
    for k, v in cells.items():
        grp[(k[0], k[1], k[2], k[3])][k[4]] = v
    rows = [v for d in grp.values() if {"en", "zh", "zhp"} <= set(d) for v in d.values()]
    if not rows:
        p("尚无三臂齐全的配对点")
        return 1
    n_triple = len(rows) // 3

    p("=" * 78)
    p("长度配平对照 · 环境 en / zh / zhp 三臂")
    p("=" * 78)
    p()
    p(f"  智能体 {AGENT}｜配对点 {n_triple} 个（每臂 {len(rows)} 格）"
      f"｜任务 {len({r['task'] for r in rows})} 个")
    p("  env=en 长提示·英文｜env=zh 短提示·中文｜env=zhp 长提示·中文（配平附录）")
    p()

    # ── 1. 提示长度核对 ────────────────────────────────────────────────────
    p("── 1. 提示长度核对（首轮 prompt token 中位）")
    p()
    p(f"  {'环境':<6}{'全部':>9}{'用户 en':>10}{'用户 zh':>10}")
    base = None
    for env in ("en", "zh", "zhp"):
        sub = [r for r in rows if r["env"] == env and r.get("first_tok")]
        allm = float(np.median([r["first_tok"] for r in sub])) if sub else float("nan")
        if env == "en":
            base = allm
        ev = [r["first_tok"] for r in sub if r["user"] == "en"]
        zv = [r["first_tok"] for r in sub if r["user"] == "zh"]
        e = float(np.median(ev)) if ev else float("nan")
        z = float(np.median(zv)) if zv else float("nan")
        p(f"  {env:<6}{allm:>9.0f}{e:>10.0f}{z:>10.0f}")
    def _m(env: str) -> float:
        v = [r["first_tok"] for r in rows if r["env"] == env and r.get("first_tok")]
        return float(np.median(v)) if v else float("nan")

    p(f"  相对 env en（首轮 prompt 中位）：" + "｜".join(
        f"{e} {100 * (_m(e) / base - 1):+.2f}%" for e in ("zh", "zhp")))
    p()

    # ── 2. 三臂结果表 ──────────────────────────────────────────────────────
    p("── 2. 三臂结果（崩塌率 / 通过率）")
    p()
    p(f"  {'用户':<6}{'env':<6}{'格数':>7}{'崩塌率':>9}{'通过率':>9}"
      f"{'DB-only':>9}{'每格报错':>10}")
    for user in ("en", "zh"):
        for env in ("en", "zh", "zhp"):
            sub = cell(rows, user, env)
            if not sub:
                continue
            db = [r for r in sub if r.get("r_actions") is not None]
            p(f"  {user:<6}{env:<6}{len(sub):>7}{100 * rate(sub, 'col'):>8.2f}%"
              f"{100 * rate(sub, 'reward'):>8.2f}%"
              f"{100 * rate(db, 'r_actions') if db else float('nan'):>8.2f}%"
              f"{np.mean([r['n_err'] for r in sub]):>10.2f}")
    p()

    # ── 3. 关键对比 ────────────────────────────────────────────────────────
    def diff_fn(env_a: str, env_b: str, user: str | None, key: str = "col"):
        def f(sub: list[dict]) -> float:
            a = [r for r in sub if r["env"] == env_a
                 and (user is None or r["user"] == user)]
            b = [r for r in sub if r["env"] == env_b
                 and (user is None or r["user"] == user)]
            if not a or not b:
                return float("nan")
            return 100 * (rate(a, key) - rate(b, key))
        return f

    bytask_all = collections.defaultdict(list)
    for r in rows:
        bytask_all[r["task"]].append(r)

    p("── 3. 两个关键对比（崩塌率之差，任务聚类 95%CI）")
    p()
    for label, ea, eb, note in (
        ("zhp − en", "zhp", "en", "长度相同、语言不同 → **净化后的语言效应**"),
        ("zhp − zh", "zhp", "zh", "语言相同、长度不同 → **净化的长度效应**"),
        ("zh − en", "zh", "en", "原始对比（语言与长度一起变）"),
    ):
        for user in ("en", "zh", None):
            obs, lo, hi, cross = boot_diff(bytask_all, diff_fn(ea, eb, user))
            tag = "全部" if user is None else f"用户 {user}"
            p(f"  {label:<10}{tag:<8}{obs:+7.2f} pp｜95%CI [{lo:+.2f}, {hi:+.2f}]"
              f"｜{'跨零' if cross else '不跨零'}")
        p(f"       （{note}）")
        p()

    # Fisher（格级，仅作参考；区间以上面的任务聚类为准）
    for label, ea, eb in (("zhp vs en", "zhp", "en"), ("zhp vs zh", "zhp", "zh")):
        a = [r for r in rows if r["env"] == ea]
        b = [r for r in rows if r["env"] == eb]
        ka, kb = sum(r["col"] for r in a), sum(r["col"] for r in b)
        _, pv = fisher_exact([[ka, len(a) - ka], [kb, len(b) - kb]])
        p(f"  格级 Fisher（仅参考）：{label:<10}p = {pv:.2e}"
          f"（{ka}/{len(a)} vs {kb}/{len(b)}）")
    p()

    # ── 3b. 同样三个对比，因变量换成**成功率** ─────────────────────────────
    # 论文摘要引用的「语言在等长下 +5.8 pp」出自这里（此前脚本只做了崩塌率，
    # 该数字是手算的，违反「一切数字由脚本复算」的规则）。
    p("── 3b. 同样三个对比（成功率之差，任务聚类 95%CI）")
    p()
    for label, ea, eb, note in (
        ("zhp − en", "zhp", "en", "长度相同、语言不同"),
        ("zhp − zh", "zhp", "zh", "语言相同、长度不同"),
        ("zh − en", "zh", "en", "语言与长度一起变"),
    ):
        for user in ("en", "zh", None):
            obs, lo, hi, cross = boot_diff(bytask_all, diff_fn(ea, eb, user, "reward"))
            tag = "全部" if user is None else f"用户 {user}"
            p(f"  {label:<10}{tag:<8}{obs:+7.2f} pp｜95%CI [{lo:+.2f}, {hi:+.2f}]"
              f"｜{'跨零' if cross else '不跨零'}")
        p(f"       （{note}）")
        p()

    # ── 4. 失败格的双向敏感性 ──────────────────────────────────────────────
    # `t27_qwen3.8-flash_u-deepseek-v4.1-flash_zh_s0_ezhp` 因 provider 侧
    # 「Repetitive tool calls detected」（HTTP 400）终止，agent_steps=0、无轨迹，
    # 因而在「计入失败」口径下计为 0 分。它属于 zhp 臂的中文用户格。
    # 本节同时报告两种处理：(a) 计入失败（默认，保守）；(b) 剔除该三元组
    # （连同 en / zh 两条配对臂），检验结论是否依赖这一格的归属。
    bad = {r["cell"] for r in rows if r.get("err")}
    p("── 4. 失败格的双向敏感性")
    p()
    if not bad:
        p("  本批无 provider 失败格。")
    else:
        for c in sorted(bad):
            p(f"  失败格：{c}")
        bad_keys = {(r["task"], r["sim"], r["user"], r["seed"]) for r in rows
                    if r.get("err")}
        keep = [r for r in rows
                if (r["task"], r["sim"], r["user"], r["seed"]) not in bad_keys]
        bt_k = collections.defaultdict(list)
        for r in keep:
            bt_k[r["task"]].append(r)
        p(f"  计入失败（默认）：zhp 臂 {len([r for r in rows if r['env'] == 'zhp'])} 格；"
          f"剔除该三元组后：zhp 臂 {len([r for r in keep if r['env'] == 'zhp'])} 格")
        p()
        p(f"  {'对比':<12}{'因变量':<8}{'计入失败':>28}{'剔除三元组':>28}")
        for label, ea, eb in (("zhp − en", "zhp", "en"), ("zhp − zh", "zhp", "zh")):
            for key, kname in (("col", "崩塌率"), ("reward", "成功率")):
                o1, l1, h1, c1 = boot_diff(bytask_all, diff_fn(ea, eb, None, key))
                o2, l2, h2, c2 = boot_diff(bt_k, diff_fn(ea, eb, None, key))
                p(f"  {label:<12}{kname:<8}"
                  f"{o1:+7.2f} [{l1:+.2f}, {h1:+.2f}]{'跨零' if c1 else '不跨零':>6}"
                  f"{o2:+8.2f} [{l2:+.2f}, {h2:+.2f}]{'跨零' if c2 else '不跨零':>6}")
        p()
        p("  读法：若两种处理的点估计与结论（是否跨零）一致，则该格不影响本节的任何主张。")
    p()

    p("── 5. 判读")
    p()
    p("  若 |zhp − en| 明显小于 |zh − en|（理想情形下 zhp − en 不跨零而 zh − en 跨零），")
    p("  则崩塌效应来自**提示长度**，环境语言是伪因——必须在论文中如实报告。")
    p("  若 zhp 与 zh 几乎重合、二者都远离 en，则**环境语言**是真因，长度被排除。")
    p("  中间情形按两个对比的量级分别报告，不作二选一的断言。")

    out = ROOT / "results" / "compare_lenmatch.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
