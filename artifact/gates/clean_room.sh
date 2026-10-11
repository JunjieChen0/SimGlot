#!/usr/bin/env bash
# clean-room 复现入口（第三轮外部复审 §7 之后补）。
#
# 本包是**增量包**：不含 S2（`oracle_audit_kit` + vendored τ-bench）与 v1.0。
# 本脚本把「哪些命令能在哪种条件下跑、期望退出码是什么」一次讲清并实测，
# 不再出现「解包后直接运行 → 裸 StopIteration，读者不知道缺什么」。
#
# 用法：
#   bash checks/clean_room.sh <S2 解包目录>      # 默认 ../sqj
#   PYTHON=/path/to/python bash checks/clean_room.sh <S2 解包目录>
#
# 退出码：0 = 全部应跑的检查都过；非 0 = 有检查失败。
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
S2="${1:-$ROOT/../sqj}"
PY="${PYTHON:-python3}"

# S2 发布包解包后，`oracle_audit_kit/` 在包根的 `sqj/` 子目录里。
# 允许传**包根**或**含 oracle_audit_kit 的那一层**，这里统一后者。
if [ ! -d "$S2/oracle_audit_kit" ] && [ -d "$S2/sqj/oracle_audit_kit" ]; then
  S2="$S2/sqj"
fi

echo "══════════════════════════════════════════════════════════════════════"
echo " SimGlot 增强轮 · clean-room 复现"
echo "   包根：$ROOT"
echo "   S2  ：$S2"
echo "   解释器：$PY"
echo "══════════════════════════════════════════════════════════════════════"

fail=0
run() {                                  # run <说明> <命令...>
  local desc="$1"; shift
  echo ""
  echo "── $desc"
  echo "   \$ $*"
  if "$@" > /tmp/clean_room_step.log 2>&1; then
    echo "   ✓ 退出码 0"
    tail -n 2 /tmp/clean_room_step.log | sed 's/^/     /'
  else
    echo "   ✗ 退出码非 0："
    tail -n 15 /tmp/clean_room_step.log | sed 's/^/     /'
    fail=1
  fi
}

echo ""
echo "── A 组：**不需要 S2**，解包即可跑"
run "E3 清单复算 + 212 条逐条对齐" "$PY" evidence/e3_inputs/build_manifest.py --check
run "B3/B4 与七类聚合（只读 CSV 与冻结的变体目录）" "$PY" analysis/analyze_b.py

if [ ! -d "$S2/oracle_audit_kit" ]; then
  echo ""
  echo "── B 组：需要 S2 的 \`oracle_audit_kit\`——**未提供**，跳过"
  echo "   给一个 S2 解包目录即可跑（S2 发布包见 paper/仓库说明）："
  echo "     bash checks/clean_room.sh /路径/to/simglot-s2-release"
  echo ""
  echo "✗ clean-room 未跑完（B 组被跳过）——A 组结果：$([ $fail -eq 0 ] && echo 全过 || echo 有失败)"
  exit 3
fi

export SIMGLOT_S2_ROOT="$S2"
echo ""
echo "── B 组：需要 S2（已设 SIMGLOT_S2_ROOT=$S2）"
run "有效性门禁回归（含顺序/缓存三条断言）" "$PY" checks/validity_gate_regression.py
run "顺序/缓存独立执行反证" "$PY" checks/order_cache_counterexample.py
run "评分回归防伪（双向）" "$PY" checks/scoring_regression.py --tasks 3 --targets tau-bench/retail

echo ""
echo "── C 组：顶层来源绑定（**计算验收，不是全来源哈希验收**）"
echo "   包外的 v1.0/S2 不在本目录时记 SKIPPED_EXTERNAL，自指条目记 NOT_ASSEMBLED；"
echo "   **只有 VERIFIED 算核过**，跳过/未组装一律不是通过。"
run "来源绑定（--available-only）" "$PY" checks/verify_sources.py --available-only \
    --write-status release/SOURCES_VERIFICATION.txt

echo ""
if [ "$fail" -eq 0 ]; then
  echo "✓ clean-room 全过（A + B + C 组）——这是**计算验收**。"
  echo "  ⚠ 它**不是**全来源哈希绑定 PASS：C 组里哪些条目真的核过，看上面"
  echo "    「已核 N/M 条」与 release/SOURCES_VERIFICATION.txt；"
  echo "    跳过/未组装的外部来源（v1.0、S2、增强包自身）本次**没有**被核对。"
  echo "    严格的全来源核验要在**组装好的工作区**里跑不带参数的 checks/verify_sources.py，"
  echo "    发布验收还要加 --require-all-verified。"
else
  echo "✗ clean-room 有失败步骤，见上。"
fi
exit "$fail"
