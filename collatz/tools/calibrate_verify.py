#!/usr/bin/env python3
"""Phase 0.3: run statement/verify.sh on every sample in calibration/verify_samples/.

Each sample runs in a fresh copy of the repository (without .lake/, with .lake/packages
symlinked read-only from the main checkout) so that patches cannot leak between samples.
Usage: tools/calibrate_verify.py [-j 4] [sample ...]
Writes calibration/verify_results.json and prints one line per theorem checked.
"""
import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "calibration", "verify_samples")
WORK = os.path.join(ROOT, ".lake", "calib")


def prepare(name, spec):
    wd = os.path.join(WORK, name)
    shutil.rmtree(wd, ignore_errors=True)
    shutil.copytree(ROOT, wd, ignore=shutil.ignore_patterns(".lake", "calibration", ".git"))
    os.makedirs(os.path.join(wd, ".lake"))
    os.symlink(os.path.join(ROOT, ".lake", "packages"), os.path.join(wd, ".lake", "packages"))
    shutil.copy(os.path.join(SAMPLES, name, "Sample.lean"), os.path.join(wd, "lib", "Lib", "Sample.lean"))
    with open(os.path.join(wd, "lib", "Lib.lean"), "a") as f:
        f.write("import Lib.Sample\n")
    if "gaps" in spec:
        with open(os.path.join(wd, "routes", "gaps.tsv"), "a") as f:
            f.write(spec["gaps"])
    if "patch" in spec:
        path, old, new = spec["patch"]
        p = os.path.join(wd, path)
        s = open(p).read()
        assert old in s, (name, old)
        os.chmod(p, 0o644)
        open(p, "w").write(s.replace(old, new, 1))
    if "extra" in spec:
        path, content = spec["extra"]
        open(os.path.join(wd, path), "w").write(content)
    return wd


def parse(out):
    lines = out.strip().splitlines()
    first = lines[0] if lines else ""
    res = {"verdict": first.split(" ")[0] if first else "?", "first_line": first}
    for l in lines[1:]:
        l = l.strip()
        for key in ("claim", "final", "gaps", "axioms"):
            if l.startswith(key + ": "):
                res[key] = l[len(key) + 2:]
    return res


def run_sample(name, spec):
    t0 = time.time()
    wd = prepare(name, spec)
    results = []
    for thm in [spec["thm"]] + spec.get("also", []):
        r = subprocess.run([os.path.join(wd, "statement", "verify.sh"), thm], cwd=wd,
                           capture_output=True, text=True, timeout=3 * 3600)
        got = parse(r.stdout + r.stderr)
        got["exit"] = r.returncode
        ok = got["verdict"] == spec["verdict"]
        for key in ("claim", "final"):
            if key in spec:
                ok = ok and got.get(key) == spec[key]
        results.append({"thm": thm, "expected": {k: spec[k] for k in ("verdict", "claim", "final") if k in spec},
                        "got": got, "correct": ok})
    shutil.rmtree(wd, ignore_errors=True)
    return name, results, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("only", nargs="*")
    a = ap.parse_args()
    expected = json.load(open(os.path.join(SAMPLES, "expected.json")))
    names = a.only or sorted(expected)
    os.makedirs(WORK, exist_ok=True)
    out = {}
    with cf.ThreadPoolExecutor(a.j) as ex:
        futs = [ex.submit(run_sample, n, expected[n]) for n in names]
        for fut in cf.as_completed(futs):
            name, results, secs = fut.result()
            out[name] = {"results": results, "seconds": secs}
            for r in results:
                mark = "OK " if r["correct"] else "BAD"
                print(f"{mark} {name:32s} {r['thm']:32s} expected={r['expected']} got={r['got']['first_line'][:110]}"
                      f" claim={r['got'].get('claim')} final={r['got'].get('final')} ({secs}s)", flush=True)
    path = os.path.join(ROOT, "calibration", "verify_results.json")
    json.dump(dict(sorted(out.items())), open(path, "w"), indent=1, ensure_ascii=False)
    total = sum(len(v["results"]) for v in out.values())
    good = sum(r["correct"] for v in out.values() for r in v["results"])
    print(f"{good}/{total} correct")


if __name__ == "__main__":
    main()
