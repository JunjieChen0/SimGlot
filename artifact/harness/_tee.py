"""让脚本的标准输出与产物文件**同源**：stdout 就是产物，产物就是 stdout。

起因：第四轮独立代码复核发现 `leaderboard_bootstrap.py` 只打印、不落盘，于是
`results/leaderboard_bootstrap.txt` 停在 D17 修正之前的旧输出，与正文相差近一个
量级；第七轮复核又发现 `h4_interaction_test.py` 等脚本同样只打印。根因是
「脚本输出」与「归档产物」是两条可能分叉的路径。

约定：**所有**分析脚本的入口一律写成

    from _tee import run, RESULTS
    if __name__ == "__main__":
        raise SystemExit(run(RESULTS / "xxx.txt", main))

`run()` 捕获 `main()` 的全部标准输出，非零退出码时不落盘（失败不覆盖好产物），
再把同一份文本打到终端。产物文件因此永远等于「在本仓库现有数据上重跑该脚本」
的输出，独立复核者可用 `diff` 逐字节对账。
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def run(out_path: Path, fn) -> int:
    """执行 fn()，把它的 stdout 同时写到 out_path 与终端。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    text = buf.getvalue()
    if rc == 0:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if rc == 0:
        print(f"\n  已写 {out_path}")
    else:
        print(f"\n  ** 退出码 {rc}，产物未覆盖（避免用失败输出替换好产物）**")
    return rc
