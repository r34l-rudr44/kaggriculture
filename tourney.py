"""Parallel tournament on fastsim.

python tourney.py CANDIDATE.py OPP1.py [OPP2.py ...] --seeds 20 [--params '{"k":v}'] [--workers 8]
Each .py must expose make_agent(params=None) (or a last-callable agent).
Reports per-opponent W-L, mean coins, mean margin.
"""
import argparse, importlib.util, json, os, sys
from concurrent.futures import ProcessPoolExecutor


def load_agent(path, params=None):
    name = "m_" + os.path.basename(path).replace(".py", "").replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, os.path.abspath(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if params:
        return mod.make_agent(params)
    # Kaggle's rule: the last callable defined in the module is the agent.
    fns = [v for v in vars(mod).values() if callable(v)]
    return fns[-1]


def run_one(args):
    cand, opp, seed, swap, params = args
    import fastsim
    a = load_agent(cand, params)
    b = load_agent(opp)
    if swap:
        r, _ = fastsim.play(b, a, seed)
        return opp, seed, r[1], r[0]
    r, _ = fastsim.play(a, b, seed)
    return opp, seed, r[0], r[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("opps", nargs="+")
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--seed0", type=int, default=5000)
    ap.add_argument("--params", default=None)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    params = json.loads(a.params) if a.params else None
    jobs = [(a.cand, o, a.seed0 + s, s % 2 == 1, params) for o in a.opps for s in range(a.seeds)]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(run_one, jobs))
    tot_w = tot_n = 0
    for o in a.opps:
        rs = [(m, t) for (oo, s, m, t) in res if oo == o]
        w = sum(1 for m, t in rs if m > t)
        l = sum(1 for m, t in rs if m < t)
        tot_w += w
        tot_n += len(rs)
        mm = sum(m for m, t in rs) / len(rs)
        mt = sum(t for m, t in rs) / len(rs)
        print(f"vs {o:28s} W-L {w:3d}-{l:<3d} me {mm:9.0f} opp {mt:9.0f} margin {mm-mt:+8.0f}")
    print(f"TOTAL win rate {tot_w}/{tot_n} = {100*tot_w/max(1,tot_n):.1f}%")


if __name__ == "__main__":
    main()
