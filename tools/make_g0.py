"""生成 params/schema.json 与 params/g0.json（阶段 0.5 种子）。

数值出处见 specs/g0-seed.md。元音面积函数读 specs/g0_area_functions.json（Researcher 提供，
44 段，声门→唇，cm²）；缺失时退回下面的粗略三区模型（标注为占位）。
"""
import os, json
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = 44
S = []


def P(name, meaning, unit, lo, hi, default, shape=None):
    d = {"name": name, "meaning": meaning, "unit": unit, "min": lo, "max": hi,
         "default": (np.asarray(default, float).round(4).tolist() if shape else float(default))}
    d["shape"] = list(shape) if shape else []
    S.append(d)


def three_zone(ph, mid, front, lip, c_pos=None, c_area=None):
    """占位：咽腔/中段/前腔/唇 四档面积，可选一个高斯收紧。"""
    x = np.linspace(0, 1, N)
    a = np.interp(x, [0, 0.12, 0.35, 0.6, 0.85, 0.93, 1.0], [1.5, ph, ph, mid, front, front, lip])
    if c_pos is not None:
        m = np.exp(-0.5 * ((x - c_pos) / 0.06) ** 2)
        a = a * (1 - m) + c_area * m
    return a


def area_targets():
    p = os.path.join(REPO, "specs", "g0_area_functions.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        return {k: np.interp(np.linspace(0, 1, N), np.linspace(0, 1, len(v)), v) for k, v in d["areas"].items()}, d.get("source", "")
    placeholder = {
        "a": three_zone(0.8, 2.5, 5.0, 4.0, 0.3, 0.6), "o": three_zone(2.0, 2.0, 3.0, 0.8, 0.55, 0.9),
        "e": three_zone(2.5, 2.5, 2.5, 2.0, 0.6, 1.0), "i": three_zone(6.0, 4.0, 0.4, 2.0, 0.78, 0.3),
        "u": three_zone(5.0, 0.6, 3.0, 0.3, 0.62, 0.4), "v": three_zone(6.0, 4.0, 0.5, 0.5, 0.78, 0.35),
        "E": three_zone(4.0, 3.0, 1.2, 2.5), "schwa": np.full(N, 2.5), "ii": three_zone(3.0, 3.0, 1.5, 2.0, 0.9, 0.5),
        "iii": three_zone(3.0, 2.5, 1.0, 2.0, 0.85, 0.6), "er": three_zone(2.5, 2.0, 1.0, 2.0, 0.82, 0.5)}
    return placeholder, "PLACEHOLDER three-zone model (未核实)"


def main():
    areas, src = area_targets()
    # ---- 说话人 / 声道
    P("tract_length_cm", "声道长度（声门到唇）", "cm", 12.0, 19.0, 14.8)
    P("min_area", "面积函数下限（避免除零，闭塞仍保留极小面积）", "cm^2", 0.001, 0.05, 0.005)
    P("r_glottis", "声门端压力波反射系数", "1", 0.5, 1.0, 0.85)
    P("r_lip", "唇端压力波反射系数的模（开端反射为 -r_lip）", "1", 0.5, 0.995, 0.92)
    P("r_nose", "鼻孔端压力波反射系数的模", "1", 0.5, 0.995, 0.9)
    P("wall_loss", "每段每采样的行波衰减（壁面与黏滞损耗的集总近似）", "1", 0.0, 0.01, 0.0015)
    P("velum_pos_frac", "鼻腔分支位置（距声门占声道长度比例）", "1", 0.35, 0.65, 0.5)
    P("nasal_length_cm", "鼻腔长度", "cm", 8.0, 13.0, 10.5)
    P("nasal_area", "鼻腔面积函数（软腭口→鼻孔，均匀重采样到实际段数）", "cm^2", 0.1, 5.0,
      np.interp(np.linspace(0, 1, 12), [0, 0.2, 0.5, 0.8, 1.0], [1.2, 2.5, 3.0, 2.0, 1.0]), (12,))
    P("velum_open_area", "鼻音时软腭口面积", "cm^2", 0.0, 2.0, 0.6)
    # ---- 声源
    P("f0_base_hz", "Chao 调值 3 对应的基频", "Hz", 140.0, 320.0, 215.0)
    P("f0_range_st", "Chao 调值 1 到 5 的音高跨度", "semitone", 3.0, 18.0, 10.0)
    P("declination_st_per_s", "句内基频下倾斜率", "semitone/s", -3.0, 0.0, -0.8)
    P("rd_modal", "LF 模型 Rd（常态发声）", "1", 0.3, 2.7, 1.1)
    P("jitter", "周期长度随机扰动的标准差（相对）", "1", 0.0, 0.03, 0.005)
    P("shimmer", "周期幅度随机扰动的标准差（相对）", "1", 0.0, 0.15, 0.03)
    P("breath_noise_gain", "声门开相送气噪声相对幅度", "1", 0.0, 0.5, 0.05)
    P("asp_noise_gain", "送气音与 h 的声门湍流噪声幅度", "relative", 0.0, 5.0, 1.0)
    # ---- 元音面积函数
    names = {"a": "/a/", "o": "/o/", "e": "/ɤ/", "i": "/i/", "u": "/u/", "v": "/y/ (ü)", "E": "/ɛ/ (ie、üe、ei 中的 ê)",
             "schwa": "/ə/ (en、eng 中的央元音)", "ii": "舌尖前元音 /ɿ/ (zi ci si)", "iii": "舌尖后元音 /ʅ/ (zhi chi shi ri)",
             "er": "卷舌元音 /ɚ/"}
    for k, nm in names.items():
        P(f"area_{k}", f"元音 {nm} 面积函数（声门→唇，{N} 段）", "cm^2", 0.05, 12.0, areas[k], (N,))
    # ---- 辅音部位：距唇的比例与收紧宽度
    place = {"lab": (0.0, "双唇"), "labdent": (0.0, "唇齿"), "dent": (0.1, "舌尖前（齿龈前）"), "alv": (0.13, "舌尖中（齿龈）"),
             "ret": (0.2, "舌尖后（龈后）"), "pal": (0.27, "舌面（龈腭）"), "vel": (0.42, "舌根（软腭）")}
    for k, (frac, nm) in place.items():
        P(f"place_{k}", f"{nm}收紧中心距唇的位置（占声道长度比例）", "1", 0.0, 0.6, frac)
        P(f"cwidth_{k}", f"{nm}收紧宽度（高斯标准差）", "sections", 0.5, 6.0, 1.5)
    for k in ["labdent", "dent", "ret", "pal", "vel"]:
        P(f"fric_gain_{k}", f"{place[k][1]}擦音 / 塞擦音湍流噪声增益", "relative", 0.0, 50.0, 10.0)
    P("closure_area", "塞音和鼻音闭塞面积", "cm^2", 0.001, 0.05, 0.005)
    P("release_area", "塞音除阻瞬间的收紧面积", "cm^2", 0.02, 0.5, 0.1)
    P("fric_area", "擦音收紧面积", "cm^2", 0.02, 0.6, 0.12)
    P("fric_area_h", "h 的舌根收紧面积", "cm^2", 0.1, 2.0, 0.5)
    P("approx_area_l", "l 的舌尖收紧面积（侧音的一维近似）", "cm^2", 0.1, 2.0, 0.4)
    P("approx_area_r", "r 的卷舌收紧面积", "cm^2", 0.1, 2.0, 0.35)
    P("burst_gain", "塞音除阻爆破噪声增益", "relative", 0.0, 50.0, 15.0)
    # ---- 时长
    P("lead_sil_ms", "句首静音", "ms", 50.0, 300.0, 120.0)
    P("tail_sil_ms", "句尾静音", "ms", 50.0, 300.0, 150.0)
    P("syl_dur_ms", "非末音节的基本时长", "ms", 120.0, 400.0, 230.0)
    P("final_lengthening", "停顿前音节的时长倍数", "1", 1.0, 2.0, 1.35)
    P("neutral_dur_ratio", "轻声音节时长倍数", "1", 0.4, 1.0, 0.65)
    P("pause_short_ms", "逗号类停顿", "ms", 50.0, 600.0, 200.0)
    P("pause_long_ms", "句末类停顿", "ms", 100.0, 900.0, 400.0)
    P("dur_closure_unasp_ms", "不送气塞音 / 塞擦音闭塞时长", "ms", 20.0, 150.0, 60.0)
    P("dur_closure_asp_ms", "送气塞音 / 塞擦音闭塞时长", "ms", 20.0, 150.0, 55.0)
    P("vot_unasp_ms", "不送气塞音 VOT", "ms", 3.0, 40.0, 12.0)
    P("vot_asp_ms", "送气塞音 VOT", "ms", 30.0, 150.0, 80.0)
    P("dur_affr_fric_unasp_ms", "不送气塞擦音擦音段时长", "ms", 10.0, 150.0, 40.0)
    P("dur_affr_fric_asp_ms", "送气塞擦音擦音段时长", "ms", 30.0, 200.0, 90.0)
    P("dur_fric_ms", "擦音时长", "ms", 40.0, 250.0, 120.0)
    P("dur_nasal_init_ms", "鼻音声母闭塞时长", "ms", 20.0, 150.0, 60.0)
    P("dur_approx_ms", "l、r 收紧段时长", "ms", 20.0, 150.0, 50.0)
    P("coda_frac", "鼻韵尾占韵母时长比例", "1", 0.1, 0.6, 0.3)

    n_total = sum(int(np.prod(p["shape"])) if p["shape"] else 1 for p in S)
    schema = {"version": "g0", "n_params": n_total, "area_function_source": src, "params": S}
    os.makedirs(os.path.join(REPO, "params"), exist_ok=True)
    json.dump(schema, open(os.path.join(REPO, "params", "schema.json"), "w"), ensure_ascii=False, indent=1)
    json.dump({"version": "g0", "parent": None, "values": {p["name"]: p["default"] for p in S}},
              open(os.path.join(REPO, "params", "g0.json"), "w"), ensure_ascii=False, indent=1)
    print("params:", len(S), "entries,", n_total, "numbers; area source:", src)


if __name__ == "__main__":
    main()
