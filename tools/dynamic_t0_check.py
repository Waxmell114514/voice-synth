"""T0 补充检查（提案 003-B，Critic 必查项；非正式分数，不进 eval/）。

  python tools/dynamic_t0_check.py <params.json> [--parent-root <另一棵引擎代码树> --parent-params <父版本参数>]

在当前目录的引擎上做两项检查：
1. 逐采样能量：engine.t0_api.zero_input_energy 在给定参数及若干“低损耗角点”下，
   存储能量逐采样不得上升（相对 e[0] 的上升 ≤ 1e-12，即舍入级）。
   eval/t0.py 只比较 1 ms 块最大值且容差 1e-6，漏过了 g0 的鼻腔结点 bug。
2. 动态瞬态：合成含软腭开合与元音切换的序列，测 6 kHz 以上的“咔哒”：
   每 2 ms 帧的高通 RMS，报告 max / 中位数（有声段内）。与父版本对比，明显变大即可疑。
"""
import os, sys, json, argparse, subprocess, tempfile
import numpy as np

SEQS = {"velum": "a1 ma1 an1 na1 ang1 a1 mang2 nan2",
        "vowels": "a1 yi1 wu1 a1 yu1 o1 e1 a1",
        "mixed": "ni3 hao3 ma1 wo3 men5 nan2 fang1"}
CORNERS = [{}, {"wall_loss": 0.0, "r_glottis": 1.0, "r_lip": 0.995, "r_nose": 0.995}]


def energy_check(params_path, root):
    sys.path.insert(0, root)
    for m in [k for k in list(sys.modules) if k == "engine" or k.startswith("engine.")]:
        del sys.modules[m]
    from engine.t0_api import zero_input_energy, FS
    base = json.load(open(params_path))
    out = []
    for ci, corner in enumerate(CORNERS):
        p = dict(base); p["values"] = dict(base.get("values", {}), **corner)
        # 新增损耗参数一律取 0（最难的角点）：名字含 loss 的标量
        if ci == 1:
            for k, v in list(p["values"].items()):
                if "loss" in k and isinstance(v, (int, float)):
                    p["values"][k] = 0.0
        tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); json.dump(p, tf); tf.close()
        worst = -np.inf
        for sd in (0, 1, 2):
            e = np.asarray(zero_input_energy(tf.name, int(FS * 0.5), sd), float)
            worst = max(worst, float(np.max(np.diff(e) / e[0])))
        os.remove(tf.name)
        out.append({"corner": ci, "max_rel_rise_per_sample": worst, "pass": worst <= 1e-12})
    sys.path.remove(root)
    return out


def click_metric(root, params_path, pinyin):
    tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); tf.close()
    subprocess.run([sys.executable, "-m", "engine.synth", "--pinyin", pinyin, "--seed", "0",
                    "--params", os.path.abspath(params_path), "--out", tf.name], cwd=root, check=True,
                   capture_output=True)
    import soundfile as sf
    from scipy.signal import butter, sosfilt
    x, sr = sf.read(tf.name); os.remove(tf.name)
    hp = sosfilt(butter(4, 6000, "highpass", fs=sr, output="sos"), x)
    fr = int(0.002 * sr)
    n = len(x) // fr
    r = np.array([np.sqrt(np.mean(hp[i * fr:(i + 1) * fr] ** 2)) for i in range(n)])
    e = np.array([np.sqrt(np.mean(x[i * fr:(i + 1) * fr] ** 2)) for i in range(n)])
    act = e > 0.05 * e.max()
    if act.sum() < 5:
        return None
    return float(r[act].max() / (np.median(r[act]) + 1e-12))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("params")
    ap.add_argument("--parent-root", default=None)
    ap.add_argument("--parent-params", default=None)
    a = ap.parse_args()
    root = os.getcwd()
    res = {"energy": energy_check(a.params, root), "clicks": {}}
    for k, s in SEQS.items():
        c = {"this": click_metric(root, a.params, s)}
        if a.parent_root:
            c["parent"] = click_metric(a.parent_root, a.parent_params or a.params, s)
        res["clicks"][k] = c
    res["energy_pass"] = all(x["pass"] for x in res["energy"])
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
