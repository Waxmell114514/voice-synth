"""共振峰带宽与频谱倾斜诊断（g003-e02，specs/g003-e02.md；非正式检查，不进 eval/）。

  python tools/bandwidth_tilt.py <params.json> [--root <引擎树>] [--override wall_loss=0.002 ...]
                                 [--selftest] [--no-selftest] [--out x.json]

只读 <root>/engine/ 的代码和给定参数文件，不读 eval/。
- 带宽（方法 A，§2.1）：静态面积、软腭关闭、零输入时 kl_run 是线性时不变映射 x_{t+1} = M x_t。
  从每个单位状态向量跑 1 个采样得到 M 的一列；eig(M) 即全部极点：
  F = ∠z·fs_sim/2π，B = −fs_sim·ln|z|/π。fs_sim 取引擎 sim_rate() 的返回值。
- 交叉校验（方法 B）：声门冲激响应去掉 N 采样纯延迟后做协方差 LPC（阶数 = 状态维数），
  F1–F3、B1–B3 与方法 A 相差 > 0.5% 时报错退出。
- 倾斜量（§4）：合成孤立元音（seed 0），40 ms Hamming 窗 ×3（中点 −20/0/+20 ms），不预加重，
  H1−H2、H1−A1、A1−A3、H1−A3 的原始值，以及用方法 A 的 F1–F4、B1–B4 按 Iseli & Alwan 2004
  校正后的值。
- --selftest：§3.2 用例 1–6 与 §4.4 用例 7–8，任一失败退出码 1。默认在正式输出前也跑一遍
  （--no-selftest 跳过）。
输出 JSON：数值保留 6 位有效数字，key 排序固定；同一输入两次运行逐字节相同。
"""
import os, sys, json, argparse, hashlib, inspect, subprocess

import numpy as np

HERE_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOWELS = ["a", "o", "e", "i", "u", "v"]
SYLL = {"a": "a1", "o": "o1", "e": "e1", "i": "yi1", "u": "wu1", "v": "yu1"}
FMIN, FMAX, B_NONFORMANT = 50.0, 5000.0, 1500.0
FS_AUDIO = 22050
NFFT = 1 << 16
KNOWN_ARGS = {"n", "block", "A", "An", "Avp", "kv", "ug", "noise", "nidx", "ngain", "r_g", "r_lip", "r_nose",
              "mu", "f", "b", "fn", "bn", "want_energy", "rad_kappa", "length_cm", "w", "kappa_bl", "dx_cm"}


# ------------------------------------------------------------------ 引擎树
class Engine:
    """从 root 导入 engine.*（清掉已导入的 engine 模块，做法同 tools/dynamic_t0_check.py）。"""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        for m in [k for k in list(sys.modules) if k == "engine" or k.startswith("engine.")]:
            del sys.modules[m]
        sys.path.insert(0, self.root)
        import engine.tract.kl as KL
        import engine.synth as SY
        import engine.params_io as PIO
        import engine.source.lf as LF
        sys.path.remove(self.root)
        self.KL, self.SY, self.PIO, self.LF = KL, SY, PIO, LF
        self.N = SY.N_SECT
        fn = getattr(KL.kl_run, "py_func", KL.kl_run)
        self.argnames = list(inspect.signature(fn).parameters)
        bad = [a for a in self.argnames if a not in KNOWN_ARGS]
        if bad:
            raise SystemExit(f"kl_run 有不认识的参数 {bad}，不猜默认值（specs/g003-e02.md §2.3）")
        self.has_w = "w" in self.argnames
        sch = {p["name"] for p in PIO.load_schema()["params"]}
        self.schema_names = sch

    def commit(self):
        def git(*a):
            try:
                return subprocess.run(["git", "-C", self.root] + list(a), capture_output=True, text=True,
                                      timeout=30).stdout.strip()
            except Exception:
                return ""
        return {"commit": git("rev-parse", "HEAD"),
                "engine_dirty": bool(git("status", "--porcelain", "--", "engine"))}

    def kl(self, n, A, ug, term, f, b, w):
        """按参数名调用 kl_run。term: r_g, r_lip, mu, L, kv, rad_kappa, kappa_bl。"""
        N = self.N
        val = {"n": n, "block": n, "A": np.ascontiguousarray(np.asarray(A, float)[None, :]),
               "An": np.full(8, 1.0), "Avp": np.zeros(1), "kv": int(term["kv"]), "ug": ug, "noise": np.zeros(n),
               "nidx": np.full(1, -1, dtype=np.int64), "ngain": np.zeros(1),
               "r_g": float(term["r_g"]), "r_lip": float(term["r_lip"]), "r_nose": 0.9, "mu": float(term["mu"]),
               "f": f, "b": b, "fn": np.zeros(8), "bn": np.zeros(8), "want_energy": False,
               "rad_kappa": float(term.get("rad_kappa", 0.0)), "length_cm": float(term["L"]), "w": w,
               "kappa_bl": float(term.get("kappa_bl", 0.0)), "dx_cm": float(term["L"]) / N}
        return self.KL.kl_run(*[val[a] for a in self.argnames])

    def fs_sim(self, L):
        return float(self.KL.sim_rate(L, self.N, FS_AUDIO)[0])


