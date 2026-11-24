"""LF 声门气流导数模型（Fant, Liljencrants & Lin 1985），用 Rd 参数化（Fant 1995）。

每个周期 T0：
  开相   0 ≤ t ≤ te:  E(t) = E0 · e^{αt} · sin(ωg t),  ωg = π / tp
  回复相 te < t ≤ tc:  E(t) = −(Ee / (ε ta)) · (e^{−ε(t−te)} − e^{−ε(tc−te)})
  tc = T0；ε 由 ε·ta = 1 − e^{−ε(tc−te)} 解出；α 由一周期内净气流为零解出；
  E0 由 E(te) = −Ee 的连续性定出。
Rd → (Ra, Rk, Rg)：Ra = (−1 + 4.8 Rd)/100，Rk = (22.4 + 11.8 Rd)/100，
  Rg = Rk / (4 (0.11 Rd / (0.5 + 1.2 Rk) − Ra))；ta = Ra T0，tp = T0/(2 Rg)，te = tp (1 + Rk)。
返回的是气流导数；synth 积分为体积速度后注入声道。
"""
import numpy as np


def rd_to_timing(rd):
    ra = (-1.0 + 4.8 * rd) / 100.0
    rk = (22.4 + 11.8 * rd) / 100.0
    denom = 0.11 * rd / (0.5 + 1.2 * rk) - ra
    rg = rk / (4.0 * max(denom, 1e-4))
    tp = 1.0 / (2.0 * rg)
    te = tp * (1.0 + rk)
    ta = max(ra, 1e-4)
    # 保证时间次序 0 < tp < te < 1，且 ta 小于回复相
    te = min(te, 0.98)
    tp = min(tp, te * 0.95)
    ta = min(ta, (1.0 - te) * 0.95)
    return tp, te, ta


def _eps(ta, tr):
    """解 ε·ta = 1 − exp(−ε·tr)（tr = tc − te），牛顿法。"""
    e = 1.0 / ta
    for _ in range(50):
        g = e * ta - 1.0 + np.exp(-e * tr)
        dg = ta - tr * np.exp(-e * tr)
        if dg == 0:
            break
        de = g / dg
        e -= de
        if e <= 0:
            e = 1e-3 / ta
        if abs(de) < 1e-10 * e:
            break
    return e


def _net_flow(alpha, wg, te, ta, eps, tc):
    """Ee = 1 时一周期的净气流（开相积分 + 回复相积分）。"""
    s = np.sin(wg * te)
    if abs(s) < 1e-9:
        s = 1e-9
    e0 = -1.0 / (np.exp(alpha * te) * s)
    a2w2 = alpha * alpha + wg * wg
    i_open = e0 * (np.exp(alpha * te) * (alpha * np.sin(wg * te) - wg * np.cos(wg * te)) + wg) / a2w2
    tr = tc - te
    i_ret = -(1.0 / (eps * ta)) * ((1.0 - np.exp(-eps * tr)) / eps - tr * np.exp(-eps * tr))
    return i_open + i_ret, e0


def lf_shape(rd):
    """归一化周期（T0 = 1, Ee = 1）的 (tp, te, ta, α, ε, E0)。"""
    tp, te, ta = rd_to_timing(rd)
    wg = np.pi / tp
    eps = _eps(ta, 1.0 - te)
    lo, hi = -50.0, 200.0
    flo, _ = _net_flow(lo, wg, te, ta, eps, 1.0)
    fhi, _ = _net_flow(hi, wg, te, ta, eps, 1.0)
    alpha = 0.0
    if flo * fhi > 0:
        alpha = lo if abs(flo) < abs(fhi) else hi
    else:
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            fm, _ = _net_flow(mid, wg, te, ta, eps, 1.0)
            if fm * flo > 0:
                lo, flo = mid, fm
            else:
                hi = mid
        alpha = 0.5 * (lo + hi)
    _, e0 = _net_flow(alpha, wg, te, ta, eps, 1.0)
    return tp, te, ta, alpha, eps, e0


def lf_period(n, rd):
    """长度 n 采样的一个周期的气流导数（Ee = 1）。"""
    tp, te, ta, alpha, eps, e0 = lf_shape(rd)
    t = np.arange(n) / n
    wg = np.pi / tp
    out = np.empty(n)
    op = t <= te
    out[op] = e0 * np.exp(alpha * t[op]) * np.sin(wg * t[op])
    rt = ~op
    out[rt] = -(1.0 / (eps * ta)) * (np.exp(-eps * (t[rt] - te)) - np.exp(-eps * (1.0 - te)))
    return out, te


def glottal_source(f0, rd, amp, fs, rng, jitter=0.0, shimmer=0.0, asp_gain=0.0):
    """按逐采样 F0 (Hz)、Rd、幅度生成气流导数与送气噪声。
    f0 ≤ 0 处不发声（输出 0）。返回 (dU/dt, 送气噪声[已按开相调制])。"""
    n = len(f0)
    du = np.zeros(n)
    asp = np.zeros(n)
    t = 0
    while t < n:
        if f0[t] <= 0 or amp[t] <= 0:
            t += 1
            continue
        T = fs / f0[t]
        if jitter > 0:
            T *= 1.0 + jitter * rng.standard_normal()
        L = max(8, int(round(T)))
        L = min(L, n - t) if n - t >= 8 else n - t
        if L <= 0:
            break
        a = amp[t] * (1.0 + shimmer * rng.standard_normal() if shimmer > 0 else 1.0)
        p, te = lf_period(L, float(np.clip(rd[t], 0.3, 2.7)))
        # 声门开相内送气噪声
        if asp_gain > 0:
            w = np.zeros(L)
            ne = int(te * L)
            w[:ne] = np.sin(np.pi * np.arange(ne) / max(ne, 1)) ** 2
            asp[t:t + L] = asp_gain * a * w * rng.standard_normal(L)
        du[t:t + L] = a * p
        t += L
    return du, asp
