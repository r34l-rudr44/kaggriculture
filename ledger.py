"""Exact money ledger for a game by instrumenting the engine.

python ledger.py tape EP            # replay both recorded tapes of an episode
python ledger.py vs CAND.py EP SEAT # candidate in SEAT vs frozen tape of the other seat
Prints per-player revenue by product, costs by category, and income by day.
"""
import sys, collections
import fastsim
K = fastsim.K

LOG = []
_cur = {"step": 0}


def install():
    orig_commit = K._commit_unit
    orig_hire = K._do_hire
    orig_land = K._do_buy_land

    def commit(op, item, price, farm, private, market, shed_capacity=100):
        before = farm["money"]
        ok = orig_commit(op, item, price, farm, private, market, shed_capacity)
        if ok:
            LOG.append((_cur["step"], id(farm), op, item, farm["money"] - before))
        return ok

    def hire(farm, private, board_size, mult=1):
        before = farm["money"]
        orig_hire(farm, private, board_size, mult)
        if farm["money"] != before:
            LOG.append((_cur["step"], id(farm), "HIRE", "", farm["money"] - before))

    def land(farm, board_size):
        before = farm["money"]
        orig_land(farm, board_size)
        if farm["money"] != before:
            LOG.append((_cur["step"], id(farm), "LAND", "", farm["money"] - before))

    K._commit_unit = commit
    K._do_hire = hire
    K._do_buy_land = land
    orig_interp = K.interpreter

    def interp(state, env):
        try:
            _cur["step"] = state[0].observation.get("step", 0)
        except Exception:
            pass
        return orig_interp(state, env)

    K.interpreter = interp


def report(state, names):
    farms = state[0].observation.farms
    ids = [id(f) for f in farms]
    for p in range(2):
        rev = collections.Counter()
        units = collections.Counter()
        cost = collections.Counter()
        by_day = collections.Counter()
        for step, fid, op, item, delta in LOG:
            if fid != ids[p]:
                continue
            by_day[step // 24] += delta
            if op == "SELL":
                rev[item] += delta
                units[item] += 1
            else:
                cost[f"{op}:{item}" if item else op] += -delta
        print(f"=== player {p} {names[p]} final {farms[p]['money']:.0f}")
        print("  revenue:", ", ".join(f"{k} {v:.0f} ({units[k]}u @{v/max(1,units[k]):.0f})" for k, v in rev.most_common()))
        print("  total revenue", sum(rev.values()))
        print("  costs:", ", ".join(f"{k} {v:.0f}" for k, v in cost.most_common()))
        print("  net by day:", " ".join(f"d{d}:{by_day[d]:.0f}" for d in range(30)))


if __name__ == "__main__":
    import tapes
    install()
    if sys.argv[1] == "tape":
        ep = sys.argv[2]
        t = tapes.load(ep)
        r, st = fastsim.play(tapes.TapeAgent(ep, 0), tapes.TapeAgent(ep, 1), t["seed"])
        report(st, t["names"])
    elif sys.argv[1] == "vs":
        from tourney import load_agent
        cand, ep, seat = sys.argv[2], sys.argv[3], int(sys.argv[4])
        t = tapes.load(ep)
        ag = [None, None]
        ag[seat] = load_agent(cand)
        ag[1 - seat] = tapes.TapeAgent(ep, 1 - seat)
        r, st = fastsim.play(ag[0], ag[1], t["seed"])
        names = list(t["names"])
        names[seat] = "CANDIDATE " + cand
        report(st, names)
