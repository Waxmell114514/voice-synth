experiments.jsonl 每行一条，只追加：
{
  "id": "g012-e07",
  "parent": "g011-e03",
  "milestone": "M2",
  "hypothesis": "一句话，只含一个机制",
  "prediction": {"metric": "T2.syllable_acc", "delta": "+0.03"},
  "touched_modules": ["tract"],
  "new_params": ["fric_noise_gain"],
  "result": {"T0": "pass", "T2.syllable_acc": 0.71, "T2.tone_acc": 0.88, "std": 0.01},
  "verdict": "accept | reject | escalate | failed_T0 | not_implemented",
  "lesson": "一句话",
  "cost": {"wall_min": 42}
}
prediction 必须在运行评估之前写入。
