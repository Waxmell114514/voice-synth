"""引擎入口。见 MISSION.md 与 eval/ENGINE_API.md。

python -m engine.synth --text "你好" --seed 0 --params params/x.json --out a.wav
python -m engine.synth --pinyin "ni3 hao3" --seed 0 --params params/x.json --out a.wav
"""
import argparse, sys, wave
import numpy as np
from scipy.signal import resample_poly

from .params_io import load_params
from .control.gestures import plan
from .source.lf import glottal_source, lf_period
from .source import turbulence as TB
from .tract.kl import kl_core, sim_rate

FS_OUT = 22050
N_SECT = 44


def nasal_areas(P, n_sections_len):
    a = np.asarray(P["nasal_area"], float)
    return np.interp(np.linspace(0, 1, n_sections_len), np.linspace(0, 1, len(a)), a)


def lf_peak_flow(rd, n=2000):
    """归一化周期（T0 = 1, Ee = 1）LF 气流的峰值。"""
    p, _ = lf_period(n, float(np.clip(rd, 0.3, 2.7)))
    return float(np.max(np.cumsum(p) / n))


def render(tokens, P, seed):
    rng = np.random.default_rng(seed)
    L = P["tract_length_cm"]
    fs_sim, up, down = sim_rate(L, N_SECT, FS_OUT)
    dx_cm = L / N_SECT
    block = max(1, int(round(fs_sim * 1e-3)))
    frame_s = block / fs_sim
    tl, total = plan(tokens, P, frame_s)
    A, Avp, nidx, ngain, voice, ag, f0f = tl.render(total)
    nb = A.shape[0]
    n = nb * block
    # 逐采样源控制
    tt = (np.arange(n) + 0.5) / block - 0.5
    fi = np.clip(tt, 0, nb - 1)
    f0 = np.interp(fi, np.arange(nb), f0f)
    vamp = np.interp(fi, np.arange(nb), voice)
    rd = np.full(n, P["rd_modal"])
    du, _ = glottal_source(f0 * (vamp > 0.05), rd, vamp, fs_sim, rng,
                           jitter=P["jitter"], shimmer=P["shimmer"], asp_gain=0.0)
    # LF 交流气流定标到 cm³/s：每周期积分得归一化流量，峰值按 Rd 的归一化峰值换成 ug_ac_peak_cm3s
    ug = np.cumsum(du * f0) / fs_sim * (P["ug_ac_peak_cm3s"] / lf_peak_flow(P["rd_modal"]))
    # 湍流噪声源（specs/g001-e07.md）：准静态气流 → Stevens 律幅度 × 系数 G × 种子白噪声
    clo = max(P["closure_area"], P["min_area"])
    udc, frac_oral = TB.dc_flow(A, Avp, ag, P["p_sub_pa"], clo)
    # 口腔收紧源只用经口腔的那一路气流（软腭开时鼻腔分流，g001-e07c）
    amp_c = TB.constriction_amp(A, clo, nidx, udc * frac_oral, P["re_crit"], P["p_sub_pa"]) * ngain     # 每控制帧
    ugl = TB.lowpass_flow(np.interp(fi, np.arange(nb), udc) + np.maximum(ug, 0.0), fs_sim)
    ag_s = np.interp(fi, np.arange(nb), ag)
    # 声门源系数随声门外展程度在 log 域插值（Birkholz 2014：声门源增益随声门状态可变）：
    # A_g ≤ ag_voiced → G_asp·10^breath_rel；A_g ≥ ag_abduct → G_asp
    ab = np.clip((ag_s - P["ag_voiced_cm2"]) / max(P["ag_abduct_cm2"] - P["ag_voiced_cm2"], 1e-3), 0.0, 1.0)
    g_g = 10.0 ** (P["noise_g_asp_log10"] + P["noise_g_breath_rel_log10"] * (1.0 - ab))
    gsrc = TB.stevens_amp(ugl, ag_s, P["re_crit"], P["p_sub_pa"]) * g_g * rng.standard_normal(n)
    noise = np.interp(fi, np.arange(nb), amp_c) * rng.standard_normal(n)
    gidx = int(np.clip(round(TB.GLOTTAL_SRC_CM / dx_cm), 0, N_SECT - 2))
    Nn = max(4, int(round(P["nasal_length_cm"] / dx_cm)))
    An = nasal_areas(P, Nn)
    kv = int(np.clip(round(P["velum_pos_frac"] * (N_SECT - 1)), 1, N_SECT - 3))
    f = np.zeros(N_SECT); b = np.zeros(N_SECT); fn = np.zeros(Nn); bn = np.zeros(Nn)
    ul, un, _ = kl_core(n, block, np.ascontiguousarray(A), An, np.ascontiguousarray(Avp), kv, ug,
                        noise, np.ascontiguousarray(nidx), np.ones(nb),
                        P["r_glottis"], P["r_lip"], P["r_nose"], P["wall_loss"], f, b, fn, bn, False,
                        gsrc, gidx)
    u = ul + un
    y = np.diff(u, prepend=0.0)                              # 辐射：一阶差分
    y = resample_poly(y, up, down)
    return finalize(y)


def finalize(y):
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    a = np.abs(y)
    if a.max() > 0:
        act = y[a > 0.02 * a.max()]
        r = np.sqrt(np.mean(act ** 2)) if len(act) else a.max()
        y = y * (10 ** (-20 / 20) / r)
        pk = np.abs(y).max()
        if pk > 0.95:
            y = y * 0.95 / pk
    return y


def write_wav(path, y, fs):
    pcm = np.clip(np.round(y * 32767), -32767, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs); w.writeframes(pcm.tobytes())


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text"); g.add_argument("--pinyin")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--params", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    P = load_params(a.params)
    if a.text is not None:
        from .frontend.text2pinyin import text_to_tokens
        tokens = text_to_tokens(a.text)
    else:
        tokens = a.pinyin.split()
    y = render(tokens, P, a.seed)
    write_wav(a.out, y, FS_OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
