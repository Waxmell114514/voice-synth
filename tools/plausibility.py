"""元音面积函数的生理合理性罚项（提案 004-A，人批准）。优化器和 Critic 共用。

  python tools/plausibility.py params/x.json      # 打印总罚项、各元音罚项和超界明细

边界出处见 specs/g002-e01.md（Story, Titze & Hoffman 1998 女声 MRI）：
  任一段面积软上限 6.5 cm²（硬上限 9，写在 schema）；咽腔（声门端 1/2 以内，不含最初 2 段喉部）最小面积 ≥ 0.15 cm²；
  唇口（最后一段）面积：u、ü 0.08–0.6；o 0.3–1.5；a 2–5.5；e、i 1–3.5。
罚项 = 各项“对数超界量”的平方之均值：在区间内为 0，超出 x 倍时为 (ln x)²。
优化目标 = T1 + LAMBDA × 罚项，LAMBDA 事先固定为 0.1，此后不再调。
M1 验收要求总罚项 < ACCEPT_MAX。
"""
import os, sys, json
import numpy as np

LAMBDA = 0.1
ACCEPT_MAX = 0.005
SOFT_MAX = 6.5
PHARYNX_MIN = 0.15
LIP = {"u": (0.08, 0.6), "v": (0.08, 0.6), "o": (0.3, 1.5), "a": (2.0, 5.5), "e": (1.0, 3.5), "i": (1.0, 3.5)}
VOWELS = ["a", "o", "e", "i", "u", "v"]


def _hinge(x, lo=None, hi=None):
    x = np.maximum(np.asarray(x, float), 1e-6)
    out = np.zeros_like(x)
    if lo is not None:
        out = np.where(x < lo, np.log(lo / x), out)
    if hi is not None:
        out = np.where(x > hi, np.log(x / hi), out)
    return out


def vowel_penalty(A, v):
    A = np.asarray(A, float)
    n = len(A)
    terms = {
        "max_area": float(np.mean(_hinge(A, hi=SOFT_MAX) ** 2)),
        "pharynx_min": float(np.mean(_hinge(A[2:n // 2], lo=PHARYNX_MIN) ** 2)),
        "lip": float(_hinge([A[-1]], *LIP[v])[0] ** 2),
    }
    return float(np.mean(list(terms.values()))), terms


def engine_areas(vals, params_path=None):
    """若当前目录的引擎能导出生成的元音面积函数（如 g002-e01 的发音模型），优先用它；否则用 area_* 参数。"""
    if params_path:
        try:
            if os.getcwd() not in sys.path:
                sys.path.insert(0, os.getcwd())
            from engine.control.story_modes import export_vowel_areas
            out = dict(vals)
            out.update({(k if k.startswith("area_") else f"area_{k}"): list(v) for k, v in export_vowel_areas(params_path).items()})
            return out
        except ImportError:
            pass
    return vals


def penalty(vals, params_path=None):
    vals = engine_areas(vals, params_path)
    per, detail = {}, {}
    for v in VOWELS:
        k = f"area_{v}"
        if k in vals:
            per[v], detail[v] = vowel_penalty(vals[k], v)
    return (float(np.mean(list(per.values()))) if per else 0.0), per, detail


if __name__ == "__main__":
    vals = json.load(open(sys.argv[1]))["values"]
    tot, per, det = penalty(vals, sys.argv[1])
    vals = engine_areas(vals, sys.argv[1])
    print(json.dumps({"penalty": round(tot, 5), "accept_max": ACCEPT_MAX, "pass": tot < ACCEPT_MAX,
                      "per_vowel": {k: round(x, 5) for k, x in per.items()},
                      "detail": {v: {k: round(x, 5) for k, x in d.items() if x > 0} for v, d in det.items()},
                      "lip_area": {v: round(float(vals[f"area_{v}"][-1]), 3) for v in VOWELS},
                      "max_area": {v: round(float(max(vals[f"area_{v}"])), 2) for v in VOWELS}},
                     ensure_ascii=False, indent=1))
