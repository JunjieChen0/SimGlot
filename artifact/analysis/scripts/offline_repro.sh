#!/usr/bin/env bash
# 一条命令、**无模型客户端、无密钥、无网络**，重建论文的主汇总表 / H4 / Collapse /
# 长度配平表，并在最后核对产物与脚本一致、正文引用与重算一致。
#
# 用法（在 simglot/ 下）：
#   bash scripts/offline_repro.sh                  # 正常离线复现
#   bash scripts/offline_repro.sh --strict-offline # 即使装了 litellm/openai 也强制用禁用桩，
#                                                  # 用来验证「纯离线路径」本身不依赖模型客户端
#   bash scripts/offline_repro.sh --fast           # 跳过 frozen_table.py（已有 CSV 时）
#
# 依赖：python3 + numpy/scipy/statsmodels/pandas/matplotlib（见 requirements-analysis.txt）。
# 全程只读 runs/ 与 results/，不新增、不修改任何 episode，不发任何网络请求。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STRICT=0
FAST=0
for a in "$@"; do
  case "$a" in
    --strict-offline) STRICT=1 ;;
    --fast) FAST=1 ;;
    *) echo "未知参数：$a"; exit 2 ;;
  esac
done

if [ "$STRICT" = "1" ]; then
  export SIMGLOT_OFFLINE_STUB=1
  echo "==> 严格离线模式：模型客户端一律走禁用桩（SIMGLOT_OFFLINE_STUB=1）"
fi

# 离线路径不应该出现任何通道密钥；出现即为配置错误，立刻停下。
for v in DASHSCOPE_API_KEY DMXAPI_API_KEY OPENAI_API_KEY; do
  if [ -n "${!v:-}" ]; then
    echo "** 离线复现检测到 $v 已设置；本脚本不读密钥，请用干净环境运行。**"
    exit 1
  fi
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "0/12 环境自检"
python3 - <<'PY'
import sys
sys.path.insert(0, "scripts"); sys.path.insert(0, ".")
import _offline
from _offline import assert_no_credentials
assert_no_credentials()
import numpy, scipy, statsmodels, pandas, matplotlib  # noqa: F401
print(f"  Python {sys.version.split()[0]}｜numpy {numpy.__version__}｜scipy {scipy.__version__}"
      f"｜statsmodels {statsmodels.__version__}｜pandas {pandas.__version__}")
print("  分析依赖齐备；未读取任何通道密钥。")
PY

step "1/12 重建唯一冻结分析表（4,320 行；重放数据库终态，纯 CPU）"
if [ "$FAST" = "1" ] && [ -f results/frozen_table.csv ]; then
  echo "  --fast：跳过（沿用现有 results/frozen_table.csv）"
else
  python3 scripts/frozen_table.py > /dev/null
  echo "  -> results/frozen_table.csv（$(wc -l < results/frozen_table.csv) 行含表头）"
fi

step "2/12 主汇总表 + 整数计数总账"
python3 scripts/audit_counts.py > /dev/null
python3 scripts/table_significance.py > /dev/null
python3 scripts/cluster_pvalues.py > /dev/null
echo "  -> count_audit.txt / significance_table.txt / cluster_pvalues.txt"

step "3/12 两种退化模式（预注册崩塌 + 重复工具调用）"
python3 scripts/degeneration_modes.py > /dev/null
python3 scripts/collapse_post_recovery.py > /dev/null
python3 scripts/collapse_construct_validity.py > /dev/null
python3 scripts/stop_reason_split.py > /dev/null
python3 scripts/twostate_denominators.py > /dev/null
echo "  -> degeneration_modes.txt / collapse_post_recovery.txt / collapse_validity.txt"
echo "     stop_reason_split.txt / twostate_denominators.txt"

step "4/12 H4 交互（Wald + wild cluster bootstrap，含零假设中心化变体）"
python3 scripts/h4_interaction_test.py > /dev/null
python3 scripts/h4_statistic_sensitivity.py > /dev/null
echo "  -> h4_interaction.txt / h4_statistic_sensitivity.txt"

step "5/12 长度配平臂对照（三臂：en / zh / zhp）"
python3 scripts/compare_lenmatch.py > /dev/null
python3 scripts/analyze_2x2.py > /dev/null
echo "  -> compare_lenmatch.txt / analyze_2x2.txt"

step "6/12 排行榜（动态前两名 vs 固定配对的有符号差）"
python3 scripts/leaderboard_bootstrap.py > /dev/null
echo "  -> leaderboard_bootstrap.txt"

step "7/12 评分器三口径与污染反证"
python3 scripts/scorer_variants.py > /dev/null
python3 scripts/repro_scorer_pollution.py > /dev/null
# 故障注入：证明上一条的回归失败会真的传到退出码（D21）。
# 只在内存中把 calculate_reward 换回旧实现，不改磁盘源码；防线失效则退出 1。
python3 scripts/check_regression_failure_propagation.py > /dev/null
echo "  -> scorer_variants.txt / scorer_pollution_repro.txt"

step "8/12 漂移探针（重跑一致率、早/晚段比较）"
python3 scripts/analyze_drift.py > /dev/null
echo "  -> runs/e2_drift_r1/drift_analysis.md"

step "9/12 输入侧长度核验与其余稳健性检查"
python3 scripts/prompt_length_check.py > /dev/null
python3 scripts/robustness_collapse.py > /dev/null
python3 scripts/scorer_audit.py > /dev/null
python3 scripts/timeout_cell_sensitivity.py > /dev/null
python3 scripts/prereg_glmm_sensitivity.py > /dev/null
echo "  -> prompt_length_check.txt / robustness_collapse.txt / scorer_audit.txt"
echo "     timeout_cell_sensitivity.txt / prereg_glmm.txt"

step "10/12 重放保真度自检（137/137 标签 + 33,402 条 observation 逐字符）"
python3 scripts/replay_db_rescore.py > /dev/null
echo "  -> replay_rescore.txt / replay_rescore.csv"

step "11/12 论文两张图（全部值由冻结表现算）"
python3 scripts/make_fig1_language_effects.py > /dev/null
python3 scripts/make_fig2_2x2.py > /dev/null
echo "  -> paper/figures/fig1_*.png/.svg、fig2_*.png/.svg"

step "12/12 一致性与覆盖检查"
python3 scripts/audit_counts.py --check
python3 scripts/audit_artifacts.py --check
echo "  全部整数引用一致；results/ 顶层每个产物都有脚本能重建。"

printf '\n\033[1m离线复现完成。\033[0m论文主汇总表（Table 1–4、15、19）、H4（Table 4）、\n'
printf 'Collapse（Table 5、7、15）与长度配平表（Table 11）均已在本机重算。\n'
printf '把任一产物与本包内同名文件 diff，应当逐字节相同（时间戳/随机种子均已固定）。\n'
