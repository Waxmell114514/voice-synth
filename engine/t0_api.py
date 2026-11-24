"""T0 钩子（eval/ENGINE_API.md）。与 synth 走同一个 kl_run 内核。"""
import numpy as np
from scipy.signal import resample_poly
from .tract.kl import kl_run, sim_rate
from .synth import FS_OUT, N_SECT, nasal_areas
from .params_io import load_params, load_schema

FS = FS_OUT


def _default(name):
    for p in load_schema()["params"]:
        if p["name"] == name:
            return p["default"]
    raise KeyError(name)


def tube_impulse_response(area_cm2, length_cm, n_samples):
    a = np.asarray(area_cm2, float)
    A = np.interp(np.linspace(0, 1, N_SECT), np.linspace(0, 1, len(a)), a)[None, :]
    fs_sim, up, down = sim_rate(length_cm, N_SECT, FS)
    n = int(np.ceil(n_samples * up / down)) + 64
    ug = np.zeros(n); ug[0] = 1.0
    z = np.zeros(1)
    ul, un, _ = kl_run(n, n, A, np.full(8, 1.0), np.zeros(1), 1, ug, np.zeros(n),
                       np.full(1, -1, dtype=np.int64), z, 1.0, float(_default("r_lip")), 0.9,
                       float(_default("wall_loss")), np.zeros(N_SECT), np.zeros(N_SECT), np.zeros(8), np.zeros(8), False)
    y = np.diff(ul, prepend=0.0)
    return resample_poly(y, up, down)[:n_samples]


def zero_input_energy(params_path, n_samples, seed):
    P = load_params(params_path)
    rng = np.random.default_rng(seed)
    L = P["tract_length_cm"]
    fs_sim, up, down = sim_rate(L, N_SECT, FS)
    Nn = max(4, int(round(P["nasal_length_cm"] / (L / N_SECT))))
    An = nasal_areas(P, Nn)
    A = np.maximum(np.asarray(P["area_a"], float), P["min_area"])[None, :]
    Avp = np.array([P["velum_open_area"]])
    kv = int(np.clip(round(P["velum_pos_frac"] * (N_SECT - 1)), 1, N_SECT - 3))
    f, b = rng.standard_normal(N_SECT), rng.standard_normal(N_SECT)
    fn, bn = rng.standard_normal(Nn), rng.standard_normal(Nn)
    n = n_samples
    _, _, e = kl_run(n, n, A, An, Avp, kv, np.zeros(n), np.zeros(n), np.full(1, -1, dtype=np.int64),
                     np.zeros(1), P["r_glottis"], P["r_lip"], P["r_nose"], P["wall_loss"], f, b, fn, bn, True)
    return e
