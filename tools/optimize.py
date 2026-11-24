"""数值优化器（CMA-ES，固定预算）。唯一可以写 params/ 的程序。

  python tools/optimize.py --parent params/g0.json --out params/g001-e01.json --milestone M1 [--budget 150]

搜索空间：只含 params/schema.json 中已声明的参数。
  - 数组参数（面积函数）用对数面积上的低阶余弦模态扰动：log A' = log A + Σ_m c_m cos(π m x)，
    m = 0..K-1；优化的是 c_m，写回的是 A'（仍是已声明参数，并裁剪到其范围）。
  - 标量参数在 [min, max] 上线性归一化到 [0,1]。
另外，schema 条目若声明 "tune": ["M1"]，自动加入该里程碑的搜索空间。
目标函数（2026-11-24 起，提案 004-A）：T1 + plausibility.LAMBDA × 生理罚项；此前为当前里程碑的主指标（开发集固定子集 --set opt，seed 0），前序里程碑指标作罚项。
选解（2026-11-24 起，提案 005-2B）：搜索仍用上面的目标函数，只改“最后选哪个点”。每次评估记录 T1、罚项、是否贴边
  （贴边规则见 tools/m1_feasible.py，005-1B）。每个种子在“罚项 < plausibility.ACCEPT_MAX 且不贴边”的评估点里选 T1 最好的；
  一个可行点都没有时退回目标函数最好的点，输出标 "feasible": false。多种子取中位数时，可行的排在不可行的前面，
  可行的按 T1 排，不可行的按目标函数排。
连续化（specs/g003-e03.md §2、specs/g003-e06.md §6.2）：schema 条目可声明 "anneal_to": 目标值 p1（标量，不得带 tune，不进搜索空间）。
  每个种子 G = ⌊(B−1)/popsize⌋ 代，Gr = ⌊G/2⌋；第 g 代全部个体取 p(g) = p0 + (p1 − p0)·min(1, (g+1)/Gr)，p0 为父版本值。
  第 1 次评估用“父版本其余参数 + p1”（start_objective_at_target），参与选解；之后只在 g ≥ Gr 的代里选解；
  不回退到父版本；切换点不重置 σ 与协方差。schema 中没有 anneal_to 时，搜索路径与改动前逐位相同。
输出：stdout 一行 JSON（optimizer 字段）。多种子时每个种子先各打印一行（"official": false），最后一行是正式结果（"official": true）。
"""
import os, sys, json, time, argparse, tempfile, copy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "eval"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 各里程碑调哪些参数（结构不变，只调数值）
TARGETS = {
    "M1": {"arrays": ["area_a", "area_o", "area_e", "area_i", "area_u", "area_v"],
           "scalars": ["tract_length_cm", "r_lip", "r_glottis", "wall_loss"], "tiers": ["T1"]},
}
K_MODES = 6
VOWELS = ["a", "o", "e", "i", "u", "v"]


def load(p):
    return json.load(open(p, encoding="utf-8"))


def search_lists(schema, milestone):
    """搜索空间（数组名、标量名，顺序固定）与连续化参数 {name: 目标值}。tools/m1_feasible.py 也用它判定“调参参数”。"""
    tgt = TARGETS[milestone]
    # schema 条目可声明 "tune": ["M1", ...]，自动纳入该里程碑的搜索空间（新机制的参数与对照组同等调参）
    extra = [p for p in schema["params"] if milestone in p.get("tune", [])]
    arrays = tgt["arrays"] + [p["name"] for p in extra if p["shape"] and p["name"] not in tgt["arrays"]]
    scalars = tgt["scalars"] + [p["name"] for p in extra if not p["shape"] and p["name"] not in tgt["scalars"]]
    inactive = {p["name"] for p in schema["params"] if p.get("inactive")}   # 被新机制取代、不再起作用的参数不调
    arrays = [x for x in arrays if x not in inactive]
    scalars = [x for x in scalars if x not in inactive]
    anneal = {}
    for p in schema["params"]:
        if "anneal_to" not in p:
            continue
        nm, to = p["name"], float(p["anneal_to"])
        assert not p.get("tune"), f"{nm}: anneal_to 与 tune 不能同时出现"
        assert not p["shape"], f"{nm}: anneal_to 只用于标量"
        assert p["min"] <= to <= p["max"], f"{nm}: anneal_to={to} 不在 [{p['min']}, {p['max']}]"
        assert nm not in tgt["arrays"] + tgt["scalars"], f"{nm}: anneal_to 参数不得在 TARGETS 中"
        anneal[nm] = to
    return arrays, scalars, anneal


