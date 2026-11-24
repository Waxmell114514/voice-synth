# 阶段 0.1 预检报告（2026-11-24）

| 项目 | 结果 |
|---|---|
| git | 2.43.0，分支 `claude/clever-hopper-io6yyj` |
| Python | 3.13.18 |
| NumPy / SciPy / Numba | 2.5.3 / 1.18.1 / 0.68.1（pip 安装成功） |
| PyTorch | 2.15.0+cpu（仅 CPU 版） |
| CPU / 内存 | 4 核 / 15 GB，无 swap |
| GPU | **无**（无 nvidia-smi）。所有评估器在 CPU 上推理 |
| 磁盘 | 可用约 61 GB |
| 联网装包 | PyPI、apt 可用 |
| 下载模型 | Hugging Face 可用；raw.githubusercontent.com 可用；github.com 发布页、codeload 和 download.pytorch.org/torchaudio/models 返回 403（被代理拒绝） |
| 下载语料 | Hugging Face 上 `AISHELL/AISHELL-3`（Apache-2.0，逐文件 wav）可用；OpenSLR 镜像 us.openslr.org 不通 |
| eSpeak NG | 1.51，`cmn` 普通话语音可用 |
| 并行子 agent | 可用。已实测：子 agent 获得独立 git 工作树和独立分支（`.claude/worktrees/…`），互不干扰 |
| 并行上限 | config 允许 6 个 worker，但只有 4 核 CPU。评估和调参是 CPU 密集型，并行实现可以开 6 个，并行评估实际限为 4 个进程 |

## 结论
- 可以联网，阶段 0 继续，无需人提供文件。
- 可以并行派生子 agent，每个有独立工作树。
- 无 GPU：评估器选型偏向 CPU 上快的模型（sherpa-onnx int8、faster-whisper int8）。
  CMA-ES 每变体 150 次评估的耗时需要在 0.3 校准后实测，如超出预算会在报告中说明。

## 已下载的评估器候选（均放在 eval/models/，不进 git，体积约 4 GB）
| 用途 | 候选 |
|---|---|
| ASR | Paraformer-zh 2024-03-09（sherpa-onnx int8）；SenseVoiceSmall（sherpa-onnx int8，2025-09-09）；Whisper small、Whisper large-v3-turbo（faster-whisper） |
| MOS | UTMOS22 strong（prj-beatrice torch-native 移植）；NISQA v2 权重（gguf） |
| 反欺骗 | AASIST（clovaai 官方权重）；AASIST（SpeechAntiSpoofingBenchmarks）；wav2vec2 Deepfake-audio-detection-V2（MelodyMachine） |
| 自监督嵌入 | chinese-hubert-base（TencentGameMate）；wavlm-base-plus（Microsoft） |

## 与原规则的偏差需要人知道
- 容器是临时的。eval/models 和 eval/data 体积大，不进 git；`eval/fetch.py` 记录来源，
  `eval.lock` 记录每个文件哈希，换容器后重新下载可按哈希核对。
