"""评估器公共函数：拼音化、对齐、混淆矩阵、音频预处理、声学测量。"""
import os, re, json, collections
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
DATA = os.path.join(ROOT, "data")

# ------------------------------------------------------------------ 拼音
from pypinyin import lazy_pinyin, Style
from pypinyin.style._utils import get_initials, get_finals

HAN = re.compile(r"[一-鿿]")


def han_only(s):
    return "".join(HAN.findall(s))


def toned(text):
    return [p if p[-1].isdigit() else p + "5"
            for p in lazy_pinyin(text, style=Style.TONE3, neutral_tone_with_five=True)]


def split_syl(p):
    """'zhuang1' -> ('zh', 'uang', '1')；声母为空记 '∅'。v/ü 统一为 v。"""
    tone = p[-1] if p[-1].isdigit() else "5"
    base = p[:-1] if p[-1].isdigit() else p
    ini = get_initials(base, strict=True) or "∅"      # y、w 不算声母
    fin = get_finals(base, strict=True) or base
    return ini, fin, tone


def levenshtein_align(ref, hyp):
    """返回对齐对列表 (r, h)，缺失一侧为 None。"""
    n, m = len(ref), len(hyp)
    D = np.zeros((n + 1, m + 1), dtype=np.int32)
    D[:, 0] = np.arange(n + 1); D[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = min(D[i - 1, j] + 1, D[i, j - 1] + 1, D[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j, out = n, m, []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and D[i, j] == D[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            out.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and D[i, j] == D[i - 1, j] + 1:
            out.append((i - 1, None)); i -= 1
        else:
            out.append((None, j - 1)); j -= 1
    return out[::-1], int(D[n, m])


def edit_distance(ref, hyp):
    return levenshtein_align(ref, hyp)[1]


class Confusions:
    """声母、韵母、声调混淆计数（只在对齐的替换/正确位置上统计；删除记为 '<del>'）。"""

    def __init__(self):
        self.ini = collections.Counter(); self.fin = collections.Counter(); self.tone = collections.Counter()

    def add(self, ref_py, hyp_py):
        rb = [p[:-1] for p in ref_py]; hb = [p[:-1] for p in hyp_py]
        pairs, _ = levenshtein_align(rb, hb)
        for i, j in pairs:
            if i is None:
                continue
            ri, rf, rt = split_syl(ref_py[i])
            if j is None:
                self.ini[(ri, "<del>")] += 1; self.fin[(rf, "<del>")] += 1; self.tone[(rt, "<del>")] += 1
            else:
                hi, hf, ht = split_syl(hyp_py[j])
                self.ini[(ri, hi)] += 1; self.fin[(rf, hf)] += 1; self.tone[(rt, ht)] += 1

    @staticmethod
    def _mat(c):
        d = collections.defaultdict(dict)
        for (r, h), n in sorted(c.items()):
            d[r][h] = n
        return d

    def export(self, top_errors=25):
        def errs(c):
            e = [(r, h, n) for (r, h), n in c.items() if r != h]
            tot = collections.Counter()
            for (r, h), n in c.items():
                tot[r] += n
            e.sort(key=lambda x: -x[2])
            return [{"ref": r, "hyp": h, "count": n, "rate": round(n / tot[r], 3)} for r, h, n in e[:top_errors]]
        return {"tone_matrix": self._mat(self.tone),
                "initial_matrix": self._mat(self.ini), "final_matrix": self._mat(self.fin),
                "top_initial_errors": errs(self.ini), "top_final_errors": errs(self.fin)}


def syllable_scores(ref_py, hyp_py):
    """音节（不计声调）对齐：返回 (N, 音节错误数, 声调正确数)。
    声调正确：对齐位置上音节相同且声调相同 —— 即“该音节被正确识别且声调也对”。"""
    rb = [p[:-1] for p in ref_py]; hb = [p[:-1] for p in hyp_py]
    pairs, dist = levenshtein_align(rb, hb)
    tone_ok = sum(1 for i, j in pairs if i is not None and j is not None
                  and rb[i] == hb[j] and ref_py[i][-1] == hyp_py[j][-1])
    return len(ref_py), dist, tone_ok


# ------------------------------------------------------------------ 音频预处理（所有系统一致）
def trim_silence(x, sr=16000, thr_db=-40.0, margin=0.1):
    if len(x) == 0:
        return x
    hop = int(0.01 * sr)
    n = max(1, len(x) // hop)
    e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(n)])
    db = 20 * np.log10(e / (e.max() + 1e-12) + 1e-12)
    idx = np.where(db > thr_db)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] * hop - int(margin * sr)); b = min(len(x), (idx[-1] + 1) * hop + int(margin * sr))
    return x[a:b]


def loudness_norm(x, target_db=-23.0):
    if len(x) == 0 or not np.isfinite(x).all() or np.abs(x).max() == 0:
        return x.astype(np.float32)
    a = np.abs(x)
    act = x[a > 0.02 * a.max()]
    r = np.sqrt(np.mean(act ** 2)) + 1e-12
    y = x * (10 ** (target_db / 20) / r)
    pk = np.abs(y).max()
    if pk > 0.99:
        y = y * 0.99 / pk
    return y.astype(np.float32)


def prep(x):
    """神经评估器的统一输入：16 kHz，裁静音，响度归一。"""
    return loudness_norm(trim_silence(x))


# ------------------------------------------------------------------ 声学测量
def formants_mid(x, sr, t0, t1, max_formant=5500.0):
    """[t0,t1] 段内 F1-F3 中位数（Praat Burg）。返回 None 表示失败。"""
    import parselmouth
    seg = x[int(t0 * sr):int(t1 * sr)]
    if len(seg) < int(0.04 * sr):
        return None
    snd = parselmouth.Sound(seg.astype(np.float64), sampling_frequency=sr)
    fm = snd.to_formant_burg(time_step=0.005, max_number_of_formants=5,
                             maximum_formant=max_formant, window_length=0.025, pre_emphasis_from=50.0)
    ts = np.arange(0.0125, snd.duration - 0.0125, 0.005)
    vals = []
    for t in ts:
        f = [fm.get_value_at_time(k, t) for k in (1, 2, 3)]
        if all(np.isfinite(f)):
            vals.append(f)
    if len(vals) < 3:
        return None
    return np.median(np.array(vals), axis=0)


def f0_track(x, sr):
    import parselmouth
    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=sr)
    p = snd.to_pitch_ac(time_step=0.01, pitch_floor=60.0, pitch_ceiling=600.0)
    f = p.selected_array["frequency"]
    return f[f > 0]