def anneal_schedule(anneal, base, G):
    """每代的连续化取值 {name: [p(0..G-1)]} 与 Gr。Gr = 0（预算太小）时全部代都取目标值。"""
    Gr = G // 2
    sched = {}
    for nm, p1 in anneal.items():
        p0 = float(base[nm])
        # g + 1 ≥ Gr 时直接取 p1（避免 p0 + (p1 − p0) 与 p1 差一个舍入单位，使固定阶段与第 1 次评估的取值逐位相同）
        sched[nm] = [p0 + (p1 - p0) * (g + 1) / Gr if g + 1 < Gr else p1 for g in range(G)]
    return sched, Gr


class EvalLog:
    """每次评估的记录（提案 005-2B）：序号、目标、T1、罚项、是否贴边、是否参与选解。"""

    def __init__(self, schema, names):
        import m1_feasible as MF
        self.MF, self.schema, self.names = MF, schema, names
        self.rows = []

    def add(self, v, obj, f, eligible=True):
        hits = self.MF.bound_hits(v, self.schema, self.names)
        self.rows.append({"n": len(self.rows) + 1, "obj": obj, "T1": f.last["T1"], "pen": f.last["pen"],
                          "at_bound": bool(hits), "hits": hits, "eligible": eligible, "values": v})

    def select(self):
        """返回 (选中的行, 是否可行, 目标函数最好的行)。并列时取最早的一次。"""
        cand = [r for r in self.rows if r["eligible"]]
        unc = min(cand, key=lambda r: (r["obj"], r["n"]))
        feas = [r for r in cand if self.MF.is_feasible(r["pen"], r["at_bound"])]
        if feas:
            return min(feas, key=lambda r: (r["T1"], r["n"])), True, unc
        return unc, False, unc

    def summary(self):
        ch, ok, unc = self.select()
        row = lambda r: {"at_eval": r["n"], "objective": r["obj"], "T1": r["T1"], "penalty": r["pen"],
                         "at_bound": r["at_bound"]}
        sel = dict(row(ch), rule="005-2B" if ok else "fallback: T1 + LAMBDA*penalty", feasible=ok,
                   n_feasible=sum(1 for r in self.rows if r["eligible"] and self.MF.is_feasible(r["pen"], r["at_bound"])),
                   n_candidates=sum(1 for r in self.rows if r["eligible"]),
                   bound_hits={k: [f"{'' if i is None else i}:{b}" for i, b in h] for k, h in ch["hits"].items()})
        log = [[r["n"], r["obj"], r["T1"], r["pen"], int(r["at_bound"]), int(r["eligible"])] for r in self.rows]
        return ch, ok, {"feasible": ok, "selected": sel, "unconstrained_best": row(unc),
                        "eval_log_columns": ["n", "objective", "T1", "penalty", "at_bound", "eligible"], "eval_log": log}


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
        # f.last 记录本次评估的 T1 与罚项（提案 005-2B 选解用）；目标函数的算式与改动前相同
        if with_diag:
            pth = os.path.join(tmpdir, "cand.json")
            json.dump({"values": vals}, open(pth, "w"))
            summ, diags = RUN.evaluate("engine", pth, tiers, "opt", "dev", [0])
            pen, per_pen, _ = PL.penalty(vals, pth)
            per = {v: float(np.mean(e)) + PL.LAMBDA * per_pen.get(v, 0.0)
                   for v, e in diags["T1.per_vowel_rel_error_F1F2F3"].items()}
            t1 = summ["T1.formant_rel_error"]["mean"]
            f.last = {"T1": t1, "pen": pen}
            return t1 + PL.LAMBDA * pen, per
        pth = os.path.join(tmpdir, "cand.json")
        json.dump({"values": vals}, open(pth, "w"))
        summ, _ = RUN.evaluate("engine", pth, tiers, "opt", "dev", [0])
        if milestone == "M1":
            t1, pen = summ["T1.formant_rel_error"]["mean"], PL.penalty(vals)[0]
            f.last = {"T1": t1, "pen": pen}
            return t1 + PL.LAMBDA * pen, {k: v["mean"] for k, v in summ.items()}
        raise NotImplementedError(milestone)
    f.last = None
    return f


