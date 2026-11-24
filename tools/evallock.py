"""eval.lock：对 eval/ 下全部文件（不含 __pycache__）算 SHA-256。

  python tools/evallock.py freeze   # 阶段 0.4：写 eval.lock 并去掉 eval/ 写权限
  python tools/evallock.py verify   # 每代第 1 步：逐文件核对，不符则退出码 1
"""
import os, sys, json, hashlib, stat

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL = os.path.join(REPO, "eval")
LOCK = os.path.join(REPO, "eval.lock")


def walk():
    for d, ds, fs in os.walk(EVAL):
        ds[:] = sorted(x for x in ds if x not in ("__pycache__", ".cache"))
        for f in sorted(fs):
            if f.endswith(".pyc"):
                continue
            yield os.path.join(d, f)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def freeze():
    files = {os.path.relpath(p, REPO): sha(p) for p in walk()}
    with open(LOCK, "w") as f:
        f.write(f"# eval.lock  {len(files)} files  SHA-256\n")
        for k in sorted(files):
            f.write(f"{files[k]}  {k}\n")
    for p in walk():
        os.chmod(p, os.stat(p).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    for d, ds, _ in os.walk(EVAL):
        os.chmod(d, os.stat(d).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    # 容器内以 root 运行时权限位无效，另加 ext4 不可变标记（符号链接不支持，忽略）
    import subprocess
    subprocess.run(f"find '{EVAL}' -name .cache -prune -o -print0 | xargs -0 chattr +i", shell=True,
                   stderr=subprocess.DEVNULL)
    print(f"frozen {len(files)} files")


def verify():
    want = {}
    for l in open(LOCK):
        if l.startswith("#") or not l.strip():
            continue
        h, p = l.rstrip("\n").split("  ", 1)
        want[p] = h
    have = {os.path.relpath(p, REPO) for p in walk()}
    bad = [p for p in want if p not in have or sha(os.path.join(REPO, p)) != want[p]]
    extra = sorted(have - set(want))
    ok = not bad and not extra
    print(json.dumps({"ok": ok, "files": len(want), "mismatch_or_missing": bad[:50], "unexpected": extra[:50]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(freeze() if sys.argv[1] == "freeze" else verify())
