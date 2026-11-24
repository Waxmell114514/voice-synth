"""T0 物理层确定性单测。全部通过才计后续分数。"""
import os, sys, json, time, tempfile, importlib
import numpy as np
from common import REPO

PROBE_PINYIN = "a1 ba1 shi2 ma3 zi4 lv4 xue2 nong2 fei1 kuai4"
PROBE_TEXT = "我们明天去北京看长城。"


def _engine():
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    return importlib.import_module("engine.t0_api")


def test_uniform_tube():
    api = _engine()
    fs = int(api.FS)
    n = int(fs * 1.0)
    h = np.asarray(api.tube_impulse_response(np.full(44, 3.0), 17.5, n), dtype=float)
    if not np.isfinite(h).all():
        return False, {"error": "non-finite impulse response"}
    H = np.abs(np.fft.rfft(h * np.hanning(len(h)), 8 * n))
    f = np.fft.rfftfreq(8 * n, 1 / fs)
    sel = (f > 100) & (f < 3200)
    Hs, fsel = H[sel], f[sel]
    pk = [i for i in range(1, len(Hs) - 1) if Hs[i] > Hs[i - 1] and Hs[i] >= Hs[i + 1]
          and Hs[i] > 0.1 * Hs.max()]
    # 非极大抑制：300 Hz 内只留最高的峰（去掉窗函数旁瓣）
    keep = []
    for i in sorted(pk, key=lambda i: -Hs[i]):
        if all(abs(fsel[i] - fsel[j]) > 300 for j in keep):
            keep.append(i)
    peaks = sorted(float(fsel[i]) for i in keep)[:3]
    target = [500.0, 1500.0, 2500.0]
    ok = len(peaks) == 3 and all(abs(p - t) / t <= 0.02 for p, t in zip(peaks, target))
    return ok, {"peaks_hz": [round(p, 1) for p in peaks], "target_hz": target, "tol": 0.02}


def test_energy_decay(params_path):
    api = _engine()
    fs = int(api.FS)
    worst = 0.0
    for seed in (0, 1, 2):
        e = np.asarray(api.zero_input_energy(params_path, fs, seed), dtype=float)
        if not np.isfinite(e).all() or e[0] <= 0:
            return False, {"error": "energy non-finite or zero at start", "seed": seed}
        blk = max(1, fs // 1000)  # 1 ms 块
        eb = e[: len(e) // blk * blk].reshape(-1, blk).max(1)
        inc = np.max(np.diff(eb) / eb[0]) if len(eb) > 1 else 0.0
        worst = max(worst, float(inc))
        if inc > 1e-6 or e[-1] > e[0]:
            return False, {"error": "energy increased", "seed": seed, "max_rel_increase": float(inc)}
    return True, {"max_rel_increase_per_ms": worst, "final_over_initial": float(e[-1] / e[0])}


def _corner_params(schema, mode, rng):
    vals = {}
    for p in schema["params"]:
        shape = tuple(p.get("shape", []))
        lo, hi = float(p["min"]), float(p["max"])
        if mode == "min":
            v = np.full(shape, lo)
        elif mode == "max":
            v = np.full(shape, hi)
        else:
            v = np.where(rng.random(shape) < 0.5, lo, hi) if shape else (lo if rng.random() < 0.5 else hi)
        vals[p["name"]] = v.tolist() if hasattr(v, "tolist") else float(v)
    return {"values": vals}


def test_bounds(schema_path):
    import soundfile as sf
    from runner import EngineRunner
    schema = json.load(open(schema_path))
    rng = np.random.default_rng(12345)
    tmp = tempfile.mkdtemp(prefix="t0b_")
    files = []
    for mode in ["min", "max", "rand", "rand", "rand", "rand"]:
        pth = os.path.join(tmp, f"{mode}{len(files)}.json")
        json.dump(_corner_params(schema, mode, rng), open(pth, "w"))
        files.append(pth)
    report = []
    ok_all = True
    for pth in files:
        run = EngineRunner(pth)
        try:
            au = run.synth([("p", "pinyin", PROBE_PINYIN), ("t", "text", PROBE_TEXT)], seed=0)
        except Exception as e:
            ok_all = False; report.append({"file": os.path.basename(pth), "error": str(e)[:300]}); continue
        finally:
            run.close()
        for k, v in au.items():
            if v is None:
                ok_all = False; report.append({"file": os.path.basename(pth), "item": k, "error": "synth failed"}); continue
            raw = v[1]
            bad = (not np.isfinite(raw).all()) or np.abs(raw).max() >= 1.0 or len(raw) == 0
            # 发散：输出最后 10% 的 RMS 不得超过全局 RMS 的 10 倍
            if not bad and len(raw) > 100:
                tail = raw[-len(raw) // 10:]
                bad = np.sqrt(np.mean(tail ** 2)) > 10 * np.sqrt(np.mean(raw ** 2)) + 1e-9
            if bad:
                ok_all = False
                report.append({"file": os.path.basename(pth), "item": k,
                               "finite": bool(np.isfinite(raw).all()),
                               "peak": float(np.nanmax(np.abs(raw))) if len(raw) else None})
    return ok_all, {"corners_tested": len(files), "failures": report}


def test_determinism_and_rtf(params_path):
    from runner import EngineRunner
    run = EngineRunner(params_path)
    try:
        t = time.time()
        a = run.synth([("t", "text", PROBE_TEXT)], seed=7)["t"]
        el = time.time() - t
        b = run.synth([("t", "text", PROBE_TEXT)], seed=7)["t"]
        c = run.synth([("t", "text", PROBE_TEXT)], seed=8)["t"]
    finally:
        run.close()
    if a is None or b is None:
        return False, {"error": "synth failed"}, None
    same = a[1].shape == b[1].shape and np.array_equal(a[1], b[1])
    sr_ok = a[2] >= 16000
    dur = len(a[1]) / a[2]
    return same and sr_ok, {"reproducible": bool(same), "sample_rate": int(a[2]),
                            "seed_changes_output": bool(c is not None and not (c[1].shape == a[1].shape and np.array_equal(c[1], a[1])))}, el / max(dur, 1e-6)


def run_t0(params_path):
    schema_path = os.path.join(REPO, "params", "schema.json")
    res = {}
    try:
        res["uniform_tube"] = test_uniform_tube()
        res["energy_decay"] = test_energy_decay(os.path.abspath(params_path))
        res["bounds"] = test_bounds(schema_path)
        ok, info, rtf = test_determinism_and_rtf(params_path)
        res["determinism"] = (ok, info)
    except Exception as e:
        import traceback
        return {"pass": False, "error": traceback.format_exc()[-1500:]}
    out = {k: {"pass": bool(v[0]), **v[1]} for k, v in res.items()}
    out["pass"] = all(v[0] for v in res.values())
    out["real_time_factor"] = round(rtf, 3) if rtf else None
    return out


if __name__ == "__main__":
    print(json.dumps(run_t0(sys.argv[1]), indent=1, ensure_ascii=False))
