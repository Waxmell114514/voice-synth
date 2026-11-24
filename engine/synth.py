"""引擎入口。见 MISSION.md 与 eval/ENGINE_API.md。

python -m engine.synth --text "你好" --seed 0 --params params/x.json --out a.wav
python -m engine.synth --pinyin "ni3 hao3" --seed 0 --params params/x.json --out a.wav
"""
import argparse, sys, wave
import numpy as np
from scipy.signal import resample_poly

from .params_io import load_params
from .control.gestures import plan
from .source.lf import glottal_source
from .tract.kl import kl_run, sim_rate

FS_OUT = 22050
N_SECT = 44


def nasal_areas(P, n_sections_len):
    a = np.asarray(P["nasal_area"], float)
    return np.interp(np.linspace(0, 1, n_sections_len), np.linspace(0, 1, len(a)), a)


def render(tokens, P, seed):
    rng = np.random.default_rng(seed)
    L = P["tract_length_cm"]
    fs_sim, up, down = sim_rate(L, N_SECT, FS_OUT)
    dx_cm = L / N_SECT
    block = max(1, int(round(fs_sim * 1e-3)))
    frame_s = block / fs_sim
    tl, total = plan(tokens, P, frame_s)
    A, Avp, nidx, ngain, voice, asp, f0f = tl.render(total)
    nb = A.shape[0]
    n = nb * block
    # 逐采样源控制
    tt = (np.arange(n) + 0.5) / block - 0.5
    fi = np.clip(tt, 0, nb - 1)
    f0 = np.interp(fi, np.arange(nb), f0f)
    vamp = np.interp(fi, np.arange(nb), voice)
    rd = np.full(n, P["rd_modal"])
    du, aspn = glottal_source(f0 * (vamp > 0.05), rd, vamp, fs_sim, rng,
                              jitter=P["jitter"], shimmer=P["shimmer"], asp_gain=P["breath_noise_gain"])
    ug = np.cumsum(du) / fs_sim * P["f0_base_hz"]          # 体积速度（相对单位）
    asp_s = np.interp(fi, np.arange(nb), asp)
    ug = ug + aspn * 0.01 + asp_s * 0.01 * rng.standard_normal(n)
    noise = rng.standard_normal(n)
    Nn = max(4, int(round(P["nasal_length_cm"] / dx_cm)))
    An = nasal_areas(P, Nn)
    kv = int(np.clip(round(P["velum_pos_frac"] * (N_SECT - 1)), 1, N_SECT - 3))
    f = np.zeros(N_SECT); b = np.zeros(N_SECT); fn = np.zeros(Nn); bn = np.zeros(Nn)
    ul, un, _ = kl_run(n, block, np.ascontiguousarray(A), An, np.ascontiguousarray(Avp), kv, ug,
                       noise, np.ascontiguousarray(nidx), np.ascontiguousarray(ngain) * 0.01,
                       P["r_glottis"], P["r_lip"], P["r_nose"], P["wall_loss"], f, b, fn, bn, False)
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