def terminals(E, P):
    t = {"r_g": P["r_glottis"], "r_lip": P["r_lip"], "mu": P["wall_loss"], "L": P["tract_length_cm"],
         "kv": int(np.clip(round(P["velum_pos_frac"] * (E.N - 1)), 1, E.N - 3))}
    if "rad_kappa" in E.argnames:
        if "rad_kappa" not in P:
            raise SystemExit("kl_run 需要 rad_kappa，但 schema 中没有")
        t["rad_kappa"] = P["rad_kappa"]
    if "kappa_bl" in E.argnames:
        if "bl_loss_kappa" not in P:
            raise SystemExit("kl_run 需要 kappa_bl，但 schema 中没有 bl_loss_kappa")
        t["kappa_bl"] = P["bl_loss_kappa"]
    return t


# ------------------------------------------------------------------ 方法 A：状态转移矩阵特征值
def step_matrix(E, A, term):
    N = E.N
    S = 2 * N + (1 if E.has_w else 0)
    M = np.zeros((S, S))
    for j in range(S):
        f = np.zeros(N); b = np.zeros(N); w = np.zeros(1)   # kl_run 就地修改状态，每列新建
        if j < N:
            f[j] = 1.0
        elif j < 2 * N:
            b[j - N] = 1.0
        else:
            w[0] = 1.0
        E.kl(1, A, np.zeros(1), term, f, b, w)
        M[:, j] = np.concatenate([f, b] + ([w] if E.has_w else []))
    return M


def poles_from_z(z, fs):
    z = z[np.imag(z) > 1e-12]
    F = np.angle(z) * fs / (2 * np.pi)
    B = -fs * np.log(np.abs(z)) / np.pi
    o = np.argsort(F)
    F, B = F[o], B[o]
    m = (F > FMIN) & (F < FMAX)
    return F[m], B[m]


def formants(F, B, k=3):
    sel = B <= B_NONFORMANT
    return F[sel][:k], B[sel][:k]


def method_a(E, A, term):
    fs = E.fs_sim(term["L"])
    z = np.linalg.eigvals(step_matrix(E, A, term))
    F, B = poles_from_z(z, fs)
    return F, B, fs


# ------------------------------------------------------------------ 方法 B：冲激响应 + 协方差 LPC
def method_b(E, A, term, n=8192, nfit=2000):
    N = E.N
    fs = E.fs_sim(term["L"])
    ug = np.zeros(n); ug[0] = 1.0
    ul = E.kl(n, A, ug, term, np.zeros(N), np.zeros(N), np.zeros(1))[0]
    h = np.asarray(ul)[N:N + nfit]                     # 去掉 N 采样纯延迟
    p = 2 * N + (1 if E.has_w else 0)
    X = np.array([h[p - k - 1:len(h) - k - 1] for k in range(p)]).T
    a = np.linalg.lstsq(X, h[p:], rcond=None)[0]
    z = np.roots(np.concatenate([[1.0], -a]))
    return poles_from_z(z, fs)


