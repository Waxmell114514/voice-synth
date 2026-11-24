#!/usr/bin/env bash
# 提案 002-B：使能型改动不调参，用指定参数直接评估。
#   tools/enabler_eval.sh <worktree> <实验 id> <参数文件（绝对路径）> [层级=T0,T1,T3]
set -euo pipefail
MAIN="$(cd "$(dirname "$0")/.." && pwd)"
WT="$(cd "$1" && pwd)"; ID="$2"; PRM="$3"; TIERS="${4:-T0,T1,T3}"; OUT="$MAIN/reports/evals"
for d in data models tools; do [ -e "$WT/eval/$d" ] || ln -s "$MAIN/eval/$d" "$WT/eval/$d"; done
[ -L "$WT/ledger/eval_calls.jsonl" ] || { rm -f "$WT/ledger/eval_calls.jsonl"; ln -s "$MAIN/ledger/eval_calls.jsonl" "$WT/ledger/eval_calls.jsonl"; }
cd "$WT"
for f in $(cd "$MAIN" && git ls-files eval); do cmp -s "$MAIN/$f" "$WT/$f" || { echo "eval 文件不一致: $f"; exit 3; }; done
python3 "$MAIN/tools/evallock.py" verify >/dev/null
cp "$PRM" "$OUT/$ID.params.json"
python3 eval/run.py --params "$PRM" --tiers "$TIERS" --set dev --experiment "$ID" > "$OUT/$ID.dev.json" 2> "$OUT/$ID.log"
# 语境检查必须用被测工作树里的工具（它加载所在树的引擎）
python3 tools/context_vowel_check.py "$PRM" > "$OUT/$ID.context.json" 2>> "$OUT/$ID.log"
python3 "$MAIN/tools/dynamic_t0_check.py" "$PRM" --parent-root "$MAIN" --parent-params "$PRM" > "$OUT/$ID.dynamic.json" 2>> "$OUT/$ID.log"
python3 - "$OUT" "$ID" <<'PY'
import json, sys
o, i = sys.argv[1], sys.argv[2]
d = json.load(open(f"{o}/{i}.dev.json")); c = json.load(open(f"{o}/{i}.context.json")); y = json.load(open(f"{o}/{i}.dynamic.json"))
print(json.dumps({"id": i, "T0": d["T0"]["pass"], "scores": {k: v["mean"] for k, v in d.get("scores", {}).items()},
                  "context": c["context_formant_rel_error"]["mean"], "context_failures": c["measure_failures"],
                  "energy_pass": y["energy_pass"], "clicks": y["clicks"]}, ensure_ascii=False))
PY
