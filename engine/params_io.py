"""读参数文件，按 params/schema.json 补默认值并裁剪到取值范围。"""
import os, json
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "params", "schema.json")


def load_schema():
    return json.load(open(SCHEMA, encoding="utf-8"))


def load_params(path):
    sch = load_schema()
    vals = json.load(open(path, encoding="utf-8")).get("values", {})
    P = {}
    for p in sch["params"]:
        v = vals.get(p["name"], p["default"])
        v = np.clip(np.asarray(v, dtype=float), p["min"], p["max"])
        shape = tuple(p.get("shape", []))
        if shape and v.shape != shape:
            v = np.broadcast_to(v, shape).copy() if v.ndim == 0 else np.interp(
                np.linspace(0, 1, shape[0]), np.linspace(0, 1, len(v)), v)
        P[p["name"]] = v if shape else float(v)
    return P
