"""Validate a submission file the way Kaggle loads it.

python validate.py agents/v5_x.py
Checks: loads via Kaggle's last-callable rule, plays 2 full games (self-play + vs agents/v5_script.py)
without exceptions, max/mean per-turn time, no disallowed imports.
"""
import ast, sys, time, traceback, importlib.util, os
import fastsim

BANNED = {"subprocess", "socket", "requests", "urllib", "http", "shutil", "ctypes", "multiprocessing"}


def last_callable(path):
    src = open(path, encoding="utf-8").read()
    ns = {"__name__": "submission", "__file__": os.path.abspath(path)}
    exec(compile(src, path, "exec"), ns)
    fns = [v for v in ns.values() if callable(v)]
    return fns[-1], src


def main(path):
    ok = True
    agent, src = last_callable(path)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                if n.split(".")[0] in BANNED:
                    print("BANNED IMPORT", n)
                    ok = False
    print("entry point:", getattr(agent, "__name__", agent))
    times = []
    errors = []

    def wrap(fn):
        def f(obs, cfg=None):
            t = time.perf_counter()
            try:
                return fn(obs, cfg)
            except Exception:
                errors.append(traceback.format_exc())
                raise
            finally:
                times.append(time.perf_counter() - t)
        return f

    a2, _ = last_callable(path)
    r, _ = fastsim.play(wrap(agent), wrap(a2), 777)
    print("self-play rewards", r)
    from tourney import load_agent
    a3, _ = last_callable(path)
    r2, _ = fastsim.play(wrap(a3), load_agent("agents/v5_script.py"), 778)
    print("vs v5_script rewards", r2)
    if errors:
        ok = False
        print("EXCEPTIONS:", len(errors))
        print(errors[0])
    print(f"per-turn time: mean {1000*sum(times)/len(times):.1f} ms, max {1000*max(times):.1f} ms")
    if max(times) > 0.5:
        print("WARNING: a turn exceeded 0.5s")
        ok = False
    print("VALID" if ok else "INVALID")


if __name__ == "__main__":
    main(sys.argv[1])
