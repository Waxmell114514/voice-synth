"""M1 可行性判定（提案 005-1B、005-2B，人决定）。优化器、Critic 和流水线共用。

  python tools/m1_feasible.py params/x.json [--milestone M1]   # 打印罚项、贴边明细与是否可行

可行 = 罚项 < plausibility.ACCEPT_MAX 且没有调参参数贴边。

贴边（005-1B）：
  - 只看调参参数，即本次搜索中的参数：tools/optimize.py 的 TARGETS[里程碑] 加上 schema 中 "tune" 含该里程碑的条目，
    去掉标了 "inactive" 的、带 "anneal_to" 的（连续化参数是事先固定的值，不在搜索中）。
  - 任一元素与 min 或 max 的距离 ≤ BOUND_TOL × (max − min) 即贴边（数组逐元素看）。
  - 物理极限不算贴边：名字以 r_ 开头的反射系数，在 |r| 接近 1 的那一端（|边界值| ≥ 1 − R_PHYS_TOL）不算。
    另一端（例如 r_lip 的 min = 0.5）仍然算。
"""
import os, sys, json
import numpy as np

BOUND_TOL = 1e-3
R_PHYS_TOL = 0.01


def search_names(schema, milestone="M1"):
    """本次搜索中的参数名（与 tools/optimize.py 的搜索空间同一规则）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from optimize import search_lists
    arrays, scalars, _ = search_lists(schema, milestone)
    return arrays + scalars


def _phys_limit(name, bound):
    return name.startswith("r_") and abs(float(bound)) >= 1.0 - R_PHYS_TOL


def bound_hits(vals, schema, names):
    """返回贴边明细 {name: [(元素序号或 None, "min"/"max"), ...]}；空字典表示不贴边。"""
    sch = {p["name"]: p for p in schema["params"]}
    hits = {}
    for nm in names:
        p = sch[nm]
        lo, hi = float(p["min"]), float(p["max"])
        tol = BOUND_TOL * (hi - lo)
        x = np.atleast_1d(np.asarray(vals[nm], float))
        arr = bool(p.get("shape"))
        h = []
        if not _phys_limit(nm, lo):
            h += [(int(i) if arr else None, "min") for i in np.nonzero(x - lo <= tol)[0]]
        if not _phys_limit(nm, hi):
            h += [(int(i) if arr else None, "max") for i in np.nonzero(hi - x <= tol)[0]]
        if h:
            hits[nm] = h
    return hits


def at_bound(vals, schema, names):
    return bool(bound_hits(vals, schema, names))


def is_feasible(penalty, at_bound_flag):
    import plausibility as PL
    return bool(penalty < PL.ACCEPT_MAX and not at_bound_flag)


def main():
    import argparse
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import plausibility as PL
    ap = argparse.ArgumentParser()
    ap.add_argument("params")
    ap.add_argument("--milestone", default="M1")
    a = ap.parse_args()
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(repo, "params", "schema.json"), encoding="utf-8"))
    pv = json.load(open(a.params, encoding="utf-8"))["values"]
    vals = {p["name"]: pv.get(p["name"], p["default"]) for p in schema["params"]}
    names = search_names(schema, a.milestone)
    pen = PL.penalty(vals, a.params)[0]
    hits = bound_hits(vals, schema, names)
    print(json.dumps({"penalty": round(pen, 5), "accept_max": PL.ACCEPT_MAX, "at_bound": bool(hits),
                      "bound_hits": {k: [f"{'' if i is None else i}:{s}" for i, s in v] for k, v in hits.items()},
                      "feasible": is_feasible(pen, bool(hits)), "checked_params": names},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