def cross_check(Fa, Ba, Fb, Bb):
    """方法 B 中与方法 A 的 F1–F3 最近的极点，返回最大相对差。"""
    worst = 0.0
    fa, ba = formants(Fa, Ba)
    for f, b in zip(fa, ba):
        j = int(np.argmin(np.abs(Fb - f)))
        worst = max(worst, abs(Fb[j] - f) / f, abs(Bb[j] - b) / b if b > 0 else abs(Bb[j] - b))
    return worst


# ------------------------------------------------------------------ 倾斜量
def spectrum_db(seg):
    X = np.abs(np.fft.rfft(seg * np.hamming(len(seg)), NFFT))
    return 20 * np.log10(X + 1e-300), FS_AUDIO / NFFT


def parabolic_peak(S, df, lo_hz, hi_hz):
    lo = max(1, int(np.floor(lo_hz / df))); hi = min(len(S) - 2, int(np.ceil(hi_hz / df)))
    j = lo + int(np.argmax(S[lo:hi + 1]))
    a, b, c = S[j - 1], S[j], S[j + 1]
    den = a - 2 * b + c
    d = 0.5 * (a - c) / den if den != 0 else 0.0
    return (j + d) * df, b - 0.25 * (a - c) * d


def f0_estimate(seg, S, df):
    x = seg - seg.mean()
    r = np.correlate(x, x, "full")[len(x) - 1:]
    lo, hi = int(FS_AUDIO / 500), int(FS_AUDIO / 100)
    k = lo + int(np.argmax(r[lo:hi + 1]))
    f0 = FS_AUDIO / k
    f1, _ = parabolic_peak(S, df, 0.8 * f0, 1.2 * f0)
    return f1


def iseli_corr(f, F, B):
    """Iseli & Alwan 2004：共振峰 (F, B) 对频率 f 处谐波的抬升（dB），fs = 22050。"""
    r = np.exp(-np.pi * B / FS_AUDIO); wi = 2 * np.pi * F / FS_AUDIO; w = 2 * np.pi * f / FS_AUDIO
    return (20 * np.log10(1 + r * r - 2 * r * np.cos(wi))
            - 10 * np.log10(1 + r * r - 2 * r * np.cos(wi + w))
            - 10 * np.log10(1 + r * r - 2 * r * np.cos(wi - w)))


def harmonics(seg, F=None, B=None):
    """一个 40 ms 段：F0、H1、H2；给了 F、B 时另求 A1、A3 及校正值。"""
    S, df = spectrum_db(seg)
    f0 = f0_estimate(seg, S, df)
    def H(k):
        return parabolic_peak(S, df, k * f0 - 0.2 * f0, k * f0 + 0.2 * f0)
    fh1, h1 = H(1); fh2, h2 = H(2)
    out = {"F0": f0, "H1": h1, "H2": h2}
    if F is None:
        return out
    def A_near(Fx):
        ks = [k for k in range(1, int(FS_AUDIO / 2 / f0)) if abs(k * f0 - Fx) <= f0]
        best = max((H(k) for k in ks), key=lambda t: t[1])
        return best
    fa1, a1 = A_near(F[0]); fa3, a3 = A_near(F[2])
    def corr(f, idx):
        return float(sum(iseli_corr(f, F[i], B[i]) for i in idx if i < len(F)))
    allf = range(len(F))
    out.update({"A1": a1, "A3": a3, "fA1": fa1, "fA3": fa3,
                "H1c": h1 - corr(fh1, allf), "H2c": h2 - corr(fh2, allf),
                "A1c": a1 - corr(fa1, [i for i in allf if i != 0]),
                "A3c": a3 - corr(fa3, [i for i in allf if i != 2])})
    return out


