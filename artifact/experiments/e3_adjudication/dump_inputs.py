#!/usr/bin/env python3
"""导出 E3 盲评的 **212 条实际裁定输入**，随发布包一同分发。

**为什么需要**：独立复审指出——S2 包里保留了 `runs/e3_blind/verdicts.csv`，
但**裁定输入本身不在包内**，而这些输入是从 v1.0 的 `runs/e2_main24/` 现场渲染的，
而该目录**按容量被排除在发布包之外**。结果：**单凭发布包无法独立重建 E3 的裁定输入**，
只能重建到 `verdicts.csv` 为止。（可重建性缺口，属实。）

**本脚本做什么**：把当时送给裁定者的**原文**逐条导出（uid、cell_id、语言臂、机械标签、
匹配层级、渲染文本），使裁定可被独立复核——包括"某条到底是不是崩塌"这类判断。

**去标识说明**：渲染文本里**用户轮已被替换为 `[user turn]`**（E3 的设计如此）；
其余内容为 τ-bench **合成**客户记录（人名/地址/订单号皆为基准自带虚构数据，非真人信息）
与模型的回复。本文件不含任何密钥、真实个人信息或通道凭据。

用法：cd sqj && python3 swe/dump_e3_inputs.py [--out results/e3_adjudication_inputs.jsonl]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import _bootstrap  # noqa: E402,F401  离线引导（本脚本其实不需要模型，但保持一致的导入纪律）

from e3_blind_adjudication import build_items, load_rows, match_controls  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(_HERE.parent / "results" /
                                         "e3_adjudication_inputs.jsonl"))
    args = ap.parse_args()

    rows = load_rows()
    pairs = match_controls(rows)
    items = build_items(pairs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps({
                "uid": it["uid"],
                "cell_id": it["cell_id"],
                "task_id": it["task_id"],
                "simulator": it["sim"],
                "user_language": it["user_lang"],
                "mechanical_collapse_label": it["truth_collapse"],
                "match_level": it["match_level"],
                # 送进裁定者的原文（用户轮已替换为 [user turn]；不含任何臂标签或判据中间量）
                "adjudication_input": it["render"],
            }, ensure_ascii=False) + "\n")
    n = len(items)
    size = out.stat().st_size
    print(f"已写 {n} 条裁定输入 → {out}（{size:,} 字节 ≈ {size/1024:.0f} KB）")
    print(f"  阳性（机械判据=崩塌）{sum(1 for i in items if i['truth_collapse']==1)} 条"
          f"｜对照 {sum(1 for i in items if i['truth_collapse']==0)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
