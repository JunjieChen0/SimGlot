# v1.0 依赖绑定

本 S2 发布包把 `simglot/`（v1.0）的**最小依赖子集**随包分发，使 `sqj/` 的脚本
解包即可运行（脚本按 `SQJ.parent/simglot` 解析）。本文件说明**绑定了哪个 v1.0**、
**包了什么、没包什么**，以及**未随包的部分如何获取与核验**。

## 1. 绑定的 v1.0 是哪一个

| 项 | 值 |
|---|---|
| 完整留档包 | `simglot-full-20261009.tar.gz`，81,481,922 字节，37,056 成员（29,584 普通文件） |
| 其 SHA-256 | `2380993ab6f7fafd740427f07153d667fe32fc50f2de0c04d356fc7850eeba0f` |
| 匿名投稿包 | `simglot-anon-20261009.tar.gz`，80,734,508 字节，其 SHA-256 `f0afa24478df6db74f8d688cba919d04bdba8f75c601636c7c6d4c5fa2736d2b` |
| 冻结记录 | 包内 `simglot/RELEASE_FREEZE_v1.0.md`；包**外**校验清单 `dist/RELEASE_FREEZE_v1.0_checksums.txt` |
| 论文标识 | `paper/main.pdf`（49 页）SHA-256 `8a4ae320714d61c1102316f88d9f4f41fcc4914e52b9bb806c0846141b3a97b2` |

## 2. 随包分发的内容（`simglot/`）

| 路径 | 用途 |
|---|---|
| `vendor/tau-bench/` | 被测基准（含两域数据、工具、wiki） |
| `harness/` | v1.0 的运行器与评分器（E1/E2 的对照组源自它） |
| `data/` | `tasks_zh.json`（retail 中文套件）、`task_sample.json`、`output_aliases.json` |
| `scripts/_offline.py`、`db_replay.py`、`critval.py`、`_tee.py` | 离线引导、重放入口、临界值口径 |
| `results/frozen_table.csv` | 主矩阵的**修正后**冻结表（E1 的 env=en 对照） |
| `runs/ez2_envzh/`、`runs/ez2_lenmatch/` | 2×2 的两条环境语言批次（E1 的 zh / zhp 两臂从它们的 `agent_trace` 现算崩塌） |
| `config/providers.yaml` | 阵容与参数适配（**不含密钥**；`config/.env` 从不打包） |
| `RELEASE_FREEZE_v1.0.md`、`DEVIATIONS.md`、`README.md` | v1.0 的冻结与偏离记录 |

## 3. **未**随包分发的内容及其后果

| 路径 | 大小 | 为什么没包 | 后果 |
|---|---|---|---|
| `runs/e2_main24/` | 4,320 格 / 271 MB | 容量 | **单凭本包不能**独立重跑主矩阵的 4,320 条工具重放，也**不能**从原始轨迹重新渲染 E3 的裁定输入 |

**对这两项的补偿**（本轮新增）：

1. **E3 的裁定输入已随包**：`results/e3_adjudication_inputs.jsonl`（212 条、959 KB），
   即当时逐条送进裁定者的**原文**；配合 `runs/e3_blind/verdicts.csv` 可独立复核每一条判定。
2. **主矩阵的工具重放**仍需 v1.0 的 `runs/e2_main24/`。核验方式：
   按其包哈希（第 1 节）取得 `simglot-full-20261009.tar.gz`，
   把该目录置于 `<release_root>/simglot/runs/e2_main24/`，再运行
   `python3 simglot/scripts/db_replay.py`（只读重放，带磁盘缓存）。

## 4. 边界声明

- **本包不是"全部来源证据"**：它自包含**离线分析**所需的一切，但完整的主矩阵重放与
  E3 输入的从零重建需要 v1.0 的完整留档包。
- 本包**不含**任何密钥、`.env`、或真实个人信息；E3 输入中的用户轮已替换为 `[user turn]`，
  其余为客户记录为 τ-bench **合成**数据。
