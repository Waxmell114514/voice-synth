"""Kelly-Lochbaum 声道（压力行波），带鼻腔旁支。

几何：口腔 N 段等长（声门→唇），段长 Δ = L/N；仿真采样率 fs_sim = N·c/L，
即每段每方向一个采样延迟。鼻腔 Nn 段，段长同为 Δ，在口腔第 kv 段与第 kv+1 段之间
经软腭口（面积 A_vp）以三端口并联结点耦合；A_vp = 0 时退化为普通两端口结点。

鼻腔第 0 段即腭咽口管段，其面积取 A_vp(t)（An[0] 不用）：口腔三端口结点、鼻腔 k=0 结点
（A_vp ↔ An[1]）与能量和都用同一个 A_vp，功率守恒一致。A_vp → 0 时鼻腔 k=0 结点对鼻腔侧
刚性反射，鼻孔输出连续地趋于 0，口腔结点连续地退化为两端口（g001-e06，specs/g001-e06.md §3）。

结点（并联，功率守恒）：pJ = 2 Σ A_i p_i^in / Σ A_i，p_i^out = pJ − p_i^in。
声门端：f0_new = r_g·b0 + 激励；唇端：b_{N-1,new} = −r_lip·f_{N-1}；鼻孔端同理（−r_nose）。
壁面损耗：每个采样所有行波乘 (1−μ)。
存储能量 E = Σ A_k (f_k² + b_k²)（含鼻腔）。r_g ≤ 1、r_lip ≤ 1、μ ≥ 0 且面积不变时
E 逐采样单调不增。
输出：唇和鼻孔的体积速度 u = A(1+r)f，再一阶差分近似辐射（在 synth 中做）。
"""
import numpy as np
from numba import njit

C_SOUND = 350.0  # m/s，见 specs/g0-seed.md


@njit(cache=True, fastmath=False)
def kl_run(n, block, A, An, Avp, kv, ug, noise, nidx, ngain,
           r_g, r_lip, r_nose, mu, f, b, fn, bn, want_energy):
    """原签名（T0 钩子使用）：无声门湍流源，等价于 kl_core(..., gsrc=[0], gidx=-1)。"""
    return kl_core(n, block, A, An, Avp, kv, ug, noise, nidx, ngain,
                   r_g, r_lip, r_nose, mu, f, b, fn, bn, want_energy, np.zeros(1), -1)


@njit(cache=True, fastmath=False)
def kl_core(n, block, A, An, Avp, kv, ug, noise, nidx, ngain,
            r_g, r_lip, r_nose, mu, f, b, fn, bn, want_energy, gsrc, gidx):
    """
    n        仿真采样数
    block    控制块长度（采样）；A[nb, N]、Avp[nb]、nidx[nb]、ngain[nb] 每块一组
    An[Nn]   鼻腔面积（固定；An[0] 不用，第 0 段面积 = Avp）
    ug[n]    声门处注入（体积速度，已含送气噪声）
    noise[n] 湍流噪声源（单位方差），在 nidx 段下游注入，增益 ngain
    f,b,fn,bn  初始状态（就地更新）
    gsrc[n]  声门湍流源（已含幅度，单位同行波量），在 gidx 与 gidx+1 段之间注入；gidx < 0 表示无
    返回 (u_lip[n], u_nose[n], energy[n])
    """
    N = f.shape[0]
    Nn = fn.shape[0]
    ul = np.zeros(n)
    un = np.zeros(n)
    en = np.zeros(n if want_energy else 1)
    nf = np.zeros(N)
    nb_ = np.zeros(N)
    nfn = np.zeros(Nn)
    nbn = np.zeros(Nn)
    g = 1.0 - mu
    for t in range(n):
        blk = t // block
        if blk >= A.shape[0]:
            blk = A.shape[0] - 1
        # 声门端
        nf[0] = r_g * b[0] + ug[t] / A[blk, 0]
        avp = Avp[blk] if Avp[blk] > 0.0 else 0.0
        # 口腔结点
        for k in range(N - 1):
            a1 = A[blk, k]
            a2 = A[blk, k + 1]
            if k == kv:
                a3 = avp  # 腭咽口（鼻腔第 0 段）面积；a3 = 0 时精确退化为两端口
                pj = 2.0 * (a1 * f[k] + a2 * b[k + 1] + a3 * bn[0]) / (a1 + a2 + a3)
                nf[k + 1] = pj - b[k + 1]
                nb_[k] = pj - f[k]
                nfn[0] = pj - bn[0]
            else:
                pj = 2.0 * (a1 * f[k] + a2 * b[k + 1]) / (a1 + a2)
                nf[k + 1] = pj - b[k + 1]
                nb_[k] = pj - f[k]
        # 鼻腔结点（第 0 段面积 = 腭咽口 Avp；a2 = An[1] > 0，分母恒正）
        for k in range(Nn - 1):
            a1 = avp if k == 0 else An[k]
            a2 = An[k + 1]
            pj = 2.0 * (a1 * fn[k] + a2 * bn[k + 1]) / (a1 + a2)
            nfn[k + 1] = pj - bn[k + 1]
            nbn[k] = pj - fn[k]
        # 唇端、鼻孔端
        nb_[N - 1] = -r_lip * f[N - 1]
        ul[t] = A[blk, N - 1] * (1.0 + r_lip) * f[N - 1]
        nbn[Nn - 1] = -r_nose * fn[Nn - 1]
        un[t] = An[Nn - 1] * (1.0 + r_nose) * fn[Nn - 1]
        # 湍流噪声：串联压力源，在 nidx 与 nidx+1 段之间（向下游 +½，上游 −½）
        ki = nidx[blk]
        if ki >= 0 and ki < N - 1 and ngain[blk] != 0.0:
            s = 0.5 * ngain[blk] * noise[t]
            nf[ki + 1] += s
            nb_[ki] -= s
        if gidx >= 0 and gidx < N - 1:
            s = 0.5 * gsrc[t]
            nf[gidx + 1] += s
            nb_[gidx] -= s
        # 损耗并推进一个采样
        e = 0.0
        for k in range(N):
            f[k] = g * nf[k]
            b[k] = g * nb_[k]
            if want_energy:
                e += A[blk, k] * (f[k] * f[k] + b[k] * b[k])
        if avp <= 0.0:
            # 软腭关闭：腭咽口段面积为 0，不进能量和；必须清零，否则它会积累口腔压力，
            # 开启瞬间释放成爆音（Critic 对 g001-fix01 的审查）
            nfn[0] = 0.0
            nbn[0] = 0.0
        for k in range(Nn):
            fn[k] = g * nfn[k]
            bn[k] = g * nbn[k]
            if want_energy:
                e += (avp if k == 0 else An[k]) * (fn[k] * fn[k] + bn[k] * bn[k])
        if want_energy:
            en[t] = e
    return ul, un, en


def sim_rate(length_cm, n_sections, fs_out):
    """理想仿真采样率 N·c/L，取与输出采样率成有理比（分母 ≤ 256）的近值，返回 (fs_sim, up, down)。"""
    from fractions import Fraction
    ideal = n_sections * C_SOUND / (length_cm / 100.0)
    fr = Fraction(ideal / fs_out).limit_denominator(256)
    return fs_out * fr.numerator / fr.denominator, fr.denominator, fr.numerator
