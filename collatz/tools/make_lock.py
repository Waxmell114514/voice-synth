#!/usr/bin/env python3
"""Write eval.lock: SHA-256 of statement/**, toolchain files, and (at freeze) bootstrap.md, roles/, config.yaml.
Usage: tools/make_lock.py [--freeze]"""
import hashlib, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()
files = ["lakefile.toml", "lean-toolchain", "lake-manifest.json"]
for d, _, fs in os.walk(os.path.join(ROOT, "statement")):
    if "__pycache__" in d: continue
    files += [os.path.relpath(os.path.join(d, f), ROOT) for f in fs if not f.endswith(".pyc")]
if "--freeze" in sys.argv:
    files += ["bootstrap.md", "config.yaml"]
    files += [os.path.join("roles", f) for f in sorted(os.listdir(os.path.join(ROOT, "roles")))]
lock = {"version": 1, "frozen": "--freeze" in sys.argv,
        "files": {f: sha(os.path.join(ROOT, f)) for f in sorted(files)}}
json.dump(lock, open(os.path.join(ROOT, "eval.lock"), "w"), indent=1, ensure_ascii=False)
print(f"eval.lock: {len(files)} files")
