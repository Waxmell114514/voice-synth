"""独立检查（非正式分数，不计配额）：把 T1 的 6 个元音放进优化器没见过的语境
（不同声母 × 不同声调的 CV 音节）测共振峰，看孤立元音上的拟合能否泛化。

  python tools/context_vowel_check.py params/x.json [--seeds 0,1,2]

测量：Praat 判为有声的最长连续段的中间 40%，Burg 共振峰中位数（与 T1 同一函数 formants_mid；
定位改用浊音而非能量，避免爆破噪声干扰）。
只输出相对偏差，不输出参考值（CONSTRAINTS 第 5 条的精神）。
"""
import os, sys, json, argparse
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "eval"))

CONTEXTS = {
    "a": ["ba1", "da4", "ga2", "ma3", "la1", "sha1", "ta4", "ka3"],
    "o": ["bo1", "po2", "mo4", "fo2", "bo4", "mo1"],
    "e": ["de2", "ge1", "ke4", "he2", "se4", "zhe2", "te4", "le4"],
    "i": ["bi3", "di1", "ji1", "li4", "xi1", "qi2", "mi2", "ti3"],
    "u": ["bu4", "du2", "gu3", "hu1", "lu4", "zhu1", "su4", "mu4"],
    "v": ["ju2", "qu4", "xu1", "lv4", "nv3", "yu4", "xu3", "qu1"],
}


def voiced_vowel_formants(x, sr):
    """按浊音定位元音：取 Praat 判为有声的最长连续段的中间 40%（避开爆破、擦音噪声）。"""
    import parselmouth
    from common import formants_mid
    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=sr)
    p = snd.to_pitch_ac(time_step=0.01, pitch_floor=60.0, pitch_ceiling=600.0)
    v = p.selected_array["frequency"] > 0
    best, cur, start, bs = 0, 0, 0, 0
    for i, on in enumerate(list(v) + [False]):
        if on:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur > best:
                best, bs = cur, start
            cur = 0
    if best < 5:
        return None
    t0 = p.xs()[bs] - 0.005; d = best * 0.01
    return formants_mid(x, sr, t0 + 0.3 * d, t0 + 0.7 * d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("params")
    ap.add_argument("--seeds", default="0,1,2")
    a = ap.parse_args()
    import vowels as V
    from runner import EngineRunner
    ref = json.load(open(os.path.join(REPO, "eval", "data", "calibration.json")))["t1_ref"]
    seeds = [int(s) for s in a.seeds.split(",")]
    run = EngineRunner(a.params)
    per_seed, per_vowel, fails = [], {v: [] for v in CONTEXTS}, 0
    try:
        for sd in seeds:
            items = [(f"{v}|{s}", "pinyin", s) for v, ss in CONTEXTS.items() for s in ss]
            au = run.synth(items, sd)
            errs = []
            for k, w in au.items():
                v = k.split("|")[0]
                f = voiced_vowel_formants(w[0], 16000) if w is not None else None
                if f is None:
                    fails += 1      # 测不出（通常是元音太弱，Praat 判不出浊音），单独计数，不计入偏差
                    continue
                e = float(np.mean([abs(f[i] - ref[v][i]) / ref[v][i] for i in range(3)]))
                errs.append(e); per_vowel[v].append(e)
            per_seed.append(float(np.mean(errs)) if errs else 1.0)
    finally:
        run.close()
    out = {"params": a.params, "context_formant_rel_error": {"mean": round(float(np.mean(per_seed)), 5),
                                                             "std": round(float(np.std(per_seed, ddof=1)) if len(per_seed) > 1 else 0.0, 5)},
           "per_vowel_mean": {v: (round(float(np.mean(x)), 4) if x else None) for v, x in per_vowel.items()},
           "n_syllables": sum(len(s) for s in CONTEXTS.values()) * len(seeds), "measure_failures": fails,
           "note": "非正式独立检查：语境音节未参与优化"}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
