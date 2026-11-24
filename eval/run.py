"""评估器入口。

  python eval/run.py --params params/x.json --tiers T0,T1,T2,T3,T4 --set dev --experiment g001-e01
  python eval/run.py --params params/x.json --tiers T1 --set opt            # 优化器用，不计配额
  python eval/run.py --params params/x.json --tiers T3,T4 --set hidden --suite final --acceptance M3

集合：opt = 开发集固定子集（30 句 / 200 词）；dev = 开发集；hidden = 隐藏集（只给汇总分）。
输出：stdout 一个 JSON。只含分数和 EVAL.md 允许的诊断。
"""
import os, sys, json, time, argparse, hashlib, datetime
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import models as M
import vowels as V
from runner import EngineRunner, EspeakRunner, HumanRunner

CAL_PATH = os.path.join(C.DATA, "calibration.json")
QUOTA_LOG = os.path.join(C.REPO, "ledger", "eval_calls.jsonl")
OPT_SENT, OPT_WORDS = 30, 200


def load_cal():
    return json.load(open(CAL_PATH)) if os.path.exists(CAL_PATH) else None


def ref_npz(suite):
    p = os.path.join(C.DATA, f"ref_{suite}.npz")
    return dict(np.load(p)) if os.path.exists(p) else None


# ------------------------------------------------------------------ 条目
def sentence_items(which, system):
    S = C.jload("sentences.json")
    if which == "opt":
        S = [s for s in S if s["split"] == "dev"][:OPT_SENT]
    else:
        S = [s for s in S if s["split"] == which]
    if system == "engine":
        return S, [(s["id"], "text", s["text"]) for s in S]
    if system == "espeak":
        return S, [(s["id"], "hanzi", s["text"]) for s in S]
    return S, [(s["id"], "utt", s["human_utt"]) for s in S]