def windows(y):
    a = np.abs(y)
    idx = np.nonzero(a > 0.02 * a.max())[0]
    mid = (idx[0] + idx[-1]) // 2
    half = int(round(0.020 * FS_AUDIO))
    return [y[c - half:c + half] for c in (mid - half, mid, mid + half)]


def tilt_measures(y, F, B):
    ms = [harmonics(s, F, B) for s in windows(y)]
    m = {k: float(np.mean([x[k] for x in ms])) for k in ms[0]}
    return {"F0": m["F0"],
            "raw": {"H1-H2": m["H1"] - m["H2"], "H1-A1": m["H1"] - m["A1"],
                    "A1-A3": m["A1"] - m["A3"], "H1-A3": m["H1"] - m["A3"]},
            "corrected": {"H1*-H2*": m["H1c"] - m["H2c"], "H1*-A1*": m["H1c"] - m["A1c"],
                          "A1*-A3*": m["A1c"] - m["A3c"], "H1*-A3*": m["H1c"] - m["A3c"]},
            "harmonic_freqs_hz": {"A1": m["fA1"], "A3": m["fA3"]}}


def source_only_h1h2(E, rd, f0=220.0, L=15.0, dur=0.4):
    """用例 7：只有声源，F0 固定、无 jitter/shimmer，气流导数按 synth 的方式降采样到 22.05 kHz。"""
    from scipy.signal import resample_poly
    fs, up, down = E.KL.sim_rate(L, E.N, FS_AUDIO)
    n = int(dur * fs)
    du, _ = E.LF.glottal_source(np.full(n, f0), np.full(n, rd), np.ones(n), fs, np.random.default_rng(0))
    y = resample_poly(du, up, down)
    c = len(y) // 2; half = int(round(0.020 * FS_AUDIO))
    ms = [harmonics(y[x - half:x + half]) for x in (c - half, c, c + half)]
    return float(np.mean([m["H1"] - m["H2"] for m in ms]))


# ------------------------------------------------------------------ 主分析
def load(E, params_path, overrides):
    P = E.PIO.load_params(params_path)
    for k, v in overrides.items():
        if k not in P:
            raise SystemExit(f"--override {k}: schema 中没有这个参数")
        if np.ndim(P[k]) != 0:
            raise SystemExit(f"--override {k}: 只支持标量")
        P[k] = float(v)
    return P


def analyze(E, P):
    term = terminals(E, P)
    res = {}
    for v in VOWELS:
        A = np.maximum(np.asarray(P["area_" + v], float), P["min_area"])
        Fa, Ba, fs = method_a(E, A, term)
        Fb, Bb = method_b(E, A, term)
        dev = cross_check(Fa, Ba, Fb, Bb)
        if dev > 0.005:
            raise SystemExit(f"/{v}/ 方法 A 与方法 B 相差 {dev:.4%} > 0.5%")
        F3, B3 = formants(Fa, Ba)
        F4, B4 = formants(Fa, Ba, 4)
        y = np.asarray(E.SY.render([SYLL[v]], P, 0), float)
        t = tilt_measures(y, F4, B4)
        res[v] = {"F": F3.tolist(), "B": B3.tolist(), "B3/B1": float(B3[2] / B3[0]),
                  "F4": float(F4[3]) if len(F4) > 3 else None, "B4": float(B4[3]) if len(B4) > 3 else None,
                  "method_b_max_rel_dev": dev,
                  "poles_below_5k": [{"F": float(f), "B": float(b), "formant": bool(b <= B_NONFORMANT)}
                                     for f, b in zip(Fa, Ba)],
                  "tilt": t, "high_vowel_caveat": bool(F3[0] < 2 * t["F0"] + 100)}
    fs = E.fs_sim(term["L"])
    return {"fs_sim": fs, "bandwidth_floor_hz": -fs * np.log(1 - term["mu"]) / np.pi,
            "terminals": {k: v for k, v in term.items() if k != "kv"}, "vowels": res}


