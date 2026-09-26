"""Blind promotion gate. Nothing is submitted unless it passes this.

    python gate.py INCUMBENT.py CANDIDATE.py [--workers 10]

Both files are copied under neutral labels and every suite treats the two labels identically;
the mapping is revealed only when the pre-registered rule below is applied.

Suites (all seeds below are the sealed HOLDOUT; development work must never use them):
  farm    each label vs the strong reactive opponent, holdout seeds x both seats (paired)
  ladder  each label in our seat vs the frozen opponents of our real ladder games (ladder_set.json)
  top     each label vs frozen top-20 tapes (regression check)
  duel    label vs label, holdout seeds x both seats
"""
import argparse, hashlib, json, math, os, random, shutil, sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
STRONG = os.path.join(ROOT, "external", "farm2945", "farm2945.py")
OUR_NAME = "Yatharth Maheshwari"

# ---- pre-registered protocol; calibrated once on v6->v7 (known ladder gain), then frozen ---------------------------
HOLDOUT_SEED0 = 31000
HOLDOUT_SEEDS = 48          # x2 seats = 96 games per paired suite
RULE = {
    "farm_margin_se": 2.0,  # candidate - incumbent margin vs strong opponent must exceed 2 SE
    "ladder_win_slack": 1,  # candidate may win at most 1 fewer ladder game than the incumbent
    "ladder_margin_min": -500.0,
    "top_margin_se": 2.0,   # frozen top-20 tapes: not significantly worse (drop < 2 SE)
    "duel_rate_min": 0.55,  # and the 95% Wilson lower bound must exceed 0.50
}
# -----------------------------------------------------------------------------------------------


def _crn(K):
    if getattr(K, "_crn_patched", False):
        return
    orig = K._spawn_weeds
    count = {}

    def spawn(farm, board_size, weed_chance, rng):
        key = tuple(rng.getstate()[1][:4])
        k = count.get(key, 0)
        count[key] = k + 1
        return orig(farm, board_size, weed_chance, random.Random(hash((key, k))))

    K._spawn_weeds = spawn
    K._crn_patched = True


def _game(job):
    kind, label, path, other, seed, seat = job
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import fastsim, tapes
    from tourney import load_agent
    _crn(fastsim.K)
    me = load_agent(path)
    if kind == "tape":
        t = tapes.load(other)
        opp = tapes.TapeAgent(other, 1 - seat)
        seed = t["seed"]
    else:
        opp = load_agent(other)
    agents = [None, None]
    agents[seat], agents[1 - seat] = me, opp
    r, _ = fastsim.play(agents[0], agents[1], seed)
    return kind, label, str(other) if kind == "tape" else os.path.basename(other), seed, seat, r[seat], r[1 - seat]


def _paired(rows_a, rows_b):
    key = lambda r: (r[2], r[3], r[4])
    A = {key(r): r for r in rows_a}
    B = {key(r): r for r in rows_b}
    ks = sorted(set(A) & set(B))
    d = [(B[k][5] - B[k][6]) - (A[k][5] - A[k][6]) for k in ks]
    n = len(d)
    m = sum(d) / n
    se = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, n - 1)) / math.sqrt(n)
    wins = lambda R: sum(1 for k in ks if R[k][5] > R[k][6])
    margin = lambda R: sum(R[k][5] - R[k][6] for k in ks) / n
    return {"n": n, "margin_diff": m, "se": se, "wins_a": wins(A), "wins_b": wins(B),
            "margin_a": margin(A), "margin_b": margin(B)}


