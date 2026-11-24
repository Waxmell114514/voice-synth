"""阶段 0.3 校准。

1. 由参考说话人建参考统计：T1 元音共振峰、T4 的 SSL 高斯（每组评估器各一套）、F0 和音节时长分布。
2. 真人（校准说话人）与 eSpeak NG 各跑全部指标；逐条值用于判断指标是否能区分两者。
3. 写 eval/data/calibration.json、eval/data/ref_{dev,final}.npz、reports/calibration.md 所需的 eval/data/calibration_raw.json。
只在阶段 0 运行。
"""
import os, sys, json, time, collections
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import models as M
import vowels as V
from runner import EspeakRunner, HumanRunner

RNG = np.random.default_rng(7)
LIM = int(os.environ.get("CAL_LIMIT", "0")) or None
LOG = lambda *a: print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)
ASR_CANDIDATES = ["paraformer", "sensevoice"]  # whisper-turbo 试跑后剔除：人声 CER 7–12%，慢 20 倍
MOS_CANDIDATES = ["utmos22", "utmosv2"]
DET_CANDIDATES = ["aasist", "w2v-deepfake"]
SSL_CANDIDATES = ["chinese-hubert-base", "wavlm-base-plus"]


def sv_tokens(asr, x):
    s = asr.r.create_stream(); s.accept_waveform(16000, x); asr.r.decode_stream(s)
    return s.result.tokens, s.result.timestamps


