"""E0 · 测试预言机完整性审计套件（零模型调用）。

模块：
  _paths             离线引导（只读接入 v1.0 树、禁止联网）
  adapters           审计对象：τ-bench retail / airline / 合成域
  oracle_variants    故障注入：7 类已知预言机缺陷
  detectors          8 个检测器（5 不变量 + 3 对照）
  run_audit          驱动器 → results/oracle_audit_matrix.{txt,csv}
"""
