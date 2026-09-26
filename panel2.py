"""Low-variance A/B panel (evaluation-only engine patch, does not modify any project file).

python panel2.py agents/CAND.py [--params JSON] [--K 1] [--crn 1] [--limit N] [--workers 3] [--tag name] [--ladder]
  --ladder: also play the tapes listed in ladder_set.json. They are left out by default because gate.py
            scores them as held-out evidence, so tuning on them would leak into the gate.
  --crn 1 : weed spawning uses its own RNG stream, so the town shop sequence depends only on
            (seed, day) and is identical for every candidate variant (common random numbers).
  --K k   : play each tape seat on k seeds (original seed + k-1 derived seeds).
Prints mean me/opp, wins; writes per-game results to results_<tag>.json for paired comparison.
"""
import argparse, glob, json, os, sys, random
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.join(ROOT, "results")


def _patch(K):
    if getattr(K, "_crn_patched", False):
        return
    orig = K._spawn_weeds
    cnt = {}

    def spawn(farm, board_size, weed_chance, rng):
        fp = tuple(rng.getstate()[1][:4])
        k = cnt.get(fp, 0)
        cnt[fp] = k + 1
        sub = random.Random(hash((fp, k)))
        return orig(farm, board_size, weed_chance, sub)

    K._spawn_weeds = spawn
    K._crn_patched = True


def run(args):
    cand, ep, seat, kk, params, crn = args
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import fastsim, tapes
    from tourney import load_agent
    if crn:
        _patch(fastsim.K)
    t = tapes.load(ep)
    me = load_agent(cand, params)
    opp = tapes.TapeAgent(ep, 1 - seat)
    ag = [None, None]
    ag[seat] = me
    ag[1 - seat] = opp
    seed = t["seed"] + kk * 7919
    r, _ = fastsim.play(ag[0], ag[1], seed)
    return ep, seat, kk, r[seat], r[1 - seat]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("--params", default=None)
    ap.add_argument("--K", type=int, default=1)
    ap.add_argument("--crn", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--ladder", action="store_true")
    a = ap.parse_args()
    params = json.loads(a.params) if a.params else None
    eps = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(ROOT, "tapes", "*.json")))
    ladder_file = os.path.join(ROOT, "ladder_set.json")
    if not a.ladder and os.path.exists(ladder_file):
        held_out = set(json.load(open(ladder_file)))
        eps = [ep for ep in eps if ep not in held_out]
    if a.limit:
        eps = eps[: a.limit]
    jobs = [(os.path.abspath(a.cand), ep, s, k, params, a.crn) for ep in eps for s in (0, 1) for k in range(a.K)]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(run, jobs, chunksize=2))
    n = len(res)
    wins = sum(1 for r in res if r[3] > r[4])
    me = sum(r[3] for r in res) / n
    op = sum(r[4] for r in res) / n
    tag = a.tag or (os.path.basename(a.cand).replace(".py", "") + ("_" + a.params if a.params else ""))
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in tag)[:80]
    os.makedirs(HERE, exist_ok=True)
    json.dump(res, open(os.path.join(HERE, f"results_{safe}.json"), "w"))
    print(f"PANEL2 {tag}: n={n} wins {wins} ({100*wins/n:.1f}%)  me {me:.0f}  opp {op:.0f}  margin {me-op:+.0f}")


if __name__ == "__main__":
    main()
