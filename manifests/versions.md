# SimGlot vFinal · 版本冻结

- 冻结日期：**2026-10-10**
- 冻结范围：v1.0 主实验、S2 增强实验、增强轮（E0/B/C/D）、以及它们各自对应的稿件
- 一句话：**从本日起，论文里的每一个数字都只对应下面表中的一个哈希；不再有第二个候选。**

---

## 1. 为什么现在冻结

2026-10-10 一天内经过五轮独立定向复审，结论收敛为：

- **B 组（预言机有效性门禁、顺序/缓存反证、评分回归、B3/B4 统计口径）**：定向复现通过；
- **clean-room**：给定一份可用的 S2，A/B/C 三组复算退出 0（**计算验收**通过）；
- **剩下的全部未闭合项都在"版本身份"上**，而不在实验上。

审稿人一定会问：**「哪个版本产生了论文里的数字？」**
本目录的存在就是为了让这句话有一个**一行的、可复算的**答案。

---

## 2. 四个对外修订版（唯一）

| 角色 | 文件（`packages/` 下） | 字节 | SHA-256 | 数据范围 | 对应稿件 |
|---|---|---:|---|---|---|
| **v1.0 完整留档** | `simglot-v1.0-final.tar.gz` | 81,481,922 | `2380993ab6f7fafd740427f07153d667fe32fc50f2de0c04d356fc7850eeba0f` | 主矩阵 **4,320 格**原始记录 + 49 页稿源与 PDF | v1.0 稿（`paper/`，49 页） |
| **v1.0 匿名投稿** | `simglot-v1.0-anon-final.tar.gz` | 80,734,508 | `f0afa24478df6db74f8d688cba919d04bdba8f75c601636c7c6d4c5fa2736d2b` | 与完整包同内容的**双盲版本**，绑同一个最终 PDF | 同上（双盲提交用） |
| **S2 自包含发布** | `simglot-S2-final.tar.gz` | 70,518,492 | `8e41d28ebfa19506a3da9232a98e830d8b9cfe69c794e46cbf2779ef557fd64e` | E0 套件 + **E1 3,240 格** + **E2 1,200 格** + **E3 212 条**；含 `sqj/` 全树与 vendored τ-bench | EMSE 稿 RQ1 与 RQ3 |
| **增强轮（增量）** | `simglot-enhancement-final.tar.gz` | 400,028 | `dffa09ef0b912e3ed20f9c068698bf6be94e94e00dc0b3f57627a2bf4b0f59e9` | A（AppWorld 负结果）+ B（预留变体/消融/基线/开销）+ C（功效与预算，**未执行**）+ D（E3 证据闭合）+ §7 发布工程 | EMSE 稿 RQ2 边界与复现包 |

**四个包共用一个校验入口**（每个角色只有一行，没有第二候选）：

```bash
python3 simglot_vfinal/checks/verify_freeze.py            # 逐角色核哈希与字节数
python3 simglot_vfinal/checks/verify_freeze.py --which 2380993a   # 反查某个哈希属于哪一版
```

**包哈希写在本目录**（`FREEZE_CHECKSUMS.txt` / `FREEZE_MANIFEST.json`）——
本目录**不在**任何一个包内，所以不构成自指。

---

## 3. 已退役的修订版（明确列出，**不得引用、不得分发**）

冻结的实质是**排除**。下面每一条都写明它是什么、以及为什么不是论文的对应版本。