# ------------------------------------------------------------------ 自检
def selftest(E, params_path):
    out = []
    N = E.N
    base = {"kv": 1, "rad_kappa": 0.0, "kappa_bl": 0.0}

    def case(name, ok, **info):
        out.append(dict(info, case=name, pass_=bool(ok)))

    for cid, L in ((1, 15.0), (2, 17.5)):
        term = dict(base, r_g=1.0, r_lip=1.0, mu=0.01, L=L)
        A = np.full(N, 3.0)
        F, B, fs = method_a(E, A, term)
        want = -fs * np.log(0.99) / np.pi
        Fw = np.array([(2 * k - 1) * 350.0 / (4 * L / 100) for k in (1, 2, 3)])
        Fb, Bb = method_b(E, A, term)
        fb, bb = formants(Fb, Bb)
        errA = float(np.max(np.abs(B[:3] - want)) / want)
        errB = float(np.max(np.abs(bb - want)) / want)
        errF = float(np.max(np.abs(F[:3] - Fw) / Fw))
        case(cid, errA < 1e-6 and errB < 0.02 and errF < 1e-3, L_cm=L, fs_sim=fs, B_expected=want,
             B_method_a=B[:3].tolist(), B_method_b=bb.tolist(), F_method_a=F[:3].tolist(), F_expected=Fw.tolist(),
             rel_err_a=errA, rel_err_b=errB, rel_err_F=errF)
    term = dict(base, r_g=1.0, r_lip=1.0, mu=0.0, L=15.0)
    F, B, fs = method_a(E, np.full(N, 3.0), term)
    case(3, np.max(np.abs(B[:3])) < 1e-6, B_method_a=B[:3].tolist())
    term = dict(base, r_g=1.0, r_lip=0.9, mu=0.0, L=15.0)
    F, B, fs = method_a(E, np.full(N, 3.0), term)
    # 均匀管、一端 |r| = r_lip：往返 2N 采样衰减 r_lip，|z| = r_lip^{1/2N}，B = −(fs/2N)·ln r_lip/π = −(c/2L)·ln r_lip/π
    want = -(fs / (2 * N)) * np.log(0.9) / np.pi
    case(4, np.max(np.abs(B[:3] - want)) / want < 1e-6, B_expected=want, B_method_a=B[:3].tolist())
    P = E.PIO.load_params(params_path)
    L = P["tract_length_cm"]
    term = dict(base, r_g=1.0, r_lip=1.0, mu=0.01, L=L)
    A = np.maximum(np.asarray(P["area_i"], float), P["min_area"])
    F, B, fs = method_a(E, A, term)
    want = -fs * np.log(0.99) / np.pi
    case(5, np.max(np.abs(B - want)) / want < 1e-6, L_cm=L, B_expected=want, B_method_a=B[:3].tolist(),
         n_poles_checked=int(len(B)))
    termr = terminals(E, P)
    devs = {}
    for v in VOWELS:
        A = np.maximum(np.asarray(P["area_" + v], float), P["min_area"])
        Fa, Ba, _ = method_a(E, A, termr)
        Fb, Bb = method_b(E, A, termr)
        devs[v] = cross_check(Fa, Ba, Fb, Bb)
    case(6, max(devs.values()) < 0.005, max_rel_dev=devs)
    # 用例 7：只有声源。两层判据：
    #  (a) 工具正确性：音频测量值与引擎 lf_period 单周期傅里叶级数的精确 H1−H2 相差 ≤ 0.1 dB（全部 Rd）；
    #  (b) Fant 1995 式 (8)：−7.6 + 11.1·Rd，±1 dB。只对 Rd ≤ 1.1（含 e06 的 rd_modal）作通过条件；
    #      Rd = 2.0 时引擎的 Rd→(Ra,Rk,Rg) 换算本身就偏离式 (8)（精确级数也差约 −1.06 dB），
    #      这是引擎声源的性质而不是工具误差，只报告，记为 fant_within_1db。
    h7 = {}
    for rd in (0.5, 1.1, 2.0):
        got = source_only_h1h2(E, rd)
        p, _ = E.LF.lf_period(100000, rd)
        X = np.abs(np.fft.rfft(p))
        exact = 20 * np.log10(X[1] / X[2])
        fant = -7.6 + 11.1 * rd
        h7[rd] = {"H1-H2": got, "exact_fourier": exact, "tool_err": got - exact, "fant1995_eq8": fant,
                  "diff_vs_fant": got - fant, "fant_within_1db": abs(got - fant) <= 1.0}
    case(7, all(abs(x["tool_err"]) <= 0.1 for x in h7.values())
         and all(x["fant_within_1db"] for rd, x in h7.items() if rd <= 1.1),
         by_rd={str(k): x for k, x in h7.items()})
    # 用例 8：参数文件 /a/ 的校正 H1*−H2* 与只有声源时（同一 Rd）相差 < 1.5 dB
    Aa = np.maximum(np.asarray(P["area_a"], float), P["min_area"])
    Fa, Ba, _ = method_a(E, Aa, termr)
    F4, B4 = formants(Fa, Ba, 4)
    t = tilt_measures(np.asarray(E.SY.render(["a1"], P, 0), float), F4, B4)
    ref = source_only_h1h2(E, P["rd_modal"], f0=t["F0"], L=L)
    d8 = t["corrected"]["H1*-H2*"] - ref
    case(8, abs(d8) < 1.5, rd=P["rd_modal"], a_corrected_H1H2=t["corrected"]["H1*-H2*"],
         a_raw_H1H2=t["raw"]["H1-H2"], source_only_H1H2=ref, diff=d8)
    for o in out:
        o["pass"] = o.pop("pass_")
    return {"cases": out, "pass": all(o["pass"] for o in out)}


