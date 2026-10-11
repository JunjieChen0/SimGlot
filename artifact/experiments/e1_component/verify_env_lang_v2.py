#!/usr/bin/env python3
"""E1 门禁：**逐组件**断言环境语言操纵做到了它声称的事（零模型调用）。

v1.0 的 `verify_env_lang.py` 有 47 项检查，但只覆盖三个整体档位（en / zh / zhp）。
E1 引入三个**单组件**档位（zh_p / zh_t / zh_e），必须有一个同样严格的门禁回答三个问题：

  1. **声称翻的翻了吗**——该组件在某档位应当用中文时，用的是 v1.0 的译文（逐字相同）；
  2. **声称不翻的没翻吗**——不该翻的组件必须**逐字节等于英文原对象**（不是"看起来像英文"）；
  3. **互不串味**——zh_p / zh_t / zh_e 三者两两之间**只在被操纵的那一维**上不同。

另加一项**跨运行器一致性**：`runner_v2` 在 `env_lang="en"` + `domain="retail"` 下交给智能体的
系统提示与工具说明，必须与 v1.0 `harness/episode.py` 的路径**逐字相同**——这是"v2 只是派生、
没有偷偷改变基线"的可检验形式。

用法：cd sqj && python3 swe/verify_env_lang_v2.py      # 退出码 0=全过，1=有失败
产出：sqj/results/verify_env_lang_v2.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQJ = HERE.parent
SIMGLOT = SQJ.parent / "simglot"
for _p in (str(SQJ), str(HERE), str(SIMGLOT), str(SIMGLOT / "vendor" / "tau-bench")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _bootstrap  # noqa: E402,F401  离线引导：必须在 tau_bench / harness 之前

import env_lang_v2 as EL2                       # noqa: E402
import harness.env_lang as V1                   # noqa: E402
from tau_bench.envs.retail.env import MockRetailDomainEnv  # noqa: E402

LINES: list[str] = []
FAILS: list[str] = []


def P(s: str = "") -> None:
    LINES.append(s)
    print(s)


def check(cond: bool, ok: str, bad: str) -> None:
    if cond:
        P(f"  ✓ {ok}")
    else:
        FAILS.append(bad)
        P(f"  ✗ {bad}")


def main() -> int:
    env = MockRetailDomainEnv(user_strategy="human", task_split="test", task_index=0)
    en_wiki = EL2.english_wiki()

    P("=" * 84)
    P("E1 门禁 · 组件级环境语言（env_lang_v2）")
    P("=" * 84)

    # ── 1. en 档：三个组件必须全部是英文原物 ────────────────────────────────
    P("\n── 1. en 档：三个组件都必须**逐字**为英文原物 ──")
    check(EL2.wiki("en") == en_wiki, "wiki(en) == τ-bench 原文", "wiki(en) 被改动")
    check(EL2.tools_info(env.tools_info, "en") is env.tools_info,
          "tools_info(en) 恒等返回原对象（同一引用）", "tools_info(en) 不是同一对象")
    check(EL2.observation("Error: user not found", "en") == "Error: user not found",
          "observation(en) 原样透传", "observation(en) 改动了文本")

    # ── 2. 每个档位的组件构成 ───────────────────────────────────────────────
    P("\n── 2. 逐档位：声称翻的翻了、声称不翻的没翻 ──")
    for lang, c in EL2.COMPONENTS.items():
        P(f"\n  [{lang}] {EL2.design(lang)}")
        w = EL2.wiki(lang)
        if c["policy"]:
            expect = V1.WIKI_ZH + (V1.WIKI_ZH_PAD if c["pad"] else "")
            check(w == expect, "wiki 用 v1.0 中文译文（逐字）", f"wiki({lang}) 与 v1.0 译文不符")
        else:
            check(w == en_wiki, "wiki 逐字等于英文原文", f"wiki({lang}) 不是英文原文")
        ti = EL2.tools_info(env.tools_info, lang)
        if c["tools"]:
            check(ti is not env.tools_info and ti[0]["function"]["description"] ==
                  V1.TOOL_DESC_ZH[env.tools_info[0]["function"]["name"]],
                  "tools_info 用 v1.0 中文译文", f"tools_info({lang}) 没换中文")
        else:
            check(ti is env.tools_info, "tools_info 恒等返回原对象",
                  f"tools_info({lang}) 不是同一对象")
        ob = EL2.observation("Error: user not found", lang)
        if c["errors"]:
            check(ob == V1.OBS_ZH["Error: user not found"], "错误串用 v1.0 中文译文",
                  f"observation({lang}) 没换中文")
        else:
            check(ob == "Error: user not found", "错误串原样透传",
                  f"observation({lang}) 改动了文本")

    # ── 3. 每个单组件臂相对**英文基线**只差一维 ───────────────────────────
    P("\n── 3. 每个单组件臂相对 en 基线：必须恰好只在一维上不同 ──")
    P("     （注意：单组件臂**两两之间**本就该在两维上不同——它们的对照组是 en，不是彼此。）")
    en_comp = EL2.COMPONENTS["en"]
    for s in ("zh_p", "zh_t", "zh_e"):
        diff = [k for k in ("policy", "tools", "errors")
                if EL2.COMPONENTS[s][k] != en_comp[k]]
        check(len(diff) == 1, f"{s} 相对 en 恰好在 1 个组件上不同（{diff}）",
              f"{s} 相对 en 在 {len(diff)} 个组件上不同：{diff}")
        check(not EL2.COMPONENTS[s]["pad"], f"{s} 不含长度配平附录（长度不是它操纵的维）",
              f"{s} 意外带了 padding")

    # ── 4. 指纹互异 ─────────────────────────────────────────────────────────
    P("\n── 4. 实现指纹必须两两不同（否则事后无法校验操纵确已生效） ──")
    fps = {l: EL2.fingerprint(l) for l in EL2.ENV_LANGS}
    check(len(set(fps.values())) == len(fps), "所有档位指纹互异",
          f"指纹碰撞：{ {k: v for k, v in fps.items()} }")

    # ── 5. 跨运行器一致性：v2 的 en/retail 必须与 v1.0 逐字相同 ───────────────
    P("\n── 5. 跨运行器一致性（v2 是派生，不得偷改基线） ──")
    v1_prompt = V1.wiki("en")
    v1_tools = V1.tools_info(env.tools_info, "en")
    v2_prompt = EL2.wiki("en")
    v2_tools = EL2.tools_info(env.tools_info, "en")
    check(v1_prompt == v2_prompt, "系统提示逐字相同", "v1 与 v2 的系统提示不同")
    check(json.dumps(v1_tools, sort_keys=True, ensure_ascii=False) ==
          json.dumps(v2_tools, sort_keys=True, ensure_ascii=False),
          "工具说明逐字相同", "v1 与 v2 的工具说明不同")

    # ── 6. 与 v1.0 的 zh / zhp 档位一致 ────────────────────────────────────
    P("\n── 6. 与 v1.0 既有档位的一致性（zh / zhp 必须原样复现） ──")
    for lang in ("zh", "zhp"):
        check(EL2.wiki(lang) == V1.wiki(lang), f"wiki('{lang}') 与 v1.0 相同",
              f"wiki('{lang}') 与 v1.0 不同")
        check(json.dumps(EL2.tools_info(env.tools_info, lang), sort_keys=True) ==
              json.dumps(V1.tools_info(env.tools_info, lang), sort_keys=True),
              f"tools_info('{lang}') 与 v1.0 相同", f"tools_info('{lang}') 与 v1.0 不同")
        check(EL2.observation("Error: user not found", lang) ==
              V1.observation("Error: user not found", lang),
              f"observation('{lang}') 与 v1.0 相同", f"observation('{lang}') 与 v1.0 不同")

    # ── 汇总 ────────────────────────────────────────────────────────────────
    P("")
    P("=" * 84)
    n = len(LINES)
    if FAILS:
        P(f"✗ 门禁未通过：{len(FAILS)} 项失败 —— 不得开跑 E1。")
        for f in FAILS:
            P(f"    · {f}")
    else:
        P("✓ 门禁全过（退出码 0）。")
    out = SQJ / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "verify_env_lang_v2.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    P(f"已写 {out/'verify_env_lang_v2.txt'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
