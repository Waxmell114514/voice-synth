"""姿态目标与时间线（g0：查表 + 线性插值）。

输入：带调拼音音节和停顿记号序列。输出：按控制帧（约 1 ms）的
  A[nf, N]    口腔面积函数（声门→唇，cm²）
  Avp[nf]     软腭口面积（cm²）
  nidx[nf]    湍流噪声注入段号（-1 表示无）
  ngain[nf]   湍流噪声增益
  voice[nf]   发声幅度（0–1）
  asp[nf]     声门送气噪声增益
  f0[nf]      基频（Hz）
辅音 = 叠加在后接元音面积函数上的收紧（预期性协同发音）。
所有数值来自 params（见 params/schema.json 与 specs/g0-seed.md）。
"""
import numpy as np
from .pinyin import parse

# 韵母 → 元音目标序列；"N" = 舌尖鼻韵尾，"NG" = 舌根鼻韵尾
FINALS = {
    "a": ["a"], "o": ["o"], "e": ["e"], "i": ["i"], "u": ["u"], "v": ["v"],
    "ii": ["ii"], "iii": ["iii"], "er": ["er"], "ê": ["E"],
    "ai": ["a", "i"], "ei": ["E", "i"], "ao": ["a", "u"], "ou": ["o", "u"],
    "an": ["a", "N"], "en": ["schwa", "N"], "ang": ["a", "NG"], "eng": ["schwa", "NG"], "ong": ["u", "NG"],
    "ia": ["i", "a"], "ie": ["i", "E"], "iao": ["i", "a", "u"], "iou": ["i", "o", "u"], "io": ["i", "o"],
    "ian": ["i", "E", "N"], "in": ["i", "N"], "iang": ["i", "a", "NG"], "ing": ["i", "NG"], "iong": ["i", "u", "NG"],
    "ua": ["u", "a"], "uo": ["u", "o"], "uai": ["u", "a", "i"], "uei": ["u", "E", "i"],
    "uan": ["u", "a", "N"], "uen": ["u", "schwa", "N"], "uang": ["u", "a", "NG"], "ueng": ["u", "schwa", "NG"],
    "ve": ["v", "E"], "van": ["v", "E", "N"], "vn": ["v", "N"],
}
VOWEL_TARGETS = ["a", "o", "e", "i", "u", "v", "E", "schwa", "ii", "iii", "er"]

# 声母：部位类、方式
INIT = {
    "b": ("lab", "stop_u"), "p": ("lab", "stop_a"), "m": ("lab", "nasal"), "f": ("labdent", "fric"),
    "d": ("alv", "stop_u"), "t": ("alv", "stop_a"), "n": ("alv", "nasal"), "l": ("alv", "lateral"),
    "g": ("vel", "stop_u"), "k": ("vel", "stop_a"), "h": ("vel", "fric_h"),
    "j": ("pal", "affr_u"), "q": ("pal", "affr_a"), "x": ("pal", "fric"),
    "zh": ("ret", "affr_u"), "ch": ("ret", "affr_a"), "sh": ("ret", "fric"), "r": ("ret", "approx"),
    "z": ("dent", "affr_u"), "c": ("dent", "affr_a"), "s": ("dent", "fric"),
}
PLACES = ["lab", "labdent", "dent", "alv", "ret", "pal", "vel"]
FRIC_PLACES = ["labdent", "dent", "ret", "pal", "vel"]
CHAO = {1: [5, 5], 2: [3, 5], 3: [2, 1, 4], 4: [5, 1]}
NEUTRAL_AFTER = {1: 2, 2: 3, 3: 4, 4: 1, 5: 2}


def constrict(base, place_frac, width, area, mode="min"):
    """在距唇 place_frac（占声道长度的比例）处施加宽度 width（段数，高斯）的收紧。"""
    N = len(base)
    c = (N - 1) * (1.0 - place_frac)
    k = np.arange(N)
    m = np.exp(-0.5 * ((k - c) / max(width, 0.3)) ** 2)
    tgt = base * (1 - m) + area * m
    return np.minimum(base, tgt) if mode == "min" else tgt


def place_index(P, place):
    N = P["area_a"].shape[0]
    c = int(round((N - 1) * (1.0 - P[f"place_{place}"])))
    return int(np.clip(c, 0, N - 2))


