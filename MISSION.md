## 目标
写出一个普通话语音合成引擎：输入文本，输出语音。引擎内不含任何人声采样
或由人声训练的权重，听感尽可能接近真人。

## 目录
engine/     可写。source/ tract/ control/ frontend/ synth.py
params/     仅数值优化器写。schema.json 和各版本参数文件
specs/      Researcher 写。公式、参数范围、出处
eval/       阶段 0 建好后冻结，只读
ledger/     只追加。experiments.jsonl
reports/    每代一份报告，外加 STATUS.md
listening/  导出给人听的样本
proposals/  你想改规则时写这里

## 引擎接口（固定，不得更改）
python -m engine.synth --text "你好" --seed 0 --params params/x.json --out a.wav
python -m engine.synth --pinyin "ni3 hao3" --seed 0 --params params/x.json --out a.wav
第二种调用绕过前端，供 T1、T2 使用。
输出单声道 WAV，采样率不低于 16 kHz。同一输入、参数和 seed 必须逐样本可复现。
实现用 Python 3 加 NumPy/SciPy，热点可用 Numba 或 C 扩展。

## 阶段 0：搭台（只做一次）
0.1 预检。检查 git、Python、磁盘、GPU、能否联网装包和下载模型、
    你能否并行派生子 agent 并给每个子 agent 独立工作树。
    结果写 reports/preflight.md。不能并行就串行扮演各角色。
    不能联网就停下，列出需要人提供的文件。
0.2 按 EVAL.md 建评估器。
0.3 校准。把真人录音和 eSpeak NG 的输出各跑一遍全部指标，
    写 reports/calibration.md。删除区分不开两者的指标。
    把 config.yaml 中标注"初始"的阈值按校准结果修改一次，此后不再改。
0.4 冻结。对 eval/ 全部文件算 SHA-256 写入 eval.lock，去掉写权限。
    config.auto_freeze 为 false 时在此停下等人确认。
    为 true 时须满足 config.freeze_checks 的全部条件才可继续，否则停下。
0.5 种子引擎。LF 声门波，Kelly-Lochbaum 声道（预留鼻腔分支），
    文献元音面积函数，最简前端（文本转拼音，查表得姿态目标，线性插值）。
    通过 T0 后作为 g0 写入账本和种群。

## 阶段 1：迭代循环（每代）
1. 校验 eval.lock。哈希不符立即停止并报告。
2. Planner 读账本和诊断，出 k 个假设。
3. 需要规格的假设先交 Researcher。
4. k 个 Implementer 并行，各自一个分支，只实现一个假设。
5. 每个通过 T0 的分支先跑数值优化器（固定预算），再送开发集评估。
6. Critic 逐个审查，给出 accept、reject 或 escalate。
7. 接受的版本进种群，按 Pareto 前沿保留 population_size 个。
8. 追加账本，写 reports/gen_NNN.md，覆盖写 STATUS.md。
9. 每 listening_every 代，把前沿最优版本的 20 条样本导出到 listening/。

结构改动之间的比较一律在第 5 步调参之后进行。

## 里程碑
M1 元音    主指标 T1 共振峰偏差
M2 音节    主指标 T2 音节准确率，约束 T2 声调准确率
M3 句子    主指标 T3 开发集 CER
M4 自然度  主指标 T4 综合分。没有终点，是否达标只能由人听（T5）判定
达到当前里程碑的过关线后，用终审评估器和隐藏集跑一次，只记录汇总分，
通过则进入下一里程碑。前一里程碑的指标自动转为约束，退步超过 5% 的版本不接受。

## 停止并等人
- eval.lock 校验失败
- Critic 给出 escalate
- 连续 stall_generations 代主指标无提升（先写一份原因分析）
- 任一预算上限触发
- 你认为某条约束妨碍进展（写 proposals/，不要自行绕过）
