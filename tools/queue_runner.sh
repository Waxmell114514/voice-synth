#!/usr/bin/env bash
# 单一顺序队列（避免多个等待循环同时运行）。reports/queue.txt 每行：<worktree> <id> <parent_params> [mode]
# mode = tune（默认，branch_pipeline）或 enabler（enabler_eval，不调参）。处理过的行改写为 "# done ..."。遇到 END 行退出。
M="$(cd "$(dirname "$0")/.." && pwd)"; Q="$M/reports/queue.txt"; touch "$Q"
while true; do
  line=$(grep -v '^#' "$Q" | grep -v '^$' | head -1)
  if [ -z "$line" ]; then sleep 20; continue; fi
  [ "$line" = "END" ] && { sed -i 's/^END$/# done END/' "$Q"; exit 0; }
  set -- $line; WT=$1; ID=$2; PRM=$3; MODE=${4:-tune}
  git -C "$WT" update-index --assume-unchanged ledger/eval_calls.jsonl 2>/dev/null
  echo "$(date +%H:%M) start $ID ($MODE)"
  if [ "$MODE" = enabler ]; then "$M/tools/enabler_eval.sh" "$WT" "$ID" "$PRM" 2>&1 | tail -1
  else (cd "$WT" && PARENT="$PRM" "$M/tools/branch_pipeline.sh" "$WT" "$ID" 2>&1 | tail -1
        python3 "$M/tools/plausibility.py" "params/$ID.json" > "$M/reports/evals/$ID.plaus.json" 2>/dev/null
        python3 "$M/tools/dynamic_t0_check.py" "params/$ID.json" > "$M/reports/evals/$ID.dynamic.json" 2>/dev/null); fi
  echo "$(date +%H:%M) done $ID"
  sed -i "0,/^$(printf '%s' "$line" | sed 's/[\/&]/\\&/g')\$/s//# done &/" "$Q"
done