def f0_norm_semitones(x, sr):
    f = f0_track(x, sr)
    if len(f) < 10:
        return np.array([])
    st = 12 * np.log2(f)
    return st - np.median(st)


def mean_syllable_duration(x, sr, n_syl):
    """有声活动时长 / 音节数（去首尾静音后，再去掉 >150 ms 的内部停顿）。"""
    hop = int(0.01 * sr)
    n = len(x) // hop
    if n == 0 or n_syl == 0:
        return float("nan")
    e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(n)])
    db = 20 * np.log10(e / (e.max() + 1e-12) + 1e-12)
    act = db > -35
    idx = np.where(act)[0]
    if len(idx) == 0:
        return float("nan")
    act = act[idx[0]:idx[-1] + 1]
    # 去掉长停顿
    dur, run = 0, 0
    for a in act:
        if a:
            if run and run <= 15:
                dur += run
            run = 0; dur += 1
        else:
            run += 1
    return dur * 0.01 / n_syl


def frechet(mu1, s1, mu2, s2):
    from scipy.linalg import sqrtm
    diff = mu1 - mu2
    cs = sqrtm(s1 @ s2)
    if np.iscomplexobj(cs):
        cs = cs.real
    return float(diff @ diff + np.trace(s1 + s2 - 2 * cs))


def wasserstein1(a, b):
    from scipy.stats import wasserstein_distance
    return float(wasserstein_distance(a, b))


def jload(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))