# ------------------------------------------------------------------ 输出
def rnd(x):
    if isinstance(x, dict):
        return {str(k): rnd(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [rnd(v) for v in x]
    if isinstance(x, (bool, np.bool_)) or x is None or isinstance(x, str):
        return bool(x) if isinstance(x, np.bool_) else x
    if isinstance(x, (int, np.integer)):
        return int(x)
    return float(f"{float(x):.6g}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("params")
    ap.add_argument("--root", default=HERE_REPO)
    ap.add_argument("--override", action="append", default=[], help="k=v，只在内存中改标量参数")
    ap.add_argument("--selftest", action="store_true", help="只跑自检")
    ap.add_argument("--no-selftest", action="store_true", help="正式运行前不跑自检")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    E = Engine(a.root)
    ov = {}
    for s in a.override:
        k, v = s.split("=", 1); ov[k] = float(v)
    head = {"tool": "tools/bandwidth_tilt.py", "spec": "specs/g003-e02.md", "engine_root_git": E.commit(),
            "params_file": os.path.basename(a.params),
            "params_sha256": hashlib.sha256(open(a.params, "rb").read()).hexdigest(),
            "overrides": ov, "kl_run_args": E.argnames}
    st = None
    if a.selftest or not a.no_selftest:
        st = selftest(E, a.params)
    if a.selftest:
        doc = dict(head, selftest=st)
    else:
        if st is not None and not st["pass"]:
            print(json.dumps(rnd(dict(head, selftest=st)), ensure_ascii=False, indent=1, sort_keys=True))
            return 1
        doc = dict(head, selftest_pass=None if st is None else st["pass"], result=analyze(E, load(E, a.params, ov)))
    s = json.dumps(rnd(doc), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if a.out:
        open(a.out, "w", encoding="utf-8").write(s)
    else:
        sys.stdout.write(s)
    return 0 if (st is None or st["pass"]) else 1


if __name__ == "__main__":
    sys.exit(main())
