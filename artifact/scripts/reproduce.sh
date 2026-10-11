#!/usr/bin/env bash
# SimGlot artifact · 离线复现入口
#
# 设计原则：**这一条命令只做它真能做的事，并如实说明做不到的**。
# 本仓库不含四个冻结归档（232 MB，在 Zenodo），所以需要逐格原始记录的实验在此跑不了；
# 不需要它们的部分——预言机审计、门禁回归、由小输入重算的表——**在无网络、无密钥、
# 无模型调用的条件下**全部跑得起来。
#
# 关于「工作目录」：仓库里的脚本是**逐字节**来自冻结归档的（见 manifests/provenance.json），
# 它们按原始工作树的目录布局解析相对路径。本脚本在 $SCRATCH 里按那个布局把文件摆好再跑，
# **不改动任何被拷贝的脚本**——这样「这是跑出论文数字的那份代码」才是可核验的，而不是一句承诺。
#
# 用法：
#   bash artifact/scripts/reproduce.sh            # 全部能跑的
#   bash artifact/scripts/reproduce.sh --fast     # 只跑秒级自查
#   bash artifact/scripts/reproduce.sh --list     # 只列出会跑什么
#
# 退出码：0 = 本次打算跑的都通过；1 = 有失败；2 = 环境不满足。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRATCH="${SIMGLOT_SCRATCH:-}"
if [ -z "$SCRATCH" ]; then SCRATCH="$(mktemp -d -t simglot-XXXXXX)"; KEEP=0; else KEEP=1; fi
FAST=0; LIST=0
for a in "$@"; do
  case "$a" in
    --fast) FAST=1 ;;
    --list) LIST=1 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
fail=0
step() { echo; echo "──────── $* ────────"; }
ok()   { echo "  ✓ $*"; }
no()   { echo "  ✗ $*" >&2; fail=1; }
skip() { echo "  · $*"; }

command -v "$PY" >/dev/null || { echo "✗ 找不到 $PY" >&2; exit 2; }

# ── 密钥防线 ────────────────────────────────────────────────────────────────
# 与论文的声明一致：任何一步都不读密钥。若环境里存在，明确拒绝而不是「静默还能跑」——
# 否则「离线复现」会悄悄变成在线调用，而结果仍看似跑通。
for v in DASHSCOPE_API_KEY DMXAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY; do
  if [ -n "${!v:-}" ]; then
    echo "✗ 检测到 $v。本入口不需要也不允许密钥，请在无密钥的环境里运行。" >&2
    exit 2
  fi
done

if [ "$LIST" = "1" ]; then
  cat <<'EOF'
本次会跑：
  1. 环境自查            artifact/scripts/verify_environment.py
  2. 预言机完整性审计    artifact/oracle_audit/run_audit.py    （零模型调用）
  3. 门禁回归            artifact/gates/validity_gate_regression.py
  4. 顺序/缓存反证        artifact/gates/order_cache_counterexample.py
  5. 评分回归防伪        artifact/gates/scoring_regression.py
  6. 结果表汇总          artifact/scripts/build_tables.py      （重算论文 Table 1）

本次**不会**跑（需要 Zenodo 归档里的逐格记录，本仓库不含）：
  · E1 组件消融的原始重算（3,240 格）  —— 已给分析产物 results/summary/e1_full_analysis.txt
  · E2 跨域检验的原始重算（1,200 格）  —— 已给分析产物 results/summary/e2_full_analysis.txt
  · E3 裁定的重跑（212 条）            —— 需要模型调用；已给输入清单与产物
  · 主矩阵 4,320 格的回放修正          —— 命令见 docs/reproduction.md
EOF
  exit 0
fi

echo "SimGlot artifact · 离线复现"
echo "仓库：$REPO"
echo "工作目录：$SCRATCH"

# ── 0. 环境 ────────────────────────────────────────────────────────────────
step "0. 环境自查"
if "$PY" "$HERE/verify_environment.py"; then ok "环境满足"; else no "环境不满足"; fi

