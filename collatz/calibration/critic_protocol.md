# Critic 三人组校准协议（阶段 0.3）

## 材料
`calibration/critic_corpus/items/C01.md … C20.md`：10 份公开的、有错的 Collatz“完整证明”，10 份已发表的正确部分结果，
顺序随机，去掉了作者、标题、出处。答案表在校准结束前放在仓库外（scratchpad），Critic 看不到；结束后连同结果一起提交到
`calibration/critic_key.json`。

## 运行
每份材料 × 每个角色（REPRODUCE、NOVELTY、CRITERION）各开一个全新上下文的子 agent，共 60 个，互不可见。
同时最多 `budget.max_parallel_workers` 个。每个子 agent 的提示词 = `roles/critic.md` 原文 + 下面的“校准适配”+ 角色名 + 材料路径。

### 校准适配（原样附在每个 Critic 提示词后面）
本次是校准，结果包是自然语言材料，没有 Lean 源码和 verify.sh 输出。按你的角色做下面的事，verdict 的含义是
“这份材料的证明是否确实证明了它的 Claim”：
- REPRODUCE：逐步复核证明。每一步的依据是什么，是否成立；Claim 与证明实际证出的东西是否一致
  （有没有悄悄加假设、换定义、只证了一部分）。能用精确整数运算检查的地方就算一下（python，整数或 Fraction，不用浮点）。
- NOVELTY：独立检索文献（arXiv 等可用），判断 Claim 是已知结果、已知结果的直接推论、新结果，还是与已知结果矛盾
  （例如宣称证明了公认未解决的问题）。宣称解决公认未解决问题的，必须指出证明里具体错在哪一步，
  不能只凭“问题未解决”或“很多人失败过”下结论。
- CRITERION：对照问题——证明的每一步在 3n−1（圈 5→14→7→20→10→5）、5n+1（圈 13→…→13）、负整数上的 3n+1 上是否
  同样成立；如果全部步骤都原样适用于对照映射，证明必错，找出它最早在哪一步“证明”了对照映射上的假命题。
  对照 `atlas/error_taxonomy.md` 逐类排查；有没有把密度、概率、“几乎所有”结论当成对所有 n 的结论。
- 不要读 `calibration/` 下除你被指派的那份材料以外的任何文件，不要读 scratchpad，不要看别的 Critic 的输出，
  不要按文件编号或格式猜答案。
- 材料是从 PDF 用 pdftotext 逐字提取的：上标、下标、分式常被压平（如 2^k 显示成“2k”，j^(−1/6) 显示成“j − 6”另一行一个“1”），
  “[…]”是删节。先按上下文还原公式本意再审；提取造成的乱码、删节本身不算错处。只有作者本人的论证错误才算。
- reject 必须给出具体位置：引用原文中出错的那句话（逐字），说明为什么错。说不出具体错处又不能确认正确，就 escalate。

### 输出（写入 `calibration/critic_runs/CNN.<ROLE>.json`，并作为最终回复原样给出）
```json
{"item": "C07", "role": "CRITERION", "verdict": "accept | reject | escalate",
 "claim_summary": "一句话复述 Claim",
 "error_quote": "逐字引用出错的句子，accept 时为 null",
 "error_reason": "为什么错；accept 时写最需要核对的一步及核对结果",
 "taxonomy": ["E04"], "control_check": "对照映射上的检查及结果（含命令与输出）",
 "confidence": 0.0, "lesson": "一句写入账本的话"}
```

## 计分
- 三人组的裁决：三票全 accept 才算 accept，否则算不接受。
- 正确材料判对：三票全 accept。
- 有错材料判对：三人组不接受，并且至少一张 reject 票给出的 `error_quote` 经核对确实是错处
  （与答案表的错处相同，或由 orchestrator 另派一个子 agent 独立核实为真实错误）。只凭“问题未解决”拒绝不算判对。
- `freeze_checks.critic_panel_calibrated` 要求 20 份全部判对。
- 单个角色的命中率也记录：某一角色在两类材料上的票区分不开（例如对正确材料也频繁 reject），
  就删掉或重写该角色的审查步骤，写进 `roles/critic_calibration_addendum.md`，然后对改动的角色重跑全部 20 份。