| 哈希 | 字节 | 属角色 | 说明 |
|---|---:|---|---|
| `215d656fecd00d675d10dfdf0676dc2e475c18d58ab4c16ffc82a600376e03f2` | 81,482,739 | v1.0-full | **2026-10-08 第九轮（D21）构建**。`dist/superseded/README.txt` 早已标注「已被取代，不要投稿或分发」。**第五轮复审手上核到的正是这一个**——那是退役件，不是我方对外发布版 |
| `13a6ffd20f4d8db8a593dff716e87bb5e7c2bd72882b6250ee6c025872929832` | 80,721,503 | v1.0-anon | 2026-10-08 构建，已被取代 |
| `24e8f4c0c60e46aa4bd14cc0b105df81a31d5b93f83c9a567ae68f90640447c3` | 69,174,713 | S2 | **本机查无此文件**。第五轮复审手上可访问的是这一个。见 §4 |
| `b03b7c80eeaffdcfcea5a78cc642c6f938ca2f8dfd227d1cc9d95c5680ce10a0` | 117,105 | enhancement | 第二轮修订版 |
| `ffcfaa09cf9c73209a5fcfe1396921e742de3c5e0d82d9d46b65dca518b1dbb5` | 361,825 | enhancement | 第三轮修订版 |
| `2a82a8956e0a83bf2c92a927249f0d8dae638e2079f0b13de1aa02cf181f78c7` | 385,292 | enhancement | 第四轮修订版 |
| `9e8ffd8fbd81c40c6291fdde290be3b86680d39bc0d9311aebced38f7110d604` | 399,979 | enhancement | 第五轮修订版（**R5 复审手上是这一个**；差异仅在本轮之后的版本命名与文档） |
| `628f47be…`（仅记前缀） | 86,801 | enhancement | 第一版增强包 |

**另有两条存档，不属于任何角色，也不得当作发布版**：
`sqj/dist/simglot-s2-full-20261009.tar.gz`（42.7 MB）与
`sqj/dist/simglot-s2-code-20261009.tar.gz`（289 KB）——是 S2 的开发/代码存档。

---

## 4. 一处仍需作者拍板的例外：S2 的另一个修订版

**事实**：本机只有**一个** S2 对外发布候选（`8e41d28e…`，70,518,492 字节，
记于该包自己的 `sqj/dist/RELEASE_20261009_checksums.txt`）；
第五轮复审在其环境里可访问并用于 B 组兼容验证的是 `24e8f4c0…`（69,174,713 字节），
**本机没有对应文件**，因此无法判定它是更早的构建、还是重新打包的同一内容。

**本方不擅自改绑**。原因：S2 的第三方独立审计（`SimGlot_S2_Release_Independent_Audit_20261009.md`）
核算的是它当时拿到的那一版；把冻结记录改成另一个哈希，会让**那份背书错配**。

**若作者确认对外发布的是 `24e8f4c0…`**，按下面四步重新出具冻结记录：

1. `checks/pin_s2.py --candidate <那份 tar>` —— 一致退 0、不一致退 2
   （它会打印要改的三处）；
2. `sqj_enhancement_v1/manifests/sources.json` 的 `sqj-s2-release` 条目
   （`sha256` / `bytes` / 更新 `sibling_check` 的修订版限定措辞）；
3. `sqj_enhancement_v1/manifests/RELEASE_PROVENANCE.md` 的「未对齐项」一段；
4. 重跑 `sqj_enhancement_v1/release/package_enhancement.sh`（八道门，门 ② 是
   `--require-all-verified`），再把本目录的 `packages/simglot-S2-final.tar.gz`
   换成新版并 `verify_freeze.py --write`。

> **注意**：v1.0 那条**不需要**这个例外——复审手上的 `215d656f…` 已经查明是
> `dist/superseded/` 里的退役件，`superseded/README.txt` 早就写着「不要投稿或分发」。

---

## 5. 冻结之后不再做的事

- 不再新增模型实验（更多语言 / 更多 episode / 更多模型 / 更多智能体）；
- 不再新增泛化门槛；
- 不再重命名任何包（**一个角色一个名字**，本目录就是唯一的对外哈希记录）；
- 唯一的可选项是 **E1 共时三臂验证**（回应"组件差异是否来自时间漂移"），
  但它**不是投稿阻断项**，且已有功效分析显示 1.11 pp 在本设计下判不了——
  除非审稿人明确要求，否则不做。

项目终态见 [`FINAL_STATUS.md`](FINAL_STATUS.md)。
