"""SimGlot harness —— 中英双语用户模拟器审计的实验骨架。

设计原则：
  * 复用 τ-bench 的**环境层**（工具、数据库、任务、规则化评分）——这是它的价值所在；
  * **不复用**它的模型层与智能体层——我们自己控制请求参数（含关闭思考模式）、
    日志、成本记账，并对原实现中会导致隐性调用/副作用的地方做显式隔离。
"""

import os

# litellm 首次导入会去 raw.githubusercontent 拉价目表（本机不可达，会重试并告警）。
# 强制使用本地内置表，避免启动延迟与噪声。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