def word_items(which, system):
    W = C.jload("wordlist.json")
    if which == "opt":
        W = W[::max(1, len(W) // OPT_WORDS)][:OPT_WORDS]
    if system == "engine":
        return W, [(w["word"], "pinyin", w["pinyin"]) for w in W]
    return W, [(w["word"], "hanzi", w["word"]) for w in W]


# ------------------------------------------------------------------ 各层
def tier_T1(run, seed, system):
    cal = load_cal()
    ref = cal["t1_ref"]
    items = [(v, "pinyin", V.VOWEL_PINYIN[v]) if system == "engine" else (v, "hanzi", V.VOWEL_HANZI[v])
             for v in V.VOWELS]
    au = run.synth(items, seed)
    dev, per = [], {}
    for v in V.VOWELS:
        a = au.get(v)
        f = V.synth_vowel_formants(a[0], 16000) if a is not None else None
        if f is None:
            rel = [1.0, 1.0, 1.0]   # 测不出按 100% 偏差计
        else:
            rel = [abs(f[k] - ref[v][k]) / ref[v][k] for k in range(3)]
        per[v] = [round(x, 4) for x in rel]
        dev += rel
    return {"T1.formant_rel_error": float(np.mean(dev)), "_diag": {"T1.per_vowel_rel_error_F1F2F3": per}}


def asr_pinyin(asr, wavs):
    hyps = asr([C.prep(w) for w in wavs])
    return hyps, [C.toned(C.han_only(h)) for h in hyps]


def tier_T2(run, seed, system, which, suite):
    W, items = word_items(which, system)
    au = run.synth(items, seed)
    asr = M.get("asr", M.SUITES[suite]["asr"])
    keys = [it[0] for it in items]
    ok = [k for k in keys if au.get(k) is not None]
    _, hp = asr_pinyin(asr, [au[k][0] for k in ok]) if ok else ([], [])
    hp = dict(zip(ok, hp))
    conf = C.Confusions()
    N = E = T = 0
    for w in W:
        ref = w["pinyin"].split()
        hyp = hp.get(w["word"], [])
        n, e, t = C.syllable_scores(ref, hyp)
        N += n; E += min(e, n); T += t
        conf.add(ref, hyp)
    return {"T2.syllable_acc": 1 - E / N, "T2.tone_acc": T / N, "_diag": {"T2.confusions": conf.export()}}


def tier_T3T4(run, seed, system, which, suite, tiers):
    S, items = sentence_items(which, system)
    au = run.synth(items, seed)
    out, diag = {}, {}
    keys = [s["id"] for s in S]
    wav = {k: au[k][0] for k in keys if au.get(k) is not None}
    fail = len(keys) - len(wav)
    if "T3" in tiers:
        asr = M.get("asr", M.SUITES[suite]["asr"])
        ks = list(wav)
        hyps, hps = asr_pinyin(asr, [wav[k] for k in ks]) if ks else ([], [])
        hyp = dict(zip(ks, hyps)); hpy = dict(zip(ks, hps))
        ce = cn = pe = pn = 0
        conf = C.Confusions()
        for s in S:
            r = C.han_only(s["text"]); h = C.han_only(hyp.get(s["id"], ""))
            ce += min(C.edit_distance(list(r), list(h)), len(r)); cn += len(r)
            rp = C.toned(r); hp_ = hpy.get(s["id"], [])
            pe += min(C.edit_distance(rp, hp_), len(rp)); pn += len(rp)
            conf.add(rp, hp_)
        out["T3.cer"] = ce / cn
        out["T3.pinyin_err"] = pe / pn
        diag["T3.confusions"] = conf.export()
    if "T4" in tiers:
        out.update(t4_raw(wav, S, suite))
    if fail:
        out["synth_failures"] = fail
    out["_diag"] = diag
    return out


def t4_raw(wav, S, suite):
    """T4 原始分项（未归一化）。"""
    su = M.SUITES[suite]
    ks = [s["id"] for s in S if s["id"] in wav]
    nsyl = {s["id"]: len(C.han_only(s["text"])) for s in S}
    if not ks:
        return {}
    pre = [C.prep(wav[k]) for k in ks]
    r = {}
    r["T4.mos"] = float(np.mean(M.get("mos", su["mos"])(pre)))
    r["T4.p_real"] = float(np.mean(M.get("det", su["det"])(pre)))
    ref = ref_npz(suite)
    if ref is not None:
        E = M.get("ssl", su["ssl"])(pre)
        Z = (E - ref["pca_mean"]) @ ref["pca_comp"].T
        mu = Z.mean(0); cov = np.cov(Z, rowvar=False)
        r["T4.ssl_fd"] = C.frechet(mu, cov, ref["ssl_mu"], ref["ssl_cov"])
        f0 = np.concatenate([C.f0_norm_semitones(wav[k], 16000) for k in ks] + [np.zeros(0)])
        r["T4.f0_w1"] = C.wasserstein1(f0, ref["f0"]) if len(f0) > 50 else 12.0
        d = np.array([C.mean_syllable_duration(wav[k], 16000, nsyl[k]) for k in ks])
        d = d[np.isfinite(d)]
        r["T4.dur_w1"] = C.wasserstein1(d, ref["dur"]) if len(d) else 1.0
    return r


T4_DIR = {"T4.mos": +1, "T4.p_real": +1, "T4.ssl_fd": -1, "T4.f0_w1": -1, "T4.dur_w1": -1}


def t4_composite(raw, suite):
    cal = load_cal()
    if not cal:
        return None, {}
    an = cal["anchors"][suite]
    kept = cal["kept_metrics"][suite]
    parts = {}
    for k in T4_DIR:
        if k in raw and k in kept and k in an:
            h, b = an[k]["human"], an[k]["baseline"]
            parts[k + ".norm"] = float(np.clip((raw[k] - b) / (h - b), 0, 1)) if h != b else 0.0
    return (float(np.mean(list(parts.values()))) if parts else None), parts


# ------------------------------------------------------------------ T0
def tier_T0(params_path):
    from t0 import run_t0
    return run_t0(params_path)


# ------------------------------------------------------------------ 主流程
def quota_check(exp, n_quota):
    used = 0
    if os.path.exists(QUOTA_LOG):
        for l in open(QUOTA_LOG):
            if json.loads(l).get("experiment") == exp:
                used += 1
    if used >= n_quota:
        raise SystemExit(json.dumps({"error": f"quota exhausted for {exp}: {used}/{n_quota}"}))
    return used


def quota_log(rec):
    os.makedirs(os.path.dirname(QUOTA_LOG), exist_ok=True)
    with open(QUOTA_LOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def evaluate(system, params, tiers, which, suite, seeds):
    if system == "engine":
        run = EngineRunner(params)
    elif system == "espeak":
        run = EspeakRunner(); seeds = [0]
    else:
        run = HumanRunner(); seeds = [0]
    per_seed, diags = [], {}
    try:
        for sd in seeds:
            r = {}
            if "T1" in tiers:
                x = tier_T1(run, sd, system); diags.update(x.pop("_diag")); r.update(x)
            if "T2" in tiers:
                x = tier_T2(run, sd, system, which, suite); diags.update(x.pop("_diag")); r.update(x)
            if "T3" in tiers or "T4" in tiers:
                x = tier_T3T4(run, sd, system, which, suite, tiers); diags.update(x.pop("_diag")); r.update(x)
                if "T4" in tiers:
                    comp, parts = t4_composite(r, suite)
                    r.update(parts)
                    if comp is not None:
                        r["T4.composite"] = comp
            per_seed.append(r)
    finally:
        run.close()
    keys = sorted({k for r in per_seed for k in r})
    summ = {}
    for k in keys:
        v = np.array([r[k] for r in per_seed if k in r], dtype=float)
        summ[k] = {"mean": round(float(v.mean()), 5), "std": round(float(v.std(ddof=1)) if len(v) > 1 else 0.0, 5)}
    return summ, diags


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--params")
    ap.add_argument("--system", default="engine", choices=["engine", "espeak", "human"])
    ap.add_argument("--tiers", default="T0,T1")
    ap.add_argument("--set", default="opt", choices=["opt", "dev", "hidden"])
    ap.add_argument("--suite", default="dev", choices=["dev", "final"])
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--experiment", help="实验 id，--set dev 时必填，计配额")
    ap.add_argument("--acceptance", help="里程碑验收（M1..M4），--set hidden 或 --suite final 时必填")
    ap.add_argument("--calibration", action="store_true", help="仅阶段 0 校准使用")
    a = ap.parse_args(argv)
    tiers = a.tiers.split(",")
    seeds = [int(s) for s in a.seeds.split(",")]
    t_start = time.time()
    import yaml
    cfg = yaml.safe_load(open(os.path.join(C.REPO, "config.yaml")))
    restricted = a.set == "hidden" or a.suite == "final"
    if a.system != "engine" and not a.calibration:
        raise SystemExit("human / espeak 只在校准时使用")
    if restricted and not (a.acceptance or a.calibration):
        raise SystemExit("隐藏集 / 终审组只在里程碑验收时运行（--acceptance）")
    if a.set == "dev" and a.system == "engine" and not a.calibration:
        if not a.experiment:
            raise SystemExit("--set dev 需要 --experiment")
        quota_check(a.experiment, cfg["eval_quota_per_experiment"])

    out = {"system": a.system, "set": a.set, "suite": a.suite, "seeds": seeds, "tiers": tiers}
    if a.params:
        out["params_sha256"] = hashlib.sha256(open(a.params, "rb").read()).hexdigest()[:16]
    if "T0" in tiers and a.system == "engine":
        t0 = tier_T0(a.params)
        out["T0"] = t0
        if not t0["pass"]:
            print(json.dumps(out, ensure_ascii=False, indent=1)); return 2
    rest = [t for t in tiers if t != "T0"]
    if rest:
        summ, diags = evaluate(a.system, a.params, rest, a.set, a.suite, seeds)
        out["scores"] = summ
        if not restricted:
            out["diagnostics"] = diags
    out["wall_sec"] = round(time.time() - t_start, 1)
    if a.system == "engine" and (a.set == "dev" or restricted) and not a.calibration:
        quota_log({"time": datetime.datetime.now().isoformat(timespec="seconds"),
                   "experiment": a.experiment or a.acceptance, "set": a.set, "suite": a.suite,
                   "tiers": tiers, "params_sha256": out.get("params_sha256")})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
