"""合成执行器：引擎（常驻 worker 调 engine.synth.main）、eSpeak NG 基线、真人录音。"""
import os, sys, json, hashlib, subprocess, tempfile, threading, queue
import numpy as np
from common import ROOT, REPO, DATA
import models as M

ESPEAK = os.path.join(ROOT, "tools", "espeak-ng")
WORKERS = int(os.environ.get("EVAL_SYNTH_WORKERS", "4"))


# ------------------------------------------------------------------ 引擎
class _SubprocPool:
    """N 个常驻 python 子进程（eval/_worker.py），与评估器进程完全隔离。"""

    def __init__(self, n):
        env = dict(os.environ, OMP_NUM_THREADS="1", PYTHONHASHSEED="0")
        w = os.path.join(ROOT, "_worker.py")
        self.procs = [subprocess.Popen([sys.executable, "-I", w], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       text=True, cwd=REPO, env=env, bufsize=1) for _ in range(n)]

    def map(self, fn_unused, jobs, chunksize=1):
        q = queue.Queue()
        for i, j in enumerate(jobs):
            q.put((i, j))
        res = [None] * len(jobs)

        def drive(p):
            while True:
                try:
                    i, j = q.get_nowait()
                except queue.Empty:
                    return
                p.stdin.write(json.dumps(j) + "\n"); p.stdin.flush()
                line = p.stdout.readline()
                res[i] = tuple(json.loads(line)) if line else (1, "worker died")
        ts = [threading.Thread(target=drive, args=(p,)) for p in self.procs]
        [t.start() for t in ts]; [t.join() for t in ts]
        return res

    def terminate(self):
        for p in self.procs:
            try:
                p.stdin.close(); p.wait(timeout=10)
            except Exception:
                p.kill()


class EngineRunner:
    def __init__(self, params_path, tmpdir=None):
        self.params = os.path.abspath(params_path)
        self.tmp = tempfile.mkdtemp(prefix="evsyn_", dir=tmpdir)
        self.pool = _SubprocPool(WORKERS)
        self.checked = False

    def _argv(self, kind, content, seed, out):
        return [f"--{kind}", content, "--seed", str(seed), "--params", self.params, "--out", out]

    def synth(self, items, seed):
        """items: [(key, 'text'|'pinyin', content)] -> {key: (wav16k, raw, sr)}，失败为 None。"""
        jobs, outs = [], []
        for k, kind, content in items:
            out = os.path.join(self.tmp, hashlib.md5(f"{k}|{seed}".encode()).hexdigest() + ".wav")
            jobs.append(self._argv(kind, content, seed, out)); outs.append(out)
        res = self.pool.map(None, jobs)
        if not self.checked and jobs:
            self._check_subprocess(jobs[0], outs[0])
        import soundfile as sf
        r = {}
        for (k, _, _), out, (rc, err) in zip(items, outs, res):
            if rc != 0 or not os.path.exists(out):
                r[k] = None
                if err and not getattr(self, "_err_shown", False):
                    sys.stderr.write(f"[engine error] {k}: {err}\n"); self._err_shown = True
                continue
            x, sr = sf.read(out, dtype="float32", always_2d=True)
            x = x.mean(1)
            os.remove(out)
            r[k] = (M.resample(x, sr, 16000), x, sr)
        return r

    def _check_subprocess(self, argv, out_inproc):
        """常驻 worker 与真实命令行调用必须逐样本一致。"""
        import soundfile as sf
        self.checked = True
        if not os.path.exists(out_inproc):
            return
        a = sf.read(out_inproc, dtype="int16")[0]
        out2 = out_inproc + ".cli.wav"
        argv2 = list(argv); argv2[-1] = out2
        p = subprocess.run([sys.executable, "-m", "engine.synth"] + argv2, cwd=REPO,
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0 or not os.path.exists(out2):
            raise RuntimeError("nondeterministic: CLI call failed: " + p.stderr[-1500:])
        b = sf.read(out2, dtype="int16")[0]
        os.remove(out2)
        if a.shape != b.shape or not np.array_equal(a, b):
            raise RuntimeError("nondeterministic: worker output differs from CLI output")

    def close(self):
        self.pool.terminate()
        try:
            os.rmdir(self.tmp)
        except OSError:
            pass


# ------------------------------------------------------------------ eSpeak NG 基线
class EspeakRunner:
    """基线吃汉字（用它自己的前端）。seed 无效。"""

    def __init__(self, voice="cmn"):
        self.voice = voice
        self.tmp = tempfile.mkdtemp(prefix="evesp_")

    def _one(self, kc):
        k, kind, content = kc
        out = os.path.join(self.tmp, hashlib.md5(k.encode()).hexdigest() + ".wav")
        env = dict(os.environ, LD_LIBRARY_PATH=os.path.join(ESPEAK, "lib"))
        subprocess.run([os.path.join(ESPEAK, "bin", "espeak-ng"), "--path=" + os.path.join(ESPEAK, "share"),
                        "-v", self.voice, "-w", out, content], env=env, check=True, capture_output=True)
        return out

    def synth(self, items, seed):
        import soundfile as sf
        from concurrent.futures import ThreadPoolExecutor
        for _, kind, _ in items:
            assert kind in ("hanzi",), "eSpeak 基线只接收汉字"
        with ThreadPoolExecutor(WORKERS) as ex:
            outs = list(ex.map(self._one, items))
        r = {}
        for (k, _, _), out in zip(items, outs):
            x, sr = sf.read(out, dtype="float32", always_2d=True); x = x.mean(1); os.remove(out)
            r[k] = (M.resample(x, sr, 16000), x, sr)
        return r

    def close(self):
        pass


# ------------------------------------------------------------------ 真人录音
class HumanRunner:
    def synth(self, items, seed):
        import soundfile as sf
        r = {}
        for k, kind, utt in items:
            assert kind == "utt"
            x, sr = sf.read(os.path.join(DATA, "wav", utt + ".wav"), dtype="float32", always_2d=True)
            x = x.mean(1)
            r[k] = (M.resample(x, sr, 16000), x, sr)
        return r

    def close(self):
        pass
