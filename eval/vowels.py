"""T1 用的元音共振峰测量。

真人录音：用 SenseVoice 的字级起点时间戳定位音节，只取韵母恰为单元音
（a o e i u ü）且被正确识别的音节，在 [起点+35%, 起点+75%] 区间测 F1–F3 中位数。
合成语音：孤立音节，取有声段中间 40%。
"""
import numpy as np
from common import toned, split_syl, formants_mid, han_only

VOWELS = ["a", "o", "e", "i", "u", "v"]           # v = ü
VOWEL_PINYIN = {"a": "a1", "o": "o1", "e": "e1", "i": "yi1", "u": "wu1", "v": "yu1"}
VOWEL_HANZI = {"a": "啊", "o": "喔", "e": "婀", "i": "衣", "u": "乌", "v": "迂"}
# 只用这些声母后的单元音（排除舌尖元音 zhi/zi 等，排除 ê 和 er）
_OK_INI = {"a": "∅ b p m f d t n l g k h z c s zh ch sh",
           "o": "∅ b p m f",
           "e": "∅ d t n l g k h z c s zh ch sh r",
           "i": "∅ b p m d t n l j q x",
           "u": "∅ b p m f d t n l g k h z c s zh ch sh r",
           "v": "∅ n l j q x"}
_OK_INI = {k: set(v.split()) for k, v in _OK_INI.items()}


def vowel_of(p):
    ini, fin, tone = split_syl(p)
    base = p[:-1]
    if base in ("yi",):
        return "i"
    if base in ("wu",):
        return "u"
    if base in ("yu",):
        return "v"
    if fin in ("ü",):
        fin = "v"
    if fin in ("u",) and ini in ("j", "q", "x"):
        fin = "v"
    if fin in VOWELS and ini in _OK_INI[fin]:
        return fin
    return None


def human_vowel_tokens(x, sr, text, asr_tokens, asr_times):
    """返回 [(vowel, F1,F2,F3)]。只在 ASR 字与参考字一致的位置取样。"""
    ref = han_only(text)
    py = toned(ref)
    out = []
    toks = list(asr_tokens)
    if len(toks) != len(ref) or "".join(toks) != ref:
        # 只用完全一致的句子，避免时间戳错位
        return out
    end = len(x) / sr
    for k, ch in enumerate(ref):
        v = vowel_of(py[k])
        if v is None:
            continue
        t0 = asr_times[k]
        t1 = asr_times[k + 1] if k + 1 < len(asr_times) else min(end, t0 + 0.3)
        d = t1 - t0
        if not (0.08 <= d <= 0.5):
            continue
        f = formants_mid(x, sr, t0 + 0.35 * d, t0 + 0.75 * d)
        if f is not None:
            out.append((v, *f))
    return out


def synth_vowel_formants(x, sr):
    """孤立元音：能量 > -20 dB 的段落的中间 40%。"""
    hop = int(0.01 * sr)
    n = len(x) // hop
    if n < 5:
        return None
    e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(n)])
    db = 20 * np.log10(e / (e.max() + 1e-12) + 1e-12)
    idx = np.where(db > -20)[0]
    if len(idx) < 4:
        return None
    a, b = idx[0] * 0.01, (idx[-1] + 1) * 0.01
    d = b - a
    return formants_mid(x, sr, a + 0.3 * d, a + 0.7 * d)
