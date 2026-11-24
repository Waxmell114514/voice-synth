# 评估器（阶段 0 建成，冻结后只读）

## 用法
```bash
python eval/run.py --params params/x.json --tiers T0,T1 --set opt               # 优化器 / 快速检查，不计配额
python eval/run.py --params params/x.json --tiers T0,T1,T2,T3,T4 --set dev --experiment g001-e02
python eval/run.py --params params/x.json --tiers T1,T2,T3,T4 --set hidden --suite final --acceptance M1
```
输出为一个 JSON：各层分数（3 个 seed 的均值和标准差）与 EVAL.md 允许的诊断
（各层分数、声母 / 韵母 / 声调混淆、T4 各分项、T1 各元音偏差）。隐藏集和终审组只输出汇总分。
开发集评估每个实验至多 `config.eval_quota_per_experiment` 次，记录在 `ledger/eval_calls.jsonl`。

## 组成
| 文件 | 作用 |
|---|---|
| build_data.py | 从 AISHELL-3（Apache-2.0，HF 镜像中实际存在的文件）构造句子集、词表、参考池 |
| calibrate.py / finalize_calibration.py | 阶段 0.3 校准（只运行一次） |
| run.py | 各层评估 |
| t0.py | T0 物理单测 |
| vowels.py | T1 元音共振峰测量 |
| common.py | 拼音化、对齐、混淆矩阵、音频预处理、F0 / 时长 / Fréchet |
| models.py | ASR、MOS、反欺骗、SSL 模型封装 |
| runner.py, _worker.py | 引擎（隔离的常驻子进程）、eSpeak NG、真人录音 |
| ENGINE_API.md | 评估器对引擎的要求（CLI 的 main、T0 钩子、schema 格式） |
| data/ | 句子集、词表、参考统计、校准结果、录音（不进 git） |
| models/, tools/ | 模型权重、eSpeak NG 1.52 源码构建（不进 git） |

## 测量要点
- 所有神经评估器的输入统一：16 kHz、去首尾静音（−40 dB，留 100 ms）、有声段 RMS 归一到 −23 dBFS。
- 拼音比对：参考与识别结果都用同一 pypinyin 转 TONE3（轻声 5），音节对齐用不计调的编辑距离；
  声调正确 = 对齐位置音节相同且声调相同。
- T1：合成侧为孤立音节（a1 o1 e1 yi1 wu1 yu1）有声段中间 40% 的 Praat Burg 共振峰中位数
  （最高 5500 Hz，5 个）；参考侧为参考说话人连续语流中的同类元音（SenseVoice 字级时间戳定位）。
  参考语料全部为北方女声，因此 T1 和 T4 都以女声为目标。
- T4：MOS 与反欺骗为逐句均值；SSL 为第 6 层均值池化，投到参考池 64 维 PCA 上算 Fréchet 距离；
  F0 为句内中位数归一的半音分布；时长为“有声时长 / 音节数”的逐句分布；后两者用 1 维 Wasserstein 距离。
  各分项按 `calibration.json` 中的基线（eSpeak NG）→ 真人锚点线性归一化并裁剪到 [0,1]，取均值为综合分。
