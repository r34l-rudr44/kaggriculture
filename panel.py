"""Evaluate a candidate against frozen top-20 players (recorded tapes, same seeds).

python panel.py CAND.py [--params '{..}'] [--limit N] [--workers 8]
For each tape episode and each seat s, candidate plays seat s, the recorded player of seat 1-s is replayed.
Reports win rate, mean coins, mean frozen-opponent coins and keep ratio (opp coins / recorded).
"""
import argparse, glob, json, os
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(args):
    cand, ep, seat, params = args
    import fastsim, tapes
    from tourney import load_agent
    t = tapes.load(ep)
    me = load_agent(cand, params)
    opp = tapes.TapeAgent(ep, 1 - seat)
    agents = [None, None]
    agents[seat] = me
    agents[1 - seat] = opp
    r, _ = fastsim.play(agents[0], agents[1], t["seed"])
    return ep, seat, r[seat], r[1 - seat], t["rewards"][1 - seat], t["names"][1 - seat]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("--params", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    params = json.loads(a.params) if a.params else None
    eps = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(ROOT, "tapes", "*.json")))
    if a.limit:
        eps = eps[: a.limit]
    jobs = [(a.cand, ep, s, params) for ep in eps for s in (0, 1)]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(run, jobs))
    wins = sum(1 for r in res if r[2] > r[3])
    valid = [r for r in res if r[3] >= 0.95 * r[4]]
    vw = sum(1 for r in valid if r[2] > r[3])
    me = sum(r[2] for r in res) / len(res)
    op = sum(r[3] for r in res) / len(res)
    keep = sum(r[3] / max(1, r[4]) for r in res) / len(res)
    if a.verbose:
        for r in sorted(res, key=lambda r: r[2] - r[3]):
            print(f"{r[0]} seat{r[1]} me {r[2]:8.0f} opp {r[3]:8.0f} (rec {r[4]:8.0f}) {r[5]}")
    print(f"PANEL {a.cand}: wins {wins}/{len(res)} ({100*wins/len(res):.1f}%)  me {me:.0f}  opp {op:.0f}  "
          f"keep {keep:.2f}  | valid(keep>=.95) wins {vw}/{len(valid)}")


if __name__ == "__main__":
    main()