def _wilson_low(w, n, z=1.96):
    if n == 0:
        return 0.0
    p = w / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def _ladder_jobs(label, path):
    import tapes
    ids = json.load(open(os.path.join(ROOT, "ladder_set.json"))) if os.path.exists(os.path.join(ROOT, "ladder_set.json")) else []
    jobs = []
    for ep in ids:
        try:
            t = tapes.load(ep)
        except FileNotFoundError:
            continue
        if OUR_NAME in t["names"]:
            jobs.append(("tape", label, path, ep, 0, t["names"].index(OUR_NAME)))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("incumbent")
    ap.add_argument("candidate")
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()

    out_dir = os.path.join(ROOT, "results", "gate")
    os.makedirs(out_dir, exist_ok=True)
    digest = hashlib.sha1(open(a.incumbent, "rb").read() + open(a.candidate, "rb").read()).hexdigest()
    flip = int(digest, 16) % 2 == 1
    blind = {"X": a.candidate if flip else a.incumbent, "Y": a.incumbent if flip else a.candidate}
    paths = {}
    for label, src in blind.items():
        dst = os.path.join(out_dir, f"label_{label}.py")
        shutil.copyfile(src, dst)
        paths[label] = dst

    import glob
    ladder_file = os.path.join(ROOT, "ladder_set.json")
    ladder_ids = set(json.load(open(ladder_file))) if os.path.exists(ladder_file) else set()
    top_ids = [os.path.basename(f)[:-5] for f in sorted(glob.glob(os.path.join(ROOT, "tapes", "*.json")))]
    top_ids = [ep for ep in top_ids if ep not in ladder_ids]

    seeds = range(HOLDOUT_SEED0, HOLDOUT_SEED0 + HOLDOUT_SEEDS)
    jobs = []
    for label, path in paths.items():
        jobs += [("farm", label, path, STRONG, s, seat) for s in seeds for seat in (0, 1)]
        jobs += _ladder_jobs(label, path)
        jobs += [("tape", label, path, ep, 0, seat) for ep in top_ids for seat in (0, 1)]
    jobs += [("duel", "Y", paths["Y"], paths["X"], s, seat) for s in seeds for seat in (0, 1)]

    with ProcessPoolExecutor(a.workers) as ex:
        rows = list(ex.map(_game, jobs, chunksize=2))
    def suite(name, label):
        if name == "farm":
            return [r for r in rows if r[0] == "farm" and r[1] == label]
        if name == "ladder":
            return [r for r in rows if r[0] == "tape" and r[1] == label and r[2] in ladder_ids]
        if name == "top":
            return [r for r in rows if r[0] == "tape" and r[1] == label and r[2] not in ladder_ids]
    # unmask
    inc, cand = ("Y", "X") if flip else ("X", "Y")
    res = {s: _paired(suite(s, inc), suite(s, cand)) for s in ("farm", "ladder", "top")}
    duel = [r for r in rows if r[0] == "duel"]
    y_wins = sum(1 for r in duel if r[5] > r[6])
    y_margin = sum(r[5] - r[6] for r in duel) / max(1, len(duel))
    cand_wins = y_wins if cand == "Y" else len(duel) - y_wins - sum(1 for r in duel if r[5] == r[6])
    cand_margin = y_margin if cand == "Y" else -y_margin
    res["duel"] = {"n": len(duel), "cand_wins": cand_wins, "cand_margin": cand_margin,
                   "wilson_low": _wilson_low(cand_wins, len(duel))}

    checks = {
        "farm": res["farm"]["margin_diff"] > RULE["farm_margin_se"] * res["farm"]["se"],
        "ladder": (res["ladder"]["n"] == 0) or (res["ladder"]["wins_b"] >= res["ladder"]["wins_a"] - RULE["ladder_win_slack"]
                                                and res["ladder"]["margin_diff"] >= RULE["ladder_margin_min"]),
        "top": res["top"]["margin_diff"] > -RULE["top_margin_se"] * res["top"]["se"],
        "duel": res["duel"]["cand_wins"] / max(1, res["duel"]["n"]) >= RULE["duel_rate_min"] and res["duel"]["wilson_low"] > 0.5,
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"
    report = {"incumbent": a.incumbent, "candidate": a.candidate, "results": res, "checks": checks, "verdict": verdict,
              "rule": RULE, "holdout": [HOLDOUT_SEED0, HOLDOUT_SEEDS]}
    json.dump(report, open(os.path.join(out_dir, f"gate_{os.path.basename(a.candidate)[:-3]}.json"), "w"), indent=1)
    for s in ("farm", "ladder", "top"):
        r = res[s]
        print(f"{s:6s} n={r['n']:3d} margin inc {r['margin_a']:+8.0f} cand {r['margin_b']:+8.0f}  diff {r['margin_diff']:+7.0f} (SE {r['se']:.0f})"
              f"  wins {r['wins_a']} -> {r['wins_b']}   {'ok' if checks[s] else 'FAIL'}")
    d = res["duel"]
    print(f"duel   n={d['n']:3d} candidate wins {d['cand_wins']} ({100*d['cand_wins']/max(1,d['n']):.0f}%), margin {d['cand_margin']:+.0f}, "
          f"Wilson low {d['wilson_low']:.2f}   {'ok' if checks['duel'] else 'FAIL'}")
    print("VERDICT:", verdict)


if __name__ == "__main__":
    main()
