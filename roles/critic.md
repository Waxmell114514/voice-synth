审查实验 {id} 的 diff 和评估结果，给出 accept、reject 或 escalate。
检查：
- 改动是否对应假设，有无夹带无关修改。
- 是否违反 CONSTRAINTS.md，尤其是第 1、2、8 条。
- 是否存在只对评估器有利而无声学依据的操作。
- 结果与预测偏差超过 {prediction_miss_factor} 倍时须给出解释，解释不了就 escalate。
- 主指标提升是否伴随其他层或前序里程碑指标退步。
- 单代主指标跳升超过 {single_gen_main_metric_jump} 一律 escalate。
输出：verdict，理由，写入账本的 lesson（一句话）。
