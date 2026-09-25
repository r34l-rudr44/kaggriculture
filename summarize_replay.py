"""Condense a Kaggriculture replay JSON into a compact per-day text summary.

python summarize_replay.py replays/episode-X-replay.json [out.txt]
"""
import json, sys, collections

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]


def tile_key(t):
    if t is None:
        return "empty"
    if t == "LOCKED":
        return None
    k = t.get("kind")
    if k == "PLANT":
        return t["crop"].lower()
    if k == "WEED":
        return "weed"
    if t.get("animal"):
        return t["animal"].lower()
    return k.lower() + "_empty"


def summarize(path):
    j = json.load(open(path))
    steps = j["steps"]
    names = j["info"].get("TeamNames", ["p0", "p1"])
    out = []
    out.append(f"EPISODE {j['info'].get('EpisodeId')}  players: 0={names[0]}  1={names[1]}")
    out.append(f"final rewards: {[s['reward'] for s in steps[-1]]}")
    shops_seen = []
    for p in range(2):
        out.append("")
        out.append(f"=================== PLAYER {p}: {names[p]} ===================")
        day_orders = collections.defaultdict(collections.Counter)
        day_units = collections.defaultdict(collections.Counter)
        day_hands_max = collections.Counter()
        day_noop = collections.Counter()
        first_actions = []
        for st in range(1, len(steps)):
            a = steps[st][p].get("action") or {}
            prev_step = st - 1
            d = prev_step // 24
            if not isinstance(a, dict):
                continue
            mk = a.get("market") or []
            for o in mk:
                if not o or o == ["NOOP"] or (isinstance(o, list) and o and o[0] == "NOOP"):
                    day_noop[d] += 1
                    continue
                op = o[0]
                if op in ("HIRE", "BUY_LAND"):
                    day_orders[d][op] += 1
                elif len(o) >= 3:
                    try:
                        day_orders[d][f"{op}:{o[1]}"] += int(o[2])
                    except Exception:
                        pass
            units = [a.get("farmer") or ["PASS"]] + list(a.get("hands") or [])
            day_hands_max[d] = max(day_hands_max[d], len(units) - 1)
            for u in units:
                if isinstance(u, list) and u:
                    day_units[d][u[0]] += 1
            if prev_step < 30:
                first_actions.append(f"  step {prev_step:3d}: farmer={a.get('farmer')} hands={a.get('hands')} market={mk}")
        out.append("First 30 steps (actions):")
        out.extend(first_actions)
        out.append("Per day (obs at hour 0 of that day; orders/unit-actions aggregated over the day):")
        for d in range(30):
            st = d * 24
            if st >= len(steps):
                break
            obs0 = steps[st][0]["observation"]
            farm = obs0["farms"][p]
            priv = steps[st][p]["observation"].get("private", {}) or {}
            cnt = collections.Counter()
            for row in farm["tiles"]:
                for t in row:
                    k = tile_key(t)
                    if k:
                        cnt[k] += 1
            shed = {k: v for k, v in (priv.get("shed") or {}).items() if v}
            seeds = {k: v for k, v in (priv.get("seeds") or {}).items() if v}
            prices = obs0["market"]["prices"]
            shops = obs0.get("town", {}).get("unlocked_shops", [])
            out.append(f"D{d:02d} ${farm['money']:.0f} quads={len(farm['unlocked_quadrants'])} hands_max={day_hands_max[d]} tiles={dict(cnt)}")
            out.append(f"     shed={shed} seeds={seeds}")
            if p == 0:
                out.append(f"     prices={ {k: prices[k] for k in PRODUCTS} } shops={shops}")
            out.append(f"     orders={dict(day_orders[d])} noops={day_noop[d]}")
            out.append(f"     unit_actions={dict(day_units[d])}")
        out.append(f"FINAL money={steps[-1][0]['observation']['farms'][p]['money']:.0f}")
    return "\n".join(out)


if __name__ == "__main__":
    txt = summarize(sys.argv[1])
    if len(sys.argv) > 2:
        open(sys.argv[2], "w", encoding="utf-8").write(txt)
    else:
        print(txt)
