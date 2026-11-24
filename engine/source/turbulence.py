"""以气流为依据的湍流噪声源（specs/g001-e07.md）。

1. 准静态气动（每个控制帧）：声门 A_g 与最窄口腔收紧 A_c 两个孔口串联（伯努利）
     U_DC = √(2 P_sub / ρ) / √(1/A_g² + 1/A_c²)
   A_c 取口腔最小面积减去闭塞残余面积（防闭塞漏流嘶声，规格 3.1），软腭开时并上 A_vp。
   A_g = 0（静音段）→ U_DC = 0。
2. 源强度（Stevens 律 + 雷诺数门限，规格 2.2）：
     p_s = G · ρ · v³ · √A / c · g_Re,   v = U / A,   Re = 2U / (ν √(π A)),
     g_Re = max(0, 1 − (Re_c / Re)²)
   以 s = p_s / (ρc) 注入 KL 网格（kl.py 的行波量已除以 ρc，规格 2.5）。
3. 两个源：
   - 口腔收紧源：在控制给出的 nidx 处，A = nidx 附近（±3 段）的最小面积，U = U_DC。
   - 声门源：声门下游约 1.5 cm，A = A_g，U = U_DC + U_AC（LF 交流气流，经 500 Hz 低通，规格 3.3）。
   G 由控制给出（按部位 / 方式，见 gestures.py）；单位方差白噪声来自种子 rng。
   本版不做源谱着色（规格 2.4 的 f_c 低通留待后续），只改电平。
CGS 单位：cm、g、s；压力 dyn/cm²（1 Pa = 10 dyn/cm²）。
"""
import numpy as np
from scipy.signal import lfilter

RHO = 1.14e-3      # g/cm³，37 °C 空气（规格第 1 节，S6）
NU = 0.167         # cm²/s，运动黏度（规格第 1 节，S6）
C_CGS = 35000.0    # cm/s，与 kl.C_SOUND 一致
GLOTTAL_SRC_CM = 1.5   # 声门源位于声门出口下游 1.5 cm（规格 2.3，S1）
LOCAL_HALF = 3         # 口腔收紧源取 nidx ± 3 段内最小面积
V_LP_HZ = 500.0        # 质点速度低通截止（S1）


def dc_flow(A, Avp, ag, p_sub_pa, closure_area):
    """每帧的准静态直流流量 U_DC（cm³/s）与口腔最窄有效面积。A[nf, N] cm²。"""
    ac = np.maximum(A.min(axis=1) - closure_area, 0.0) + np.maximum(Avp, 0.0)
    ag = np.maximum(ag, 0.0)
    p = p_sub_pa * 10.0
    u = np.zeros(len(ac))
    ok = (ac > 0) & (ag > 0)
    u[ok] = np.sqrt(2.0 * p / RHO) / np.sqrt(1.0 / ag[ok] ** 2 + 1.0 / ac[ok] ** 2)
    return u, ac


def stevens_amp(u, a, re_crit, p_sub_pa):
    """源压力 / (ρc)：G = 1 时的幅度（单位同 KL 行波量，cm/s）。u、a 同形数组。
    质点速度不超过伯努利上限 √(2 P_sub / ρ)：流量超过 a·v_max 时（发声开相、过渡段
    面积插值与 LF 流量不同步），取有效面积 u / v_max。"""
    out = np.zeros(np.shape(u))
    ok = (a > 0) & (u > 0)
    vmax = np.sqrt(2.0 * p_sub_pa * 10.0 / RHO)
    uu = u[ok]
    aa = np.maximum(a[ok], uu / vmax)
    v = uu / aa
    re = 2.0 * uu / (NU * np.sqrt(np.pi * aa))
    g = np.maximum(0.0, 1.0 - (re_crit / re) ** 2)
    ps = RHO * v ** 3 * np.sqrt(aa) / C_CGS * g
    out[ok] = ps / (RHO * C_CGS)
    return out


def constriction_amp(A, closure_area, nidx, u_dc, re_crit, p_sub_pa):
    """口腔收紧源每帧幅度（G = 1）。"""
    nf, N = A.shape
    a = np.zeros(nf)
    for i in range(nf):
        k = nidx[i]
        if k < 0:
            continue
        lo, hi = max(0, k - LOCAL_HALF), min(N, k + LOCAL_HALF + 2)
        a[i] = max(A[i, lo:hi].min() - closure_area, 0.0)
    return stevens_amp(u_dc, a, re_crit, p_sub_pa)


def lowpass_flow(u, fs):
    """质点速度只取低频部分：流量经一阶 500 Hz 低通（S1）。"""
    al = np.exp(-2.0 * np.pi * V_LP_HZ / fs)
    return lfilter([1.0 - al], [1.0, -al], u)