if [ "$FAST" = "1" ]; then
  step "完成（--fast：只跑了自查）"
  [ "$fail" = "0" ] && echo "✓ 通过" || echo "✗ 有失败" >&2
  exit "$fail"
fi

# ── 搭建脚本期望的工作区布局 ────────────────────────────────────────────────
step "1. 按原始工作区布局准备 scratch"
rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/simglot/vendor" "$SCRATCH/simglot/scripts" \
         "$SCRATCH/sqj" "$SCRATCH/enhancement/experiments" "$SCRATCH/enhancement/results/.cache"

ln -s "$REPO/vendor/tau-bench" "$SCRATCH/simglot/vendor/tau-bench"
ln -s "$REPO/artifact/harness" "$SCRATCH/simglot/harness"
for f in _offline.py _tee.py; do
  ln -s "$REPO/artifact/harness/$f" "$SCRATCH/simglot/scripts/$f"
done
# 套件本体与 `_boot.py` 必须**复制**而非软链：两者都用 Path(__file__).resolve() 推工程根，
# 软链会被解析回仓库、算出错误的根目录。
cp -r "$REPO/artifact/oracle_audit" "$SCRATCH/sqj/oracle_audit_kit"
cp    "$REPO/artifact/_boot.py"     "$SCRATCH/enhancement/_boot.py"
ln -s "$REPO/artifact/holdout" "$SCRATCH/enhancement/experiments/oracle_mutation_holdout"
# 门禁脚本也**复制**：它用 Path(__file__).resolve() 向上找 `_boot.py`，
# 软链会被解析回仓库、从而找到仓库里那份 `_boot.py` 并算出错误的根。
cp -r "$REPO/artifact/gates" "$SCRATCH/enhancement/checks"
ok "布局就绪（被拷贝的脚本一个字节都没改）"

# ── 2. 预言机完整性审计 ─────────────────────────────────────────────────────
step "2. 预言机完整性审计（零模型调用，约 10 分钟；用 --fast 可跳过）"
if ( cd "$SCRATCH/sqj/oracle_audit_kit" && "$PY" run_audit.py --tasks 3 \
       --targets tau-bench/retail,synthetic/tiny ); then
  ok "审计完成，产物在 $SCRATCH/sqj/oracle_audit_kit/results/"
else
  no "审计未通过"
fi

# ── 3. 门禁 ────────────────────────────────────────────────────────────────
step "3. 门禁：有效性回归 + 顺序/缓存反证 + 评分回归"
for chk in validity_gate_regression order_cache_counterexample; do
  if ( cd "$SCRATCH/enhancement" && SIMGLOT_S2_ROOT="$SCRATCH/sqj" \
       "$PY" checks/$chk.py >/dev/null 2>&1 ); then
    ok "$chk"
  else
    no "$chk"
  fi
done
if ( cd "$SCRATCH/enhancement" && SIMGLOT_S2_ROOT="$SCRATCH/sqj" \
     "$PY" checks/scoring_regression.py --tasks 3 --targets tau-bench/retail >/dev/null 2>&1 ); then
  ok "scoring_regression"
else
  no "scoring_regression"
fi

# ── 4. 结果表（由随仓库的小输入现算） ───────────────────────────────────────
step "4. 结果表汇总（重算论文 Table 1）"
if ( cd "$REPO" && "$PY" artifact/scripts/build_tables.py ); then
  ok "结果表已写到 results/summary/"
else
  no "build_tables.py"
fi
skip "变体级消融 analyze_b.py 按原始工作区路径读输入，本布局下其功能由上面的 build_tables.py 覆盖"

# ── 收尾 ───────────────────────────────────────────────────────────────────
step "完成"
if [ "$fail" = "0" ]; then
  echo "✓ 本次打算跑的全部通过。"
  echo
  echo "  这**只**代表：可以由本仓库算出来的那部分复现了。"
  echo "  需要四个冻结归档的实验，命令见 docs/reproduction.md，数据见 docs/data_availability.md。"
else
  echo "✗ 有步骤失败，见上面的 ✗ 行。" >&2
fi
[ "$KEEP" = "1" ] || rm -rf "$SCRATCH"
exit "$fail"
