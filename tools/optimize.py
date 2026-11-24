"""数值优化器（CMA-ES，固定预算）。唯一可以写 params/ 的程序。

  python tools/optimize.py --parent params/g0.json --out params/g001-e01.json --milestone M1 [--budget 150]

搜索空间：只含 params/schema.json 中已声明的参数。
  - 数组参数（面积函数）用对数面积上的低阶余弦模态扰动：log A' = log A + Σ_m c_m cos(π m x)，
    m = 0..K-1；优化的是 c_m，写回的是 A'（仍是已声明参数，并裁剪到其范围）。
  - 标量参数在 [min, max] 上线性归一化到 [0,1]。
目标函数：当前里程碑的主指标（开发集固定子集 --set opt，seed 0），前序里程碑指标作罚项。
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


def objective_fn(milestone, tiers):
    import run as RUN

    def f(vals, tmpdir):
        pth = os.path.join(tmpdir, "cand.json")
        json.dump({"values": vals}, open(pth, "w"))
        summ, _ = RUN.evaluate("engine", pth, tiers, "opt", "dev", [0])
        if milestone == "M1":
            return summ["T1.formant_rel_error"]["mean"], {k: v["mean"] for k, v in summ.items()}
        raise NotImplementedError(milestone)
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--milestone", default="M1")
    ap.add_argument("--budget", type=int, default=None)
    ap.add_argument("--sigma", type=float, default=0.15)
    a = ap.parse_args()
    import yaml, cma
    cfg = yaml.safe_load(open(os.path.join(REPO, "config.yaml")))
    budget = a.budget or cfg["optimizer"]["evals_per_variant"]
    schema = load(os.path.join(REPO, "params", "schema.json"))
    par = load(a.parent)
    vals = {p["name"]: par["values"].get(p["name"], p["default"]) for p in schema["params"]}
    tgt = TARGETS[a.milestone]
    sp = Space(schema, vals, tgt["arrays"], tgt["scalars"])
    f = objective_fn(a.milestone, tgt["tiers"])
    tmp = tempfile.mkdtemp(prefix="opt_")
    t0 = time.time()
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
