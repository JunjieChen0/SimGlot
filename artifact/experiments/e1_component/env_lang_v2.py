"""环境语言的**组件级**版本（E1 用）。在 `sqj/` 内派生，**不修改 v1.0**。

v1.0 的 `env_lang` 只有三个整体档位：`en` / `zh` / `zhp`（长度配平）。E1 要把 `zh` 拆成
三个**单组件**臂，看保护效应到底由哪一份文档承担：

| 档位 | 政策 wiki | 工具说明 | 错误串 | 说明 |
|---|:--:|:--:|:--:|---|
| `en` | 英 | 英 | 英 | v1.0 主矩阵的基线 |
| `zh` | 中 | 中 | 中 | v1.0 的全中文臂 |
| `zhp` | 中 | 中 | 中 | 全中文 + 长度配平附录 |
| **`zh_p`** | **中** | 英 | 英 | 仅政策 |
| **`zh_t`** | 英 | **中** | 英 | 仅工具说明 |
| **`zh_e`** | 英 | 英 | **中** | 仅错误串 |

**翻译表完全复用 v1.0 的 `harness/env_lang.py`**（只读导入 `WIKI_ZH`、`TOOL_DESC_ZH`、
`OBS_ZH` 及其翻译函数），因此不存在"第二套译文"这一新的效度风险。

**恒等保证**：不含某组件的档位，该组件**逐字返回英文原对象**；`en` 三个组件全为英文，
与 v1.0 的 `env_lang="en"` 完全同构（由 `verify_env_lang_v2.py` 逐组件断言）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

SIMGLOT = Path(__file__).resolve().parents[2] / "simglot"
for _p in (str(SIMGLOT), str(SIMGLOT / "vendor" / "tau-bench")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _bootstrap  # noqa: E402,F401  离线引导：必须在 tau_bench / harness 之前

import harness.env_lang as V1  # noqa: E402  只读复用 v1.0 的译文与翻译函数

#: 档位 → 哪几个组件用中文
COMPONENTS: Dict[str, Dict[str, bool]] = {
    "en":   dict(policy=False, tools=False, errors=False, pad=False),
    "zh":   dict(policy=True,  tools=True,  errors=True,  pad=False),
    "zhp":  dict(policy=True,  tools=True,  errors=True,  pad=True),
    "zh_p": dict(policy=True,  tools=False, errors=False, pad=False),
    "zh_t": dict(policy=False, tools=True,  errors=False, pad=False),
    "zh_e": dict(policy=False, tools=False, errors=True,  pad=False),
}

ENV_LANGS = tuple(COMPONENTS)


def _c(lang: str) -> Dict[str, bool]:
    if lang not in COMPONENTS:
        raise ValueError(f"未知环境语言档位：{lang!r}（只支持 {ENV_LANGS}）")
    return COMPONENTS[lang]


def english_wiki() -> str:
    from tau_bench.envs.retail.wiki import WIKI
    return WIKI


def wiki(lang: str) -> str:
    """智能体系统提示。不含 policy 组件的档位返回**英文原文**。"""
    c = _c(lang)
    if not c["policy"]:
        return english_wiki()
    text = V1.WIKI_ZH
    if c["pad"]:
        text = text + V1.WIKI_ZH_PAD
    return text


def tools_info(tools_info: List[Dict[str, Any]], lang: str) -> List[Dict[str, Any]]:
    """工具说明。不含 tools 组件的档位**恒等返回原对象**（与 v1.0 的 en 行为一致）。"""
    if not _c(lang)["tools"]:
        return tools_info
    return V1.tools_info(tools_info, "zh")


def observation(text: str, lang: str) -> str:
    """智能体看到的反馈串。不含 errors 组件的档位**原样返回**。"""
    if not _c(lang)["errors"]:
        return text
    return V1.observation(text, "zh")


def fingerprint(lang: str) -> str:
    """实现指纹：把三个组件的**实际取值**哈希进去，供事后校验操纵确已生效。

    与 v1.0 的 `fingerprint` 不同——后者按整体档位取值，无法区分单组件臂。
    """
    c = _c(lang)
    payload = {
        "components": c,
        "wiki": wiki(lang),
        "tool_desc": V1.TOOL_DESC_ZH if c["tools"] else {"__en__": "tau-bench 原文"},
        "param_desc": ({f"{k[0]}.{k[1]}": v for k, v in V1.TOOL_PARAM_DESC_ZH.items()}
                       if c["tools"] else {}),
        "obs": V1.OBS_ZH if c["errors"] else {"__en__": "原样透传"},
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def design(lang: str) -> str:
    """一行人类可读的操纵说明，写进 summary.json 便于事后审计。"""
    c = _c(lang)
    on = [k for k in ("policy", "tools", "errors") if c[k]]
    if not on:
        return "全英文基线（@1.0 的 env_lang=en）"
    label = {"policy": "政策wiki", "tools": "工具说明", "errors": "错误串"}
    s = " + ".join(label[k] for k in on) + " 用中文"
    if c["pad"]:
        s += "（另加长度配平附录）"
    return s
