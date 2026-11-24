"""账本与种群工具。

  python tools/ledger.py append '<json>'        # 追加一条（校验必填字段；只追加）
  python tools/ledger.py show [N]               # 最近 N 条
  python tools/ledger.py population             # 打印 reports/population.json

种群：reports/population.json，[{id, params, scores{metric: mean}}]；按 Pareto 前沿保留
config.generation.population_size 个（目标方向见 DIRECTION）。
"""
import os, sys, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(REPO, "ledger", "experiments.jsonl")
POP = os.path.join(REPO, "reports", "population.json")
REQUIRED = ["id", "parent", "milestone", "hypothesis", "prediction", "touched_modules", "new_params", "verdict"]
DIRECTION = {"T1.formant_rel_error": -1, "T2.syllable_acc": 1, "T2.tone_acc": 1, "T3.cer": -1,
             "T3.pinyin_err": -1, "T4.composite": 1}


def append(rec):
    miss = [k for k in REQUIRED if k not in rec]
    if miss:
        raise SystemExit(f"missing fields: {miss}")
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def records():
    if not os.path.exists(LEDGER):
        return []
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]


def dominates(a, b, keys):
    ge = all(DIRECTION[k] * (a[k] - b[k]) >= 0 for k in keys)
    gt = any(DIRECTION[k] * (a[k] - b[k]) > 0 for k in keys)
    return ge and gt


def update_population(new, size, primary):
    pop = json.load(open(POP)) if os.path.exists(POP) else []
    pop = [p for p in pop if p["id"] != new["id"]] + [new]
    keys = sorted({k for p in pop for k in p["scores"] if k in DIRECTION and all(k in q["scores"] for q in pop)})
    front = [p for p in pop if not any(dominates(q["scores"], p["scores"], keys) for q in pop if q is not p)]
    rest = [p for p in pop if p not in front]
    key = lambda p: -DIRECTION[primary] * p["scores"].get(primary, 0)
    keep = sorted(front, key=key)[:size]
    keep += sorted(rest, key=key)[: max(0, size - len(keep))]
    json.dump(keep, open(POP, "w"), ensure_ascii=False, indent=1)
    return keep


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "append":
        append(json.loads(sys.argv[2]))
    elif cmd == "show":
        for r in records()[-int(sys.argv[2] if len(sys.argv) > 2 else 10):]:
            print(json.dumps(r, ensure_ascii=False))
    elif cmd == "population":
        print(open(POP).read() if os.path.exists(POP) else "[]")
