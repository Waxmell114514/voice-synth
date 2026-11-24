#!/usr/bin/env bash
# 对一个 Implementer 分支跑第 5 步：T0 → 调参（固定预算，种子 1）→ 开发集评估 → 语境检查。
#   tools/branch_pipeline.sh <worktree 路径> <实验 id> [里程碑=M1] [开发集层级=T0,T1,T3]
# 评估数据、模型、eSpeak 与配额日志都链接到主仓库，配额统一计数；结果写回主仓库 reports/evals/。
set -euo pipefail
MAIN="$(cd "$(dirname "$0")/.." && pwd)"
WT="$(cd "$1" && pwd)"; ID="$2"; MS="${3:-M1}"; TIERS="${4:-T0,T1,T3}"
OUT="$MAIN/reports/evals"; mkdir -p "$OUT"
for d in data models tools; do [ -e "$WT/eval/$d" ] || ln -s "$MAIN/eval/$d" "$WT/eval/$d"; done
mkdir -p "$WT/ledger"
[ -L "$WT/ledger/eval_calls.jsonl" ] || { rm -f "$WT/ledger/eval_calls.jsonl"; ln -s "$MAIN/ledger/eval_calls.jsonl" "$WT/ledger/eval_calls.jsonl"; }
cd "$WT"
echo "[$ID] eval 代码与主仓库比对"
for f in $(cd "$MAIN" && git ls-files eval); do cmp -s "$MAIN/$f" "$WT/$f" || { echo "eval 文件不一致: $f"; exit 3; }; done
python3 "$MAIN/tools/evallock.py" verify >/dev/null
echo "[$ID] T0"
python3 eval/t0.py params/g0.json > "$OUT/$ID.t0.json"
python3 -c "import json,sys;d=json.load(open('$OUT/$ID.t0.json'));sys.exit(0 if d['pass'] else 2)" || { echo "[$ID] T0 FAIL"; exit 2; }
echo "[$ID] 调参"
EVAL_SYNTH_WORKERS=2 python3 tools/optimize.py --parent "${PARENT:-params/g0.json}" --out "params/$ID.json" --milestone "$MS" --seeds "${SEEDS:-1,2,3}" --budget "${BUDGET:-450}" \
  > "$OUT/$ID.opt.json" 2> "$OUT/$ID.opt.log"
cp "params/$ID.json" "$OUT/$ID.params.json"
echo "[$ID] 开发集评估"
python3 eval/run.py --params "params/$ID.json" --tiers "$TIERS" --set dev --experiment "$ID" > "$OUT/$ID.dev.json" 2>> "$OUT/$ID.opt.log"
echo "[$ID] 语境检查"
python3 tools/context_vowel_check.py "params/$ID.json" > "$OUT/$ID.context.json" 2>> "$OUT/$ID.opt.log"
python3 - "$OUT" "$ID" <<'EOF'
import json, sys
o, i = sys.argv[1], sys.argv[2]
d = json.load(open(f"{o}/{i}.dev.json")); c = json.load(open(f"{o}/{i}.context.json")); p = json.loads(open(f"{o}/{i}.opt.json").read().strip().splitlines()[-1])
print(json.dumps({"id": i, "opt_best": p["best_objective"], "scores": {k: v["mean"] for k, v in d["scores"].items()},
                  "T1_std": d["scores"]["T1.formant_rel_error"]["std"], "context": c["context_formant_rel_error"]["mean"],
                  "context_failures": c["measure_failures"]}, ensure_ascii=False))
EOF