def separable_m1(sp, f_full, budget, sigma, tmp, seed=1, log=None, anneal=None):
    """M1 可分搜索：T1 = 各元音偏差之和，每个元音的共振峰基本只取决于自己的参数。
    分块：元音 v 的块 = area_v 的余弦模态 + schema 中标了 "vowel": v 的标量；其余全部进共用块。
    每块一个 CMA-ES；每次评估同时喂给全部搜索器（元音块用该元音的偏差，共用块用总偏差）。总评估次数不变。
    log：EvalLog，记录每次评估。anneal：{name: 目标值}，非空时按代连续化（见文件头）；为空时搜索路径与改动前相同。"""
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
    info = {}
    if anneal:
        G = budget // pop
        sched, Gr = anneal_schedule(anneal, sp.base, G)
        info = {"G": G, "Gr": Gr, "sched": sched, "sigma_trace": [], "first_fixed_gen_best": None}
    best = (np.inf, None, 0); n = 0; trace = []; g = 0
    while n + pop <= budget:
        fixed = (not anneal) or g >= info["Gr"]
        X = {k: ess[k].ask() for k in keys}
        F = {k: [] for k in keys}
        tots = []
        for j in range(pop):
            x = np.array(x0, dtype=float)
            for k in keys:
                x[blocks[k]] = X[k][j]
            v = sp.decode(x)
            if anneal:
                for nm in anneal:
                    v[nm] = info["sched"][nm][g]
            tot, per = f_full(v, tmp); n += 1
            if log is not None:
                log.add(v, tot, f_full, eligible=fixed)
            for k in keys:
                F[k].append(tot if k is None else float(per[k]))
            tots.append(tot)
            if fixed and tot < best[0]:
                best = (tot, v, n)
        for k in keys:
            ess[k].tell(X[k], F[k])
        trace.append(round(min(tots), 5))
        if anneal:
            info["sigma_trace"].append({("shared" if k is None else k): round(float(ess[k].sigma), 6) for k in keys})
            if g == info["Gr"]:
                info["first_fixed_gen_best"] = min(tots)
        g += 1
        print(f"[opt-sep] evals {n}/{budget} gen-best {min(tots):.4f} best {best[0]:.4f}", file=sys.stderr, flush=True)
    return best, n, trace, info


def anneal_out(anneal, base, info):
    """输出 JSON 中的 anneal 字段（兼顾 g003-e03 §2.3 与 g003-e06 §6.2 第 7 条的字段名）。"""
    return {nm: {"to": p1, "p0": float(base[nm]), "p1": p1, "schedule": [round(x, 6) for x in info["sched"][nm]],
                 "G_ramp": info["Gr"], "Gr": info["Gr"], "G": info["G"]} for nm, p1 in anneal.items()}