# ------------------------------------------------------------------ 1. T1 参考与真人校准
def t1_stats():
    sv = M.get("asr", "sensevoice")
    pool = C.jload("t1pool.json") + [dict(r, group="reference") for r in C.jload("refpool.json")]
    sents = C.jload("sentences.json")
    pool += [{"utt": s["human_utt"], "speaker": s["speaker"], "text": s["text"], "group": "calibration"} for s in sents]
    pool = pool[::max(1, len(pool) // (LIM * 25))] if LIM else pool
    tok = collections.defaultdict(lambda: collections.defaultdict(list))   # speaker -> vowel -> [F]
    grp = {}
    for i, r in enumerate(pool):
        x = M.load_wav(os.path.join(C.DATA, "wav", r["utt"] + ".wav"))
        t, ts = sv_tokens(sv, x)
        for v, *f in V.human_vowel_tokens(x, 16000, r["text"], t, ts):
            tok[r["speaker"]][v].append(f)
        grp[r["speaker"]] = r["group"]
        if i % 300 == 0:
            LOG("t1 pool", i, len(pool))
    ref = {}
    counts = {}
    for v in V.VOWELS:
        spk_med = [np.median(np.array(tok[s][v]), 0) for s in tok if grp[s] == "reference" and len(tok[s][v]) >= 2]
        all_tok = [f for s in tok if grp[s] == "reference" for f in tok[s][v]]
        counts[v] = {"speakers": len(spk_med), "tokens": len(all_tok)}
        ref[v] = (np.median(np.array(spk_med), 0) if len(spk_med) >= 5 else np.median(np.array(all_tok), 0)).tolist()
    # 真人：每个校准说话人自己的元音中位数 vs 参考
    human = []
    per_vowel = collections.defaultdict(list)
    for s in tok:
        if grp[s] != "calibration":
            continue
        errs = []
        for v in V.VOWELS:
            if len(tok[s][v]) >= 2:
                f = np.median(np.array(tok[s][v]), 0)
                e = [abs(f[k] - ref[v][k]) / ref[v][k] for k in range(3)]
                errs += e; per_vowel[v].append(np.mean(e))
        if len(errs) >= 12:     # 至少 4 个元音
            human.append(float(np.mean(errs)))
    return ref, counts, human, {v: float(np.mean(x)) for v, x in per_vowel.items()}


# ------------------------------------------------------------------ 2. 句子层逐条特征
def sentence_features(wavs, texts, need_asr):
    pre = [C.prep(w) for w in wavs]
    f = {"hyp": {}, "mos": {}, "det": {}, "ssl": {}}
    for a in need_asr:
        f["hyp"][a] = M.get("asr", a)(pre); LOG("asr", a)
    for m in MOS_CANDIDATES:
        f["mos"][m] = M.get("mos", m)(pre); LOG("mos", m)
    for d in DET_CANDIDATES:
        f["det"][d] = M.get("det", d)(pre); LOG("det", d)
    for s in SSL_CANDIDATES:
        f["ssl"][s] = M.get("ssl", s)(pre); LOG("ssl", s)
    f["f0"] = [C.f0_norm_semitones(w, 16000) for w in wavs]
    f["dur"] = [C.mean_syllable_duration(w, 16000, len(C.han_only(t))) for w, t in zip(wavs, texts)]
    return f


def per_utt_cer(hyps, texts):
    out = []
    for h, t in zip(hyps, texts):
        r = C.han_only(t); hh = C.han_only(h)
        out.append(min(C.edit_distance(list(r), list(hh)), len(r)) / len(r))
    return out


def per_utt_syl(hyps, texts):
    sa, ta = [], []
    for h, t in zip(hyps, texts):
        rp = C.toned(C.han_only(t)); hp = C.toned(C.han_only(h))
        n, e, tt = C.syllable_scores(rp, hp)
        sa.append(1 - min(e, n) / n); ta.append(tt / n)
    return sa, ta


def auc(pos, neg):
    """P(pos > neg)，pos 为“应当更好”的一组。"""
    pos = np.asarray(pos, float); neg = np.asarray(neg, float)
    gt = (pos[:, None] > neg[None, :]).mean(); eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + 0.5 * eq)


def set_metric_boot(fn, A, B, n=200):
    """集合级指标（越小越好）：自助法 P(fn(A*) < fn(B*))。"""
    wins = 0
    for _ in range(n):
        ia = RNG.integers(0, len(A), len(A)); ib = RNG.integers(0, len(B), len(B))
        wins += fn([A[i] for i in ia]) < fn([B[i] for i in ib])
    return wins / n


def main():
    t_all = time.time()
    out = {"created": time.strftime("%Y-%m-%d %H:%M:%S")}
    LOG("T1 stats")
    t1_ref, t1_counts, t1_human, t1_human_pv = t1_stats()
    out["t1_ref"] = {v: [round(x, 1) for x in t1_ref[v]] for v in V.VOWELS}
    out["t1_ref_counts"] = t1_counts
    cal = {"t1_ref": out["t1_ref"]}
    json.dump(cal, open(os.path.join(C.DATA, "calibration.json"), "w"))   # 临时（T1 评估需要）

    # 参考池（参考说话人）
    refpool = C.jload("refpool.json")[:LIM]
    R = [M.load_wav(os.path.join(C.DATA, "wav", r["utt"] + ".wav")) for r in refpool]
    Rpre = [C.prep(w) for w in R]
    ref_f0 = np.concatenate([C.f0_norm_semitones(w, 16000) for w in R])
    ref_dur = np.array([C.mean_syllable_duration(w, 16000, len(C.han_only(r["text"]))) for w, r in zip(R, refpool)])
    ref_dur = ref_dur[np.isfinite(ref_dur)]
    ref_ssl = {s: M.get("ssl", s)(Rpre) for s in SSL_CANDIDATES}
    LOG("refpool done")

    def pca_ref(E, k=64):
        mu = E.mean(0); U, S, Vt = np.linalg.svd(E - mu, full_matrices=False)
        comp = Vt[:k]; Z = (E - mu) @ comp.T
        return {"pca_mean": mu, "pca_comp": comp, "ssl_mu": Z.mean(0), "ssl_cov": np.cov(Z, rowvar=False)}
    ref_pca = {s: pca_ref(ref_ssl[s]) for s in SSL_CANDIDATES}

    def fd_of(s):
        rp = ref_pca[s]
        def fn(E):
            Z = (np.asarray(E) - rp["pca_mean"]) @ rp["pca_comp"].T
            return C.frechet(Z.mean(0), np.cov(Z, rowvar=False), rp["ssl_mu"], rp["ssl_cov"])
        return fn
    f0_fn = lambda L: C.wasserstein1(np.concatenate(L), ref_f0)
    dur_fn = lambda L: C.wasserstein1(np.array([d for d in L if np.isfinite(d)]), ref_dur)

    sents = C.jload("sentences.json")
    res = {}
    for split in ("dev", "hidden"):
        S = [s for s in sents if s["split"] == split][:LIM]
        texts = [s["text"] for s in S]
        hu = HumanRunner().synth([(s["id"], "utt", s["human_utt"]) for s in S], 0)
        es = EspeakRunner().synth([(s["id"], "hanzi", s["text"]) for s in S], 0)
        H = [hu[s["id"]][0] for s in S]; B = [es[s["id"]][0] for s in S]
        LOG(split, "human features"); fh = sentence_features(H, texts, ASR_CANDIDATES)
        LOG(split, "espeak features"); fb = sentence_features(B, texts, ASR_CANDIDATES)
        r = {}
        for a in ASR_CANDIDATES:
            ch, cb = per_utt_cer(fh["hyp"][a], texts), per_utt_cer(fb["hyp"][a], texts)
            sh, th = per_utt_syl(fh["hyp"][a], texts); sb, tb = per_utt_syl(fb["hyp"][a], texts)
            nt = sum(len(C.han_only(t)) for t in texts)
            wch = sum(c * len(C.han_only(t)) for c, t in zip(ch, texts)) / nt
            wcb = sum(c * len(C.han_only(t)) for c, t in zip(cb, texts)) / nt
            r[f"T3.cer[{a}]"] = {"human": wch, "baseline": wcb, "auc": auc(-np.array(ch), -np.array(cb)), "dir": -1}
            r[f"T2proxy.syllable_acc[{a}]"] = {"human": float(np.mean(sh)), "baseline": float(np.mean(sb)), "auc": auc(sh, sb), "dir": +1}
            r[f"T2proxy.tone_acc[{a}]"] = {"human": float(np.mean(th)), "baseline": float(np.mean(tb)), "auc": auc(th, tb), "dir": +1}
        for m in MOS_CANDIDATES:
            r[f"T4.mos[{m}]"] = {"human": float(np.mean(fh["mos"][m])), "baseline": float(np.mean(fb["mos"][m])),
                                 "auc": auc(fh["mos"][m], fb["mos"][m]), "dir": +1}
        for d in DET_CANDIDATES:
            r[f"T4.p_real[{d}]"] = {"human": float(np.mean(fh["det"][d])), "baseline": float(np.mean(fb["det"][d])),
                                    "auc": auc(fh["det"][d], fb["det"][d]), "dir": +1}
        for s in SSL_CANDIDATES:
            fn = fd_of(s)
            r[f"T4.ssl_fd[{s}]"] = {"human": fn(fh["ssl"][s]), "baseline": fn(fb["ssl"][s]),
                                    "p_human_better": set_metric_boot(fn, list(fh["ssl"][s]), list(fb["ssl"][s])), "dir": -1}
        r["T4.f0_w1"] = {"human": f0_fn(fh["f0"]), "baseline": f0_fn(fb["f0"]),
                         "p_human_better": set_metric_boot(f0_fn, fh["f0"], fb["f0"]), "dir": -1}
        r["T4.dur_w1"] = {"human": dur_fn(fh["dur"]), "baseline": dur_fn(fb["dur"]),
                          "p_human_better": set_metric_boot(dur_fn, fh["dur"], fb["dur"]), "dir": -1}
        res[split] = r
        LOG(split, "done", json.dumps({k: round(v["human"], 3) for k, v in r.items()}))

    # eSpeak 的 T1 和 T2（词表）
    sys.argv = ["x"]
    import run as RUN
    es_run = EspeakRunner()
    es_t1 = RUN.tier_T1(es_run, 0, "espeak")
    es_t2 = {}
    for suite_asr in ["paraformer", "sensevoice"]:
        W, items = RUN.word_items("dev", "espeak")
        W, items = W[:LIM], items[:LIM]
        au = es_run.synth(items, 0)
        hyps = M.get("asr", suite_asr)([C.prep(au[w["word"]][0]) for w in W])
        N = E = T = 0
        for w, h in zip(W, hyps):
            n, e, t = C.syllable_scores(w["pinyin"].split(), C.toned(C.han_only(h)))
            N += n; E += min(e, n); T += t
        es_t2[suite_asr] = {"syllable_acc": 1 - E / N, "tone_acc": T / N}
        LOG("espeak T2", suite_asr, es_t2[suite_asr])

    raw = {"t1": {"ref": out["t1_ref"], "counts": t1_counts, "human_per_speaker": t1_human,
                  "human_per_vowel": t1_human_pv, "espeak": es_t1},
           "sentences": res, "espeak_wordlist_T2": es_t2,
           "ref_sizes": {"refpool": len(refpool), "f0_frames": int(len(ref_f0)), "dur_utts": int(len(ref_dur))},
           "wall_min": round((time.time() - t_all) / 60, 1)}
    np.savez(os.path.join(C.DATA, "ref_cache.npz"), f0=ref_f0, dur=ref_dur,
             **{f"{s}__{k}": v for s in SSL_CANDIDATES for k, v in ref_pca[s].items()})
    json.dump(raw, open(os.path.join(C.DATA, "calibration_raw.json"), "w"), ensure_ascii=False, indent=1)
    LOG("all done", raw["wall_min"], "min")


if __name__ == "__main__":
    main()
