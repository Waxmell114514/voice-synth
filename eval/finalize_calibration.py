"""阶段 0.3 后半：根据 calibration_raw.json 做出全部校准决定（只运行一次）。

规则（写进 reports/calibration.md）：
- 区分度：逐条指标要求 AUC(真人优于基线) ≥ 0.75；集合级指标要求自助法 P(真人更好) ≥ 0.95；
  T1 要求 eSpeak 偏差高于 95% 的真人说话人。不满足的指标删除。
- 反欺骗检测器另加合理性检查：对种子引擎 g0（明显不像人）打分不得高于真人，否则删除
  （AASIST 因此删除）。检测器的真人/基线 AUC 均已饱和，改按“真人分 − g0 分”排序。
- 评估器分组：同一角色两个候选中区分度高的进开发组，另一个进终审组；ASR 开发组固定
  Paraformer（最快），终审组 SenseVoice。开发组锚点用开发集，终审组锚点用隐藏集。
- 过关线（config 中标“初始”的阈值，只改这一次）：统一取“从基线到真人走完 90%”处，
  即 gate = human + 0.1·(baseline − human)。T1 的 human 取校准说话人逐人偏差的中位数；
  T2 的 human 取句子层代理值（真人没有孤立词录音，见报告）。
  human_T3_cer_max 保持 0.05 不放宽：它是对 ASR 本身的要求，不按结果迁就。
"""
import os, sys, json, re
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

AUC_MIN, BOOT_MIN = 0.75, 0.95


def main():
    raw = json.load(open(os.path.join(C.DATA, "calibration_raw.json")))
    cache = dict(np.load(os.path.join(C.DATA, "ref_cache.npz")))
    S = raw["sentences"]

    def disc(split, key):
        r = S[split][key]
        if "auc" in r:
            return r["auc"], r["auc"] >= AUC_MIN
        return r["p_human_better"], r["p_human_better"] >= BOOT_MIN

    def score(cands, fmt):
        out = {}
        for c in cands:
            k = fmt.format(c)
            v = [disc(sp, k)[0] for sp in ("dev", "hidden")]
            out[c] = float(np.mean(v))
        return out

    decisions = {}
    suites = {"dev": {"asr": "paraformer"}, "final": {"asr": "sensevoice"}}
    sanity = raw.get("detector_sanity_g0", {})
    det_ok = [d for d in ["aasist", "w2v-deepfake", "xlsr-deepfake"] if sanity[d]["g0"] < sanity[d]["human"]]
    decisions["det_dropped_sanity"] = {d: sanity[d] for d in sanity if d not in det_ok}
    for role, cands, fmt in [("mos", ["utmos22", "utmosv2"], "T4.mos[{}]"),
                             ("det", det_ok, "T4.p_real[{}]"),
                             ("ssl", ["chinese-hubert-base", "wavlm-base-plus"], "T4.ssl_fd[{}]")]:
        sc = score(cands, fmt)
        if role == "det":
            sc = {d: sanity[d]["human"] - sanity[d]["g0"] for d in cands}
        best = max(sc, key=sc.get); other = [c for c in cands if c != best][0]
        suites["dev"][role] = best; suites["final"][role] = other
        decisions[role] = sc

    kept, anchors, dropped = {}, {}, {}
    for suite, split in (("dev", "dev"), ("final", "hidden")):
        su = suites[suite]
        keymap = {"T3.cer": f"T3.cer[{su['asr']}]", "T2.syllable_acc": f"T2proxy.syllable_acc[{su['asr']}]",
                  "T2.tone_acc": f"T2proxy.tone_acc[{su['asr']}]",
                  "T4.mos": f"T4.mos[{su['mos']}]", "T4.p_real": f"T4.p_real[{su['det']}]",
                  "T4.ssl_fd": f"T4.ssl_fd[{su['ssl']}]", "T4.f0_w1": "T4.f0_w1", "T4.dur_w1": "T4.dur_w1"}
        kept[suite], anchors[suite], dropped[suite] = [], {}, {}
        for m, k in keymap.items():
            r = S[split][k]
            val, ok = disc(split, k)
            better = (r["human"] - r["baseline"]) * r["dir"] > 0
            anchors[suite][m] = {"human": r["human"], "baseline": r["baseline"], "discrimination": val}
            if ok and better:
                kept[suite].append(m)
            else:
                dropped[suite][m] = {"discrimination": val, "human_better": bool(better)}
        # T2 词表上的基线（eSpeak 读孤立词）
        anchors[suite]["T2.wordlist_baseline"] = raw["espeak_wordlist_T2"][su["asr"]]

    # T1
    hp = np.array(raw["t1"]["human_per_speaker"])
    es = raw["t1"]["espeak"]["T1.formant_rel_error"]
    t1_ok = es > np.percentile(hp, 95)
    t1 = {"human_median": float(np.median(hp)), "human_p95": float(np.percentile(hp, 95)),
          "human_n_speakers": int(len(hp)), "espeak": es, "kept": bool(t1_ok)}
    for suite in kept:
        if t1_ok:
            kept[suite].append("T1.formant_rel_error")
        anchors[suite]["T1.formant_rel_error"] = {"human": t1["human_median"], "baseline": es}

    # 过关线
    def gate(h, b):
        return h + 0.1 * (b - h)
    a = anchors["dev"]
    gates = {
        "M1_formant_rel_error_max": round(gate(t1["human_median"], es), 3),
        "M2_syllable_acc_min": round(gate(a["T2.syllable_acc"]["human"], a["T2.wordlist_baseline"]["syllable_acc"]), 3),
        "M2_tone_acc_min": round(gate(a["T2.tone_acc"]["human"], a["T2.wordlist_baseline"]["tone_acc"]), 3),
        "M3_dev_cer_max": round(gate(a["T3.cer"]["human"], a["T3.cer"]["baseline"]), 3),
    }
    # 冻结检查
    human_cer = {s: anchors[s]["T3.cer"]["human"] for s in anchors}
    beats = {s: {m: bool((anchors[s][m]["human"] - anchors[s][m]["baseline"]) *
                         (-1 if re.search(r"cer|fd|w1|error", m) else 1) > 0)
                 for m in kept[s]} for s in kept}

    cal = {"t1_ref": raw["t1"]["ref"], "suites": suites, "kept_metrics": kept, "anchors": anchors,
           "dropped_metrics": dropped, "selection_scores": decisions, "t1": t1, "gates": gates,
           "freeze_inputs": {"human_T3_cer": human_cer, "human_beats_baseline_on_kept": beats}}
    json.dump(cal, open(os.path.join(C.DATA, "calibration.json"), "w"), ensure_ascii=False, indent=1)
    for suite in ("dev", "final"):
        s = suites[suite]["ssl"]
        np.savez(os.path.join(C.DATA, f"ref_{suite}.npz"), f0=cache["f0"], dur=cache["dur"],
                 **{k: cache[f"{s}__{k}"] for k in ("pca_mean", "pca_comp", "ssl_mu", "ssl_cov")})
    print(json.dumps({k: cal[k] for k in ("suites", "kept_metrics", "dropped_metrics", "gates", "t1", "freeze_inputs")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