def seed_rank(o):
    """多种子取中位数的排序键（提案 005-2B）：可行的在前（按 T1），不可行的在后（按 T1 + LAMBDA × 罚项）。"""
    if "selected" not in o:            # 旧格式输出
        return (0, o["best_objective"])
    return (0, o["selected"]["T1"]) if o["feasible"] else (1, o["selected"]["objective"])


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
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)   # 多种子模式的子进程：输出行标 official=false
    a = ap.parse_args()
    import yaml, cma
    cfg = yaml.safe_load(open(os.path.join(REPO, "config.yaml")))
    budget = a.budget or cfg["optimizer"]["evals_per_variant"]
    schema = load(os.path.join(REPO, "params", "schema.json"))
    par = load(a.parent)
    vals = {p["name"]: par["values"].get(p["name"], p["default"]) for p in schema["params"]}
    tgt = TARGETS[a.milestone]
    arrays, scalars, anneal = search_lists(schema, a.milestone)
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
                   "--budget", str(per), "--seed", str(sd), "--mode", a.mode, "--sigma", str(a.sigma), "--child"]
            import subprocess
            subprocess.run(cmd, check=True)
            runs.append((json.load(open(o)), o))
        runs.sort(key=lambda r: seed_rank(r[0]["optimizer"]))
        med, med_path = runs[len(runs) // 2]
        out = dict(med)
        out["version"] = os.path.splitext(os.path.basename(a.out))[0]
        per_seed = {}
        for r, _ in runs:
            q = r["optimizer"]
            sel = q.get("selected", {})
            per_seed[q["seed"]] = {"feasible": q.get("feasible"), "T1": sel.get("T1"), "penalty": sel.get("penalty"),
                                   "at_bound": sel.get("at_bound"), "objective": q["best_objective"],
                                   "unconstrained_best_objective": q.get("unconstrained_best", {}).get("objective")}
        out["optimizer"] = dict(med["optimizer"], protocol="002-A multi-seed median", seeds=seeds,
                                per_seed_best={r[0]["optimizer"]["seed"]: r[0]["optimizer"]["best_objective"] for r in runs},
                                per_seed=per_seed,
                                median_rule="005-2B: feasible first (by T1), then infeasible (by T1 + LAMBDA*penalty)",
                                chosen_seed=med["optimizer"]["seed"], total_evals=sum(r[0]["optimizer"]["evals"] for r in runs),
                                official=True)
        json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
        for _, o in runs:
            os.remove(o)
        print(json.dumps(out["optimizer"]))
        return
    log = EvalLog(schema, arrays + scalars)
    v_start = dict(vals, **anneal) if anneal else vals    # 有连续化时第 1 次评估 = 父版本其余参数 + 目标值
    if a.milestone == "M1" and a.mode == "separable":
        fd = objective_fn(a.milestone, tgt["tiers"], with_diag=True)
        f0, _ = fd(v_start, tmp)
        log.add(v_start, f0, fd)
        _, n, trace, info = separable_m1(sp, fd, budget - 1, a.sigma, tmp, a.seed, log, anneal)
        n += 1
        opt = {"method": "cma-es", "mode": "separable", "milestone": a.milestone, "evals": n, "seed": a.seed,
               "budget": budget, "start_objective": f0}
        trace = [round(f0, 5)] + trace
    else:
        f0, _ = f(v_start, tmp)
        log.add(v_start, f0, f)
        trace = [round(f0, 5)]
        # 种子用 --seed（此前写死为 1，多种子时三次结果相同）
        es = cma.CMAEvolutionStrategy(sp.x0(), a.sigma, {"seed": a.seed, "verbose": -9, "maxfevals": budget - 1,
                                                         "bounds": [None, None]})
        info = {}
        if anneal:
            G = (budget - 1) // es.popsize
            sched, Gr = anneal_schedule(anneal, vals, G)
            info = {"G": G, "Gr": Gr, "sched": sched, "sigma_trace": [], "first_fixed_gen_best": None}
        n = 1; g = 0
        while not es.stop() and n < budget:
            if anneal and g >= info["G"]:
                break
            X = es.ask()
            X = X[: max(1, min(len(X), budget - n))]
            F = []
            for x in X:
                v = sp.decode(np.asarray(x))
                if anneal:
                    for nm in anneal:
                        v[nm] = info["sched"][nm][g]
                fx, _ = f(v, tmp)
                log.add(v, fx, f, eligible=(not anneal) or g >= info["Gr"])
                F.append(fx); n += 1
            if len(X) == es.popsize:
                es.tell(X, F)
            else:
                break
            trace.append(round(min(F), 5))
            if anneal:
                info["sigma_trace"].append(round(float(es.sigma), 6))
                if g == info["Gr"]:
                    info["first_fixed_gen_best"] = min(F)
            g += 1
            print(f"[opt] evals {n}/{budget} gen-best {min(F):.4f}", file=sys.stderr, flush=True)
        opt = {"method": "cma-es", "mode": "joint", "milestone": a.milestone, "evals": n, "seed": a.seed,
               "budget": budget, "start_objective": f0}
    ch, ok, summ = log.summary()
    opt.update({"best_objective": ch["obj"], "best_at_eval": ch["n"], "dims": sp.dim, "trace_gen_best": trace})
    if anneal:
        opt.update({"anneal": anneal_out(anneal, vals, info), "start_objective_at_target": f0,
                    "first_fixed_gen_best": info["first_fixed_gen_best"], "sigma_trace": info["sigma_trace"],
                    "fallback_to_parent": False})
    opt.update(summ)
    opt.update({"wall_min": round((time.time() - t0) / 60, 1), "official": not a.child})
    out = {"version": os.path.splitext(os.path.basename(a.out))[0], "parent": os.path.basename(a.parent),
           "optimizer": opt, "values": ch["values"]}
    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out["optimizer"]))


if __name__ == "__main__":
    main()
