"""数值优化器（CMA-ES，固定预算）。唯一可以写 params/ 的程序。

  python tools/optimize.py --parent params/g0.json --out params/g001-e01.json --milestone M1 [--budget 150]

搜索空间：只含 params/schema.json 中已声明的参数。
  - 数组参数（面积函数）用对数面积上的低阶余弦模态扰动：log A' = log A + Σ_m c_m cos(π m x)，
    m = 0..K-1；优化的是 c_m，写回的是 A'（仍是已声明参数，并裁剪到其范围）。
  - 标量参数在 [min, max] 上线性归一化到 [0,1]。
另外，schema 条目若声明 "tune": ["M1"]，自动加入该里程碑的搜索空间。
目标函数（2026-11-24 起，提案 004-A）：T1 + plausibility.LAMBDA × 生理罚项；此前为当前里程碑的主指标（开发集固定子集 --set opt，seed 0），前序里程碑指标作罚项。
"""
import os, sys, json, time, argparse, tempfile, copy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "eval"))

# 各里程碑调哪些参数（结构不变，只调数值）
TARGETS = {
    "M1": {"arrays": ["area_a", "area_o", "area_e", "area_i", "area_u", "area_v"],
           "scalars": ["tract_length_cm", "r_lip", "r_glottis", "wall_loss"], "tiers": ["T1"]},
}
K_MODES = 6
VOWELS = ["a", "o", "e", "i", "u", "v"]


def load(p):
    return json.load(open(p, encoding="utf-8"))


class Space:
    def __init__(self, schema, parent_vals, arrays, scalars):
        self.sch = {p["name"]: p for p in schema["params"]}
        self.base = parent_vals
        self.arrays = [a for a in arrays if a in self.sch]
        self.scalars = [s for s in scalars if s in self.sch]
        self.dim = len(self.arrays) * K_MODES + len(self.scalars)

    def x0(self):
        xs = []
        for s in self.scalars:
            p = self.sch[s]
            xs.append((float(self.base[s]) - p["min"]) / (p["max"] - p["min"]))
        return np.concatenate([np.zeros(len(self.arrays) * K_MODES), np.array(xs)])

    def decode(self, x):
        v = copy.deepcopy(self.base)
        i = 0
        for a in self.arrays:
            p = self.sch[a]
            A = np.asarray(self.base[a], float)
            n = len(A)
            xx = np.linspace(0, 1, n)
            d = sum(x[i + m] * np.cos(np.pi * m * xx) for m in range(K_MODES))
            v[a] = np.clip(np.exp(np.log(A) + d), p["min"], p["max"]).round(5).tolist()
            i += K_MODES
        for s in self.scalars:
            p = self.sch[s]
            v[s] = float(np.clip(p["min"] + x[i] * (p["max"] - p["min"]), p["min"], p["max"]))
            i += 1
        return v


def objective_fn(milestone, tiers, with_diag=False):
    import run as RUN
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import plausibility as PL   # 提案 004-A：目标 = T1 + LAMBDA × 生理罚项

    def f(vals, tmpdir):
        if with_diag:
            pth = os.path.join(tmpdir, "cand.json")
            json.dump({"values": vals}, open(pth, "w"))
            summ, diags = RUN.evaluate("engine", pth, tiers, "opt", "dev", [0])
            pen, per_pen, _ = PL.penalty(vals)
            per = {v: float(np.mean(e)) + PL.LAMBDA * per_pen.get(v, 0.0)
                   for v, e in diags["T1.per_vowel_rel_error_F1F2F3"].items()}
            return summ["T1.formant_rel_error"]["mean"] + PL.LAMBDA * pen, per
        pth = os.path.join(tmpdir, "cand.json")
        json.dump({"values": vals}, open(pth, "w"))
        summ, _ = RUN.evaluate("engine", pth, tiers, "opt", "dev", [0])
        if milestone == "M1":
            return summ["T1.formant_rel_error"]["mean"] + PL.LAMBDA * PL.penalty(vals)[0], {k: v["mean"] for k, v in summ.items()}
        raise NotImplementedError(milestone)
    return f