class Timeline:
    def __init__(self, P, frame_s):
        self.P = P
        self.fs = frame_s
        self.keys = []   # (t, A, Avp, nidx, ngain, voice, asp)
        self.f0k = []    # (t, chao_level)

    def key(self, t, A, Avp=0.0, nidx=-1, ngain=0.0, voice=1.0, asp=0.0):
        self.keys.append((t, np.asarray(A, float), float(Avp), int(nidx), float(ngain), float(voice), float(asp)))

    def render(self, total):
        P = self.P
        nf = max(2, int(np.ceil(total / self.fs)) + 1)
        t = np.arange(nf) * self.fs
        K = sorted(self.keys, key=lambda x: x[0])
        kt = np.array([k[0] for k in K])
        N = K[0][1].shape[0]
        A = np.empty((nf, N))
        KA = np.stack([k[1] for k in K])
        for j in range(N):
            A[:, j] = np.interp(t, kt, KA[:, j])
        Avp = np.interp(t, kt, [k[2] for k in K])
        voice = np.interp(t, kt, [k[5] for k in K])
        asp = np.interp(t, kt, [k[6] for k in K])
        ngain = np.interp(t, kt, [k[4] for k in K])
        # 噪声位置：取最近的有噪声关键帧（分段常数）
        idx = np.searchsorted(kt, t, side="right") - 1
        idx = np.clip(idx, 0, len(K) - 1)
        nidx = np.array([K[i][3] for i in idx], dtype=np.int64)
        nxt = np.clip(idx + 1, 0, len(K) - 1)
        nidx = np.where(nidx < 0, np.array([K[i][3] for i in nxt]), nidx)
        ngain = np.where(nidx < 0, 0.0, ngain)
        # F0
        if self.f0k:
            ft = np.array([x[0] for x in self.f0k]); fl = np.array([x[1] for x in self.f0k])
            lev = np.interp(t, ft, fl)
        else:
            lev = np.full(nf, 3.0)
        st = (lev - 3.0) / 4.0 * P["f0_range_st"] + P["declination_st_per_s"] * t
        f0 = P["f0_base_hz"] * 2.0 ** (st / 12.0)
        A = np.maximum(A, P["min_area"])
        return A, Avp, nidx, ngain, voice, asp, f0


def plan(tokens, P, frame_s):
    """tokens：拼音音节或 '<sp>' / '<sil>'。返回 Timeline 与总时长（秒）。"""
    tl = Timeline(P, frame_s)
    ms = 1e-3
    V = {v: np.asarray(P[f"area_{v}"], float) for v in VOWEL_TARGETS}
    neutral = V["schwa"]
    # 解析并做三声连读变调（同一停顿段内）
    syls = []
    for tok in tokens:
        if tok in ("<sp>", "<sil>"):
            syls.append(tok); continue
        p = parse(tok)
        if p is not None and p[1] in FINALS:
            syls.append(list(p))
    for i in range(len(syls) - 1):
        a, b = syls[i], syls[i + 1]
        if isinstance(a, list) and isinstance(b, list) and a[2] == 3 and b[2] == 3:
            a[2] = 2
    t = P["lead_sil_ms"] * ms
    tl.key(0.0, neutral, voice=0.0)
    tl.key(t, neutral, voice=0.0)
    prev_tone = 5
    phrase_syls = [s for s in syls if isinstance(s, list)]
    last_idx = {}
    # 每个停顿段最后一个音节做延长
    seg_last = set()
    for i, s in enumerate(syls):
        if isinstance(s, list) and (i + 1 == len(syls) or not isinstance(syls[i + 1], list)):
            seg_last.add(i)
    for i, s in enumerate(syls):
        if s == "<sp>" or s == "<sil>":
            d = (P["pause_short_ms"] if s == "<sp>" else P["pause_long_ms"]) * ms
            tl.key(t + 0.02, neutral, voice=0.0)
            t += d
            tl.key(t, neutral, voice=0.0)
            prev_tone = 5
            continue
        ini, fin, tone = s
        D = P["syl_dur_ms"] * ms * (P["final_lengthening"] if i in seg_last else 1.0)
        if tone == 5:
            D *= P["neutral_dur_ratio"]
        t = _syllable(tl, P, V, t, D, ini, fin, tone, prev_tone, i in seg_last)
        prev_tone = tone
    t += P["tail_sil_ms"] * ms
    tl.key(t, neutral, voice=0.0)
    return tl, t


