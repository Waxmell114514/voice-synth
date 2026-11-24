"""常驻合成 worker：独立 python 进程，stdin 每行一个 JSON argv，stdout 每行一个 JSON 结果。
刻意不导入评估器的任何模块，保证进程里只有引擎自己的代码和依赖。"""
import os, sys, json, io, contextlib, importlib, traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    os.chdir(REPO)
    sys.path[:] = [REPO] + [p for p in sys.path if os.path.abspath(p or ".") != os.path.dirname(os.path.abspath(__file__))]
    out = sys.stdout
    sys.stdout = io.StringIO()  # 引擎的 print 不得污染协议
    for line in sys.stdin:
        argv = json.loads(line)
        try:
            mod = importlib.import_module("engine.synth")
            rc = mod.main(list(argv)) or 0
            err = ""
        except SystemExit as e:
            rc, err = int(e.code or 0), ""
        except Exception:
            rc, err = 1, traceback.format_exc()[-2000:]
        sys.stdout = io.StringIO()
        out.write(json.dumps([rc, err]) + "\n"); out.flush()


if __name__ == "__main__":
    main()
