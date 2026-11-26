# STATUS（覆盖写）— 2026-11-26，人要求“先都暂停”

**停在哪**：阶段 0.3（Critic 三人组校准）进行中，同时提前开工的 0.5 图谱 D1a 和 0.6 种子库 R1–R3。
**为什么**：人下令暂停。所有后台子 agent 已停止，没有残留的 lean/lake 进程，没有新任务排队执行。

## 已完成并已推送
- 0.1 预检（reports/preflight.md）；0.2 statement/、verify.sh、roles/、config.yaml。
- 0.3 verify.sh 校准：25 个样本 26 次检查全部判对（冻结前需用最终版完整重跑一次）。
- 0.3 Critic 校准语料：20 份盲审材料与 60 份提示词（calibration/critic_corpus、critic_prompts）。
  答案表在仓库外：scratchpad/critic_key.json（容器回收即丢失；恢复前应决定是否先提交）。
- Critic 结果：60 次中完成 2 次（C01.REPRODUCE、C01.NOVELTY，都是 reject，错处与答案表一致）。

## 被中断、未保存或未完成
| 任务 | 中断时状态 |
|---|---|
| Critic C01.CRITERION | 中断，无输出；队列剩 57 次（scratchpad/critic_queue.txt） |
| Prover g000-R1 | 工作树 `.claude/worktrees/agent-a43143ce6a99ad11c` 里有未提交、未验证的 lib/Lib/Seed/R1.lean（227 行）和 routes/seed.md |
| Prover g000-R2 + R3 | 工作树已被自动清理，无产出保留 |
| Cartographer D1a | 仓库内无产出保留（atlas/domains/D1a 未生成） |

## 恢复时需要人决定
1. 是否继续，从哪一步继续（建议：先跑完 Critic 校准，它是冻结的前置条件）。
2. 72 小时预算是否从暂停起停表。
3. 种子库和图谱是否仍在冻结前并行开工，还是严格按 0.3 → 0.4 → 0.5 → 0.6 顺序。