def _syllable(tl, P, V, t0, D, ini, fin, tone, prev_tone, is_last):
    ms = 1e-3
    tg = FINALS[fin]
    vtg = [x for x in tg if x not in ("N", "NG")]
    coda = tg[-1] if tg[-1] in ("N", "NG") else None
    first = V[vtg[0]]
    t = t0
    # ---------------- 声母
    if ini:
        place, manner = INIT[ini]
        pf, w = P[f"place_{place}"], P[f"cwidth_{place}"]
        ci = place_index(P, place)
        if manner in ("stop_u", "stop_a", "affr_u", "affr_a"):
            clo = constrict(first, pf, w, P["closure_area"])
            asp_ = manner.endswith("_a")
            dc = P["dur_closure_asp_ms" if asp_ else "dur_closure_unasp_ms"] * ms
            tl.key(t, clo, voice=0.0)
            t += dc
            tl.key(t, clo, voice=0.0)
            if manner.startswith("stop"):
                # 除阻：爆破噪声 + （送气）
                vot = P["vot_asp_ms" if asp_ else "vot_unasp_ms"] * ms
                rel = constrict(first, pf, w, P["release_area"])
                tl.key(t + 0.001, rel, nidx=ci, ngain=P["burst_gain"], voice=0.0,
                       asp=P["asp_noise_gain"] if asp_ else 0.0)
                t += vot
                tl.key(t, first, voice=0.0, asp=P["asp_noise_gain"] if asp_ else 0.0)
            else:
                fr = constrict(first, pf, w, P["fric_area"])
                dfr = P["dur_affr_fric_asp_ms" if asp_ else "dur_affr_fric_unasp_ms"] * ms
                g = P[f"fric_gain_{place}"]
                tl.key(t + 0.001, fr, nidx=ci, ngain=g, voice=0.0, asp=P["asp_noise_gain"] if asp_ else 0.0)
                t += dfr
                tl.key(t, fr, nidx=ci, ngain=g * 0.5, voice=0.0, asp=P["asp_noise_gain"] if asp_ else 0.0)
                t += 0.01
                tl.key(t, first, voice=0.0)
        elif manner in ("fric", "fric_h"):
            fr = constrict(first, pf, w, P["fric_area"] if manner == "fric" else P["fric_area_h"])
            g = P[f"fric_gain_{place}"]
            dfr = P["dur_fric_ms"] * ms
            tl.key(t, fr, nidx=ci, ngain=g, voice=0.0, asp=P["asp_noise_gain"] if manner == "fric_h" else 0.0)
            t += dfr
            tl.key(t, fr, nidx=ci, ngain=g, voice=0.0, asp=P["asp_noise_gain"] if manner == "fric_h" else 0.0)
            t += 0.01
            tl.key(t, first, voice=0.0)
        elif manner == "nasal":
            clo = constrict(first, pf, w, P["closure_area"])
            dn = P["dur_nasal_init_ms"] * ms
            tl.key(t, clo, Avp=P["velum_open_area"], voice=1.0)
            t += dn
            tl.key(t, clo, Avp=P["velum_open_area"], voice=1.0)
        else:  # lateral / approx
            ap = constrict(first, pf, w, P["approx_area_l" if manner == "lateral" else "approx_area_r"])
            da = P["dur_approx_ms"] * ms
            tl.key(t, ap, voice=1.0)
            t += da
            tl.key(t, ap, voice=1.0)
    # ---------------- 韵母
    rest = t0 + D - t
    rest = max(rest, 0.06)
    vdur = rest * (1.0 - (P["coda_frac"] if coda else 0.0))
    n = len(vtg)
    for k, v in enumerate(vtg):
        # 每个目标在其时间段中点达到，首尾目标保持
        tk = t + vdur * (k + 0.5) / n
        if k == 0:
            tl.key(t + min(0.03, vdur * 0.25), V[v], voice=1.0)
        tl.key(tk, V[v], voice=1.0)
    tend = t + vdur
    tl.key(tend, V[vtg[-1]], voice=1.0)
    if coda:
        place = "alv" if coda == "N" else "vel"
        clo = constrict(V[vtg[-1]], P[f"place_{place}"], P[f"cwidth_{place}"], P["closure_area"])
        tl.key(tend + 0.02, clo, Avp=P["velum_open_area"], voice=1.0)
        tend = t + rest
        tl.key(tend, clo, Avp=P["velum_open_area"], voice=1.0)
    # 音节结束：发声渐弱（下一个音节的首帧会覆盖）
    # ---------------- 声调
    lev = list(CHAO.get(tone, [NEUTRAL_AFTER.get(prev_tone, 2)] * 2))
    if tone == 3 and not is_last:
        lev = [2, 1]  # 半上
    if tone == 5:
        lev = [NEUTRAL_AFTER.get(prev_tone, 2), NEUTRAL_AFTER.get(prev_tone, 2) - 0.5]
    vs = t
    for j, L in enumerate(lev):
        tl.f0k.append((vs + (tend - vs) * (j / max(len(lev) - 1, 1)) * 0.9 + 0.05 * (tend - vs), float(L)))
    return t0 + D if t0 + D > tend else tend
