"""Paired head-to-head: python h2h.py CAND OPP [OPP2..] --seeds N --params JSON --tag T
Plays CAND vs each OPP on seeds seed0..seed0+N-1 in BOTH seats (CRN weed patch), saves per-game
results to results/h2h_<tag>.json. Compare two runs with: python h2h.py --cmp A.json B.json"""
import argparse, json, os, sys, random, math
from concurrent.futures import ProcessPoolExecutor
ROOT = os.path.dirname(os.path.abspath(__file__))
HERE = ROOT


def _patch(K):
    if getattr(K, "_crn_patched", False):
        return
    orig = K._spawn_weeds
    cnt = {}

    def spawn(farm, board_size, weed_chance, rng):
        fp = tuple(rng.getstate()[1][:4])
        k = cnt.get(fp, 0)
        cnt[fp] = k + 1
        return orig(farm, board_size, weed_chance, random.Random(hash((fp, k))))
    K._spawn_weeds = spawn
    K._crn_patched = True


def run(args):
    cand, opp, seed, seat, params = args
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import fastsim
    from tourney import load_agent
    _patch(fastsim.K)
    a = load_agent(cand, params)
    b = load_agent(opp)
    ag = [b, b]
    ag[seat] = a
    r, _ = fastsim.play(ag[0], ag[1], seed)
    return os.path.basename(opp), seed, seat, r[seat], r[1 - seat]


def cmp(fa, fb):
    A = {(r[0], r[1], r[2]): r for r in json.load(open(fa))}
    B = {(r[0], r[1], r[2]): r for r in json.load(open(fb))}
    for opp in sorted(set(k[0] for k in B)):
        ks = sorted(k for k in set(A) & set(B) if k[0] == opp)
        if not ks:
            continue
        d = [B[k][3] - A[k][3] for k in ks]
        dm = [(B[k][3] - B[k][4]) - (A[k][3] - A[k][4]) for k in ks]
        n = len(d)
        def ms(v):
            m = sum(v) / n
            return m, math.sqrt(sum((x - m) ** 2 for x in v) / max(1, n - 1)) / math.sqrt(n)
        m, se = ms(d); mm, sem = ms(dm)
        wa = sum(1 for k in ks if A[k][3] > A[k][4]); wb = sum(1 for k in ks if B[k][3] > B[k][4])
        print(f"  vs {opp:16s} n={n} me diff {m:+.0f} (SE {se:.0f})  margin diff {mm:+.0f} (SE {sem:.0f})  wins {wa} -> {wb}")


def main():
    if sys.argv[1] == "--cmp":
        cmp(sys.argv[2], sys.argv[3]); return
    ap = argparse.ArgumentParser()
    ap.add_argument("cand"); ap.add_argument("opps", nargs="+")
    ap.add_argument("--seeds", type=int, default=12); ap.add_argument("--seed0", type=int, default=5000)
    ap.add_argument("--params", default=None); ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", required=True); ap.add_argument("--seats", default="0,1")
    a = ap.parse_args()
    params = json.loads(a.params) if a.params else None
    jobs = [(os.path.abspath(a.cand), os.path.abspath(o), a.seed0 + s, seat, params)
            for o in a.opps for s in range(a.seeds) for seat in [int(x) for x in a.seats.split(",")]]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(run, jobs, chunksize=1))
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "results", f"h2h_{a.tag}.json"), "w"))
    for o in a.opps:
        o = os.path.basename(o)
        rs = [r for r in res if r[0] == o]
        w = sum(1 for r in rs if r[3] > r[4]); l = sum(1 for r in rs if r[3] < r[4])
        me = sum(r[3] for r in rs) / len(rs); op = sum(r[4] for r in rs) / len(rs)
        print(f"H2H {a.tag} vs {o:16s} W-L {w}-{l}  me {me:.0f} opp {op:.0f} margin {me-op:+.0f}")


if __name__ == "__main__":
    main()
