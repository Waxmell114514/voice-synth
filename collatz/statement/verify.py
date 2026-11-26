#!/usr/bin/env python3
"""The fleet's only judge. Frozen after phase 0.4.

Usage: statement/verify.sh <theorem full name>

Prints PASS or FAIL on the first line, then details. Exit code 0 on PASS, 1 on FAIL.
Checks, in order (see bootstrap.md, "验证接口"):
  1. statement/ and the toolchain files hash to the values in eval.lock.
  2. Source scan of lib/: forbidden tokens, imports, stray files.
  3. `lake build` with zero errors and zero `sorry`.
  4. Lean inspection of the theorem: it exists, is a theorem declared in a Lib module,
     its axioms are a subset of {propext, Classical.choice, Quot.sound} plus registered gaps,
     every axiom declared in Lib is registered in routes/gaps.tsv, no Lib constant reuses a
     name of the frozen statement, no axiom/opaque occurs in the theorem's type.
     Claim check: statement/Final.lean with the theorem substituted elaborates or not.
  5. leanchecker replays Statement and every Lib module through the kernel.
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
STATEMENT_NAMES = {"collatzStep", "CollatzConjecture", "statement_eq_upstream"}
TOOLCHAIN_FILES = ["lakefile.toml", "lean-toolchain", "lake-manifest.json"]
IMPORT_OK = ("Mathlib", "Batteries", "Aesop", "Qq", "Plausible", "Lean", "Std", "Init",
             "Statement", "Lib")
FORBIDDEN = [
    (r"\bsorry\b", "sorry"),
    (r"\badmit\b", "admit"),
    (r"\bnative_decide\b", "native_decide"),
    (r"\bnative\b", "native evaluation"),
    (r"\bunsafe\b", "unsafe"),
    (r"\bimplemented_by\b", "implemented_by"),
    (r"\bextern\b", "extern"),
    (r"\bdebug\.", "debug option"),
    (r"skipKernelTC", "kernel check disabled"),
    (r"\bofReduceBool\b|\breduceBool\b|\btrustCompiler\b", "compiler-trusting axiom"),
    (r"\baddDecl\b|\baddAndCompile\b|\bmodifyEnv\b|\bsetEnv\b|\bKernel\.", "environment hacking"),
]

ENV = dict(os.environ)
ENV["PATH"] = os.path.expanduser("~/.elan/bin") + os.pathsep + ENV.get("PATH", "")


class Fail(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_lock():
    lock_path = os.path.join(ROOT, "eval.lock")
    if not os.path.exists(lock_path):
        raise Fail("eval.lock missing")
    with open(lock_path) as f:
        lock = json.load(f)["files"]
    present = set(TOOLCHAIN_FILES)
    for dirpath, _, files in os.walk(os.path.join(ROOT, "statement")):
        for fn in files:
            if fn.endswith(".pyc") or "__pycache__" in dirpath:
                continue
            present.add(os.path.relpath(os.path.join(dirpath, fn), ROOT))
    for rel in sorted(present):
        if rel not in lock:
            raise Fail(f"eval.lock: file not locked: {rel}")
    for rel, digest in sorted(lock.items()):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            raise Fail(f"eval.lock: locked file missing: {rel}")
        if sha256(p) != digest:
            raise Fail(f"eval.lock: hash mismatch: {rel}")


def strip_comments_and_strings(src):
    out = []
    i, n, depth = 0, len(src), 0
    while i < n:
        if depth > 0:
            if src.startswith("/-", i):
                depth += 1
                i += 2
            elif src.startswith("-/", i):
                depth -= 1
                i += 2
            else:
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
        elif src.startswith("/-", i):
            depth = 1
            i += 2
        elif src.startswith("--", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src[i] == '"':
            i += 1
            while i < n and src[i] != '"':
                i += 2 if src[i] == "\\" else 1
            i += 1
            out.append('""')
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def scan_sources():
    lib = os.path.join(ROOT, "lib")
    for dirpath, _, files in os.walk(lib):
        for fn in files:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, ROOT)
            if not fn.endswith(".lean"):
                continue
            relmod = os.path.relpath(p, lib)
            if not (relmod == "Lib.lean" or relmod.startswith("Lib" + os.sep)):
                raise Fail(f"stray Lean file outside the Lib library: {rel}")
            with open(p, encoding="utf-8") as f:
                code = strip_comments_and_strings(f.read())
            for lineno, line in enumerate(code.splitlines(), 1):
                for pat, what in FORBIDDEN:
                    if re.search(pat, line):
                        raise Fail(f"forbidden ({what}) at {rel}:{lineno}")
                m = re.match(r"\s*(?:public\s+|private\s+|meta\s+)*import\s+(.*)", line)
                if m:
                    for mod in m.group(1).split():
                        if mod.split(".")[0] not in IMPORT_OK:
                            raise Fail(f"import not allowed: {mod} at {rel}:{lineno}")


def run(cmd, timeout):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True, text=True,
                          timeout=timeout)


def lake_build():
    r = run(["lake", "build"], timeout=6 * 3600)
    log = r.stdout + r.stderr
    if r.returncode != 0:
        errs = [l for l in log.splitlines() if "error" in l][:5]
        raise Fail("lake build failed: " + " | ".join(errs))
    if re.search(r"declaration uses ['`]sorry['`]", log):
        raise Fail("lake build: declaration uses sorry")


def load_gaps():
    gaps = {}
    p = os.path.join(ROOT, "routes", "gaps.tsv")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 4 or parts[1] not in ("L", "O"):
                    raise Fail(f"routes/gaps.tsv: malformed line: {line.strip()}")
                gaps[parts[0]] = parts[1]
    return gaps


def lean_file(text, timeout=3600):
    d = os.path.join(ROOT, ".lake", "verify")
    os.makedirs(d, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".lean", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        return run(["lake", "env", "lean", path], timeout=timeout)
    finally:
        os.unlink(path)


def inspect(thm):
    if not re.fullmatch(r"[A-Za-z_\u0080-￿][\w.'\u0080-￿!?₀-₉]*", thm):
        raise Fail(f"bad theorem name: {thm!r}")
    with open(os.path.join(ROOT, "statement", "Inspect.lean.in"), encoding="utf-8") as f:
        tmpl = f.read()
    r = lean_file(tmpl.replace("__THM__", thm))
    facts = {"libconst": [], "typeconst": [], "axiom": []}
    for line in (r.stdout + r.stderr).splitlines():
        i = line.find("VERIFY\t")
        if i < 0:
            continue
        _, key, val = line[i:].split("\t", 2)
        if key in facts:
            facts[key].append(val)
        else:
            facts[key] = val
    if r.returncode != 0 or "found" not in facts:
        raise Fail("inspection failed: " + (r.stdout + r.stderr).strip()[:500])
    return facts


def claim_check(thm):
    with open(os.path.join(ROOT, "statement", "Final.lean"), encoding="utf-8") as f:
        tmpl = f.read()
    r = lean_file(tmpl.replace("CLAIMED_PROOF", "@" + thm))
    return r.returncode == 0 and not re.search(r"\d+:\d+: error", r.stdout + r.stderr)


def main():
    if len(sys.argv) != 2:
        print("usage: statement/verify.sh <theorem full name>")
        return 2
    thm = sys.argv[1]
    details = []
    try:
        check_lock()
        scan_sources()
        lake_build()
        gaps = load_gaps()
        facts = inspect(thm)
        lib_modules = set()
        for row in facts["libconst"]:
            mod, name, kind = row.split("\t")
            lib_modules.add(mod)
            if name.split(".")[-1] in STATEMENT_NAMES:
                raise Fail(f"Lib redefines a frozen statement name: {name} ({mod})")
            if kind == "axiom" and name not in gaps:
                raise Fail(f"unregistered axiom in Lib: {name} ({mod})")
        if facts["found"] != "yes":
            raise Fail(f"theorem not found: {thm}")
        if facts["kind"] != "theorem":
            raise Fail(f"{thm} is a {facts['kind']}, not a theorem")
        if not (facts["module"] == "Lib" or facts["module"].startswith("Lib.")):
            raise Fail(f"{thm} is declared in {facts['module']}, not in the Lib library")
        used_gaps = []
        for a in facts["axiom"]:
            if a in STD_AXIOMS:
                continue
            if a == "sorryAx":
                raise Fail("depends on sorryAx")
            if a in gaps:
                used_gaps.append(f"{a} [{gaps[a]}]")
                continue
            raise Fail(f"depends on non-standard, unregistered axiom: {a}")
        lib_in_type = []
        for row in facts["typeconst"]:
            mod, name, kind = row.split("\t")
            if mod == "Lib" or mod.startswith("Lib."):
                if kind in ("axiom", "opaque"):
                    raise Fail(f"type of {thm} mentions Lib {kind} {name}")
                lib_in_type.append(name)
        claim = claim_check(thm)
        mods = ["Statement"] + sorted(lib_modules | {"Lib"})
        # one module per call: leanchecker re-imports the environment for every module argument,
        # so memory grows with the number of arguments (measured: 4 modules > 14 GB)
        # and only one leanchecker at a time on the machine (all worktrees share one memory limit)
        lockdir = os.path.expanduser("~/.cache")
        os.makedirs(lockdir, exist_ok=True)
        with open(os.path.join(lockdir, "collatz-leanchecker.lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            for mod in mods:
                r = run(["lake", "env", "leanchecker", mod], timeout=6 * 3600)
                if r.returncode != 0:
                    raise Fail(f"leanchecker {mod} exit {r.returncode}: "
                               + (r.stdout + r.stderr).strip()[:500])
        details += [
            f"theorem: {thm}",
            f"module: {facts['module']}",
            f"type: {facts.get('type', '?')}",
            f"axioms: {sorted(facts['axiom'])}",
            f"gaps: {used_gaps}",
            f"lib_constants_in_type: {sorted(lib_in_type)}",
            f"claim: {'CollatzConjecture' if claim else 'lemma'}",
            f"final: {'PASS' if claim and not used_gaps else 'n/a'}",
            f"leanchecker: ok ({len(mods)} modules)",
        ]
    except Fail as e:
        print(f"FAIL {thm}: {e}")
        return 1
    except subprocess.TimeoutExpired as e:
        print(f"FAIL {thm}: timeout: {e.cmd}")
        return 1
    print(f"PASS {thm}")
    for d in details:
        print("  " + d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
