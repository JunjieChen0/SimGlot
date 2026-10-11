#!/usr/bin/env python3
"""环境自查：跑复现之前先确认这台机器能跑。

检查三件事，任何一件不满足都**明确说出来**，而不是等脚本跑到一半才崩：

1. Python 版本（≥ 3.10；本项目脚本用了 `X | None` 这类标注语法）；
2. 计算所需的第三方包（numpy / scipy / pandas）；
3. **模型相关的环境状态**——本项目声称离线可复现，所以这里反过来查：
   若环境里存在密钥，明确提示。

第 3 条不是洁癖。论文的复现声明建立在「这一步不调用模型」之上；
若环境本身带密钥，一个疏忽就会让「离线复现」悄悄变成在线调用，而结果仍看似跑通。

用法：python3 artifact/scripts/verify_environment.py
退出码：0 = 满足；1 = 缺依赖；2 = Python 版本过低。
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys

MIN_PY = (3, 10)
REQUIRED = ["numpy", "scipy", "pandas"]
OPTIONAL = ["statsmodels", "matplotlib"]
KEY_VARS = ["DASHSCOPE_API_KEY", "DMXAPI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


def main() -> int:
    print(f"Python  {platform.python_version()}  ({sys.executable})")
    if sys.version_info < MIN_PY:
        print(f"x need Python >= {MIN_PY[0]}.{MIN_PY[1]}", file=sys.stderr)
        return 2
    print(f"platform {platform.system()} {platform.machine()}")

    missing = []
    print("\ndependencies:")
    for name in REQUIRED:
        have = importlib.util.find_spec(name) is not None
        print(f"  {'ok ' if have else 'XX '} {name}" + ("" if have else "   <- required"))
        if not have:
            missing.append(name)
    for name in OPTIONAL:
        have = importlib.util.find_spec(name) is not None
        print(f"  {'ok ' if have else '.. '} {name}" + ("" if have else "   (optional)"))

    print("\nmodel channels:")
    present = [v for v in KEY_VARS if os.environ.get(v)]
    if present:
        print(f"  !! environment carries {', '.join(present)}")
        print("     This entry point needs no key. Run the reproduction in an environment")
        print("     without keys, so that 'offline reproduction' cannot quietly become online.")
    else:
        print("  ok  no model keys - the precondition for offline reproduction holds")
    litellm = importlib.util.find_spec("litellm") is not None
    note = ("installed (will not be used; the suite forbids network access)"
            if litellm else "not installed")
    print(f"  ..  litellm {note}")

    if missing:
        print(f"\nx missing required packages: {', '.join(missing)}", file=sys.stderr)
        print("  install:  pip install " + " ".join(missing), file=sys.stderr)
        return 1

    print("\nok environment satisfies this repository's offline reproduction requirements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
