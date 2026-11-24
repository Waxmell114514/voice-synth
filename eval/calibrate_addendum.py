"""阶段 0.3 补充：AASIST 失效后（把种子引擎 g0 判得比真人更“真”，见 reports/calibration.md），
补算候选检测器 xlsr-deepfake 在开发集 / 隐藏集上的真人与基线锚点，并记录三个检测器对 g0 的分数。
只在阶段 0 运行一次，结果并入 calibration_raw.json。"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C, models as M
from runner import EspeakRunner, HumanRunner, EngineRunner
from calibrate import auc

raw_p = os.path.join(C.DATA, "calibration_raw.json")
raw = json.load(open(raw_p))
sents = C.jload("sentences.json")
det = M.get("det", "xlsr-deepfake")
for split in ("dev", "hidden"):
    S = [s for s in sents if s["split"] == split]
    hu = HumanRunner().synth([(s["id"], "utt", s["human_utt"]) for s in S], 0)
    es = EspeakRunner().synth([(s["id"], "hanzi", s["text"]) for s in S], 0)
    h = det([C.prep(hu[s["id"]][0]) for s in S]); b = det([C.prep(es[s["id"]][0]) for s in S])
    raw["sentences"][split]["T4.p_real[xlsr-deepfake]"] = {"human": float(np.mean(h)), "baseline": float(np.mean(b)),
                                                          "auc": auc(h, b), "dir": +1}
    print(split, raw["sentences"][split]["T4.p_real[xlsr-deepfake]"])
# 合理性检查：种子引擎 g0（开发集固定子集 30 句）
S = [s for s in sents if s["split"] == "dev"][:30]
e = EngineRunner(os.path.join(C.REPO, "params", "g0.json"))
g = e.synth([(s["id"], "text", s["text"]) for s in S], 0); e.close()
hu = HumanRunner().synth([(s["id"], "utt", s["human_utt"]) for s in S], 0)
chk = {}
for d in ("aasist", "w2v-deepfake", "xlsr-deepfake"):
    m = M.get("det", d)
    chk[d] = {"human": float(np.mean(m([C.prep(hu[s["id"]][0]) for s in S]))),
              "g0": float(np.mean(m([C.prep(g[s["id"]][0]) for s in S])))}
raw["detector_sanity_g0"] = chk
print(chk)
json.dump(raw, open(raw_p, "w"), ensure_ascii=False, indent=1)