def separable_m1(sp, f_full, budget, sigma, tmp, seed=1):
    """M1 可分搜索：T1 = 各元音偏差之和，每个元音的共振峰基本只取决于自己的参数。
    分块：元音 v 的块 = area_v 的余弦模态 + schema 中标了 "vowel": v 的标量；其余全部进共用块。
    每块一个 CMA-ES；每次评估同时喂给全部搜索器（元音块用该元音的偏差，共用块用总偏差）。总评估次数不变。"""
    import cma
    x0 = sp.x0()
    blocks = {}
    i = 0
    for a in sp.arrays:
        v = a[5:] if a.startswith("area_") and a[5:] in VOWELS else None
        blocks.setdefault(v, []).extend(range(i, i + K_MODES)); i += K_MODES
    for s_ in sp.scalars:
        v = sp.sch[s_].get("vowel")
        blocks.setdefault(v if v in VOWELS else None, []).append(i); i += 1
    keys = [v for v in VOWELS if v in blocks] + ([None] if None in blocks else [])
    pop = 8
    ess = {k: cma.CMAEvolutionStrategy(x0[blocks[k]], sigma, {"seed": seed * 100 + j, "verbose": -9, "popsize": pop})
           for j, k in enumerate(keys)}
    best = (np.inf, None, 0); n = 0; trace = []
    while n + pop <= budget:
        X = {k: ess[k].ask() for k in keys}
        F = {k: [] for k in keys}
        tots = []
        for j in range(pop):
            x = np.array(x0, dtype=float)
            for k in keys:
                x[blocks[k]] = X[k][j]
            v = sp.decode(x)
            tot, per = f_full(v, tmp); n += 1
            for k in keys:
                F[k].append(tot if k is None else float(per[k]))
            tots.append(tot)
            if tot < best[0]:
                best = (tot, v, n)
        for k in keys:
            ess[k].tell(X[k], F[k])
        trace.append(round(min(tots), 5))
        print(f"[opt-sep] evals {n}/{budget} gen-best {min(tots):.4f} best {best[0]:.4f}", file=sys.stderr, flush=True)
    return best, n, trace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--milestone", default="M1")
    ap.add_argument("--budget", type=int, default=None)
    ap.add_argument("--sigma", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=1, help="单种子模式的随机种子")
    ap.add_argument("--seeds", default=None,
                    help="多种子模式（提案 002-A）：例如 1,2,3；每个种子各用 budget/种子数 次，结果取中位数那次")
    ap.add_argument("--mode", default="separable", choices=["separable", "joint"],
                    help="M1 默认用可分搜索（2026-11-24 起；此前 g001-e00、g001-e00r 用 joint）")
    a = ap.parse_args()
    import yaml, cma
    cfg = yaml.safe_load(open(os.path.join(REPO, "config.yaml")))
    budget = a.budget or cfg["optimizer"]["evals_per_variant"]
    schema = load(os.path.join(REPO, "params", "schema.json"))
    par = load(a.parent)
    vals = {p["name"]: par["values"].get(p["name"], p["default"]) for p in schema["params"]}
    tgt = TARGETS[a.milestone]
    # schema 条目可声明 "tune": ["M1", ...]，自动纳入该里程碑的搜索空间（新机制的参数与对照组同等调参）
    extra = [p for p in schema["params"] if a.milestone in p.get("tune", [])]
    arrays = tgt["arrays"] + [p["name"] for p in extra if p["shape"] and p["name"] not in tgt["arrays"]]
    scalars = tgt["scalars"] + [p["name"] for p in extra if not p["shape"] and p["name"] not in tgt["scalars"]]
    inactive = {p["name"] for p in schema["params"] if p.get("inactive")}   # 被新机制取代、不再起作用的参数不调
    arrays = [x for x in arrays if x not in inactive]
    scalars = [x for x in scalars if x not in inactive]
    sp = Space(schema, vals, arrays, scalars)
    f = objective_fn(a.milestone, tgt["tiers"])
    tmp = tempfile.mkdtemp(prefix="opt_")
    t0 = time.time()
    if a.seeds:
        seeds = [int(x) for x in a.seeds.split(",")]
        per = budget // len(seeds)
        runs = []
        for sd in seeds:
            o = a.out + f".seed{sd}.json"
            cmd = [sys.executable, __file__, "--parent", a.parent, "--out", o, "--milestone", a.milestone,
                   "--budget", str(per), "--seed", str(sd), "--mode", a.mode, "--sigma", str(a.sigma)]
            import subprocess
            subprocess.run(cmd, check=True)
            runs.append((json.load(open(o)), o))
        runs.sort(key=lambda r: r[0]["optimizer"]["best_objective"])
        med, med_path = runs[len(runs) // 2]
        out = dict(med)
        out["version"] = os.path.splitext(os.path.basename(a.out))[0]
        out["optimizer"] = dict(med["optimizer"], protocol="002-A multi-seed median", seeds=seeds,
                                per_seed_best={r[0]["optimizer"]["seed"]: r[0]["optimizer"]["best_objective"] for r in runs},
                                chosen_seed=med["optimizer"]["seed"], total_evals=sum(r[0]["optimizer"]["evals"] for r in runs))
        json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
        for _, o in runs:
            os.remove(o)
        print(json.dumps(out["optimizer"]))
        return
    if a.milestone == "M1" and a.mode == "separable":
        fd = objective_fn(a.milestone, tgt["tiers"], with_diag=True)
        f0, _ = fd(vals, tmp)
        (bf, bv, bat), n, trace = separable_m1(sp, fd, budget - 1, a.sigma, tmp, a.seed)
        n += 1
        if f0 <= bf:
            bf, bv, bat = f0, vals, 1
        out = {"version": os.path.splitext(os.path.basename(a.out))[0], "parent": os.path.basename(a.parent),
               "optimizer": {"method": "cma-es", "mode": "separable", "milestone": a.milestone, "evals": n, "seed": a.seed,
                             "budget": budget, "start_objective": f0, "best_objective": bf, "best_at_eval": bat,
                             "dims": sp.dim, "trace_gen_best": [round(f0, 5)] + trace,
                             "wall_min": round((time.time() - t0) / 60, 1)},
               "values": bv}
        json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
        print(json.dumps(out["optimizer"]))
        return
    f0, _ = f(vals, tmp)
    best = (f0, vals, 0)
    trace = [round(f0, 5)]
    es = cma.CMAEvolutionStrategy(sp.x0(), a.sigma, {"seed": 1, "verbose": -9, "maxfevals": budget - 1,
                                                     "bounds": [None, None]})
    n = 1
    while not es.stop() and n < budget:
        X = es.ask()
        X = X[: max(1, min(len(X), budget - n))]
        F = []
        for x in X:
            v = sp.decode(np.asarray(x))
            fx, _ = f(v, tmp)
            F.append(fx); n += 1
            if fx < best[0]:
                best = (fx, v, n)
        if len(X) == es.popsize:
            es.tell(X, F)
        else:
            break
        trace.append(round(min(F), 5))
        print(f"[opt] evals {n}/{budget} gen-best {min(F):.4f} best {best[0]:.4f}", file=sys.stderr, flush=True)
    out = {"version": os.path.splitext(os.path.basename(a.out))[0], "parent": os.path.basename(a.parent),
           "optimizer": {"method": "cma-es", "milestone": a.milestone, "evals": n, "budget": budget,
                         "start_objective": f0, "best_objective": best[0], "best_at_eval": best[2],
                         "dims": sp.dim, "trace_gen_best": trace, "wall_min": round((time.time() - t0) / 60, 1)},
           "values": best[1]}
    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out["optimizer"]))


if __name__ == "__main__":
    main()
