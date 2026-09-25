"""Kaggriculture agent v5 'evolve' (evolved from main.py v4).

Per turn:
  1. Day 0: scripted all-in opening (2 cows + 3 sheep on a shed ring, 4 hands, 6 melons, 10 wheat).
  2. Survey farm, estimate town demand, set herd / crop targets.
  3. Keep a persistent tile plan (structures near the shed, crops outside).
  4. Build per-tile work orders (bursts: FEED-CARE-COLLECT-HARVEST, FERT-WATER, WATER-HARVEST-PLANT-WATER).
  5. Greedy unit->tile matching by value - lambda*distance, morning wheat / fertilizer pickups.
  6. Market: steep sells first, hires, other sells, land, animals, seeds, feed wheat.
"""
import math
import collections

N = 10
HALF = N // 2
TPD = 24
DAYS = 30
LAST_STEP = 718

SHED_TILES = ((HALF - 1, HALF - 1), (HALF, HALF - 1), (HALF - 1, HALF), (HALF, HALF))
SHED_SET = frozenset(SHED_TILES)

CROPS = {
    "WHEAT":      {"seed": 10, "first_yield_day": 2, "max_yield_day": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20, "first_yield_day": 2, "max_yield_day": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50, "first_yield_day": 8, "max_yield_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80, "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}
ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
MARKET_PARAMS = {
    "WHEAT":      {"base":  25, "I0": 10000, "T": 400, "below_func": "sqrt",   "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base":  35, "I0": 10000, "T": 450, "below_func": "hinge",  "below_target": 1.00, "above_func": "sqrt",   "above_target": 0.70},
    "TOMATO":     {"base":  60, "I0": 10000, "T": 200, "below_func": "hinge",  "below_target": 0.40, "above_func": "sqrt",   "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "below_func": "sqrt",   "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "I0": 10000, "T": 300, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.60},
    "EGG":        {"base":  50, "I0": 10000, "T": 332, "below_func": "hinge",  "below_target": 0.40, "above_func": "log",    "above_target": 0.20},
    "MILK":       {"base": 160, "I0": 10000, "T": 122, "below_func": "sqrt",   "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "I0": 10000, "T": 105, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": 10000, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}
SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
# expected daily consumption added by one future (random) shop
FUTURE_SHOP_RATE = {p: 0.0 for p in PRODUCTS}
for _s, _prods in SHOPS.items():
    for _p in _prods:
        FUTURE_SHOP_RATE[_p] += (12.0 if len(_prods) == 1 else 6.0) / len(SHOPS)
LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]
SELL_PRIO = {"WOOL": 0, "MILK": 1, "STRAWBERRY": 2, "MELON": 3, "TOMATO": 4, "EGG": 5, "CARROT": 6,
             "FERTILIZER": 7, "WHEAT": 8}
STEEP = ("WOOL", "MILK", "STRAWBERRY", "MELON")
ANIMAL_OP_ORDER = {"COLLECT_FERTILIZER": 0, "HARVEST": 1, "FEED": 2, "CARE": 3}
FIB = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987]


def _shape(func, x, T=None):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "hinge":
        u = x / T
        return u + 8.0 * max(0.0, u - 1.0) ** 2
    return x


def market_price(item, inv):
    p = MARKET_PARAMS[item]
    base, I0, T = p["base"], p["I0"], p["T"]
    if inv < I0:
        f = p["below_func"]
        price = base + p["below_target"] * base / _shape(f, T, T) * _shape(f, I0 - inv, T)
    else:
        f = p["above_func"]
        price = base - p["above_target"] * base / _shape(f, T, T) * _shape(f, inv - I0, T)
    return max(1, int(round(price)))


def sell_proceeds(item, inv, n):
    """Revenue of selling n units starting at market inventory inv."""
    tot = 0
    for _ in range(n):
        pr = market_price(item, inv)
        tot += pr
        if pr > 1:
            inv += 1
    return tot, inv


UNLOCK_DAYS = (3, 6, 9, 12, 15, 18, 21, 24)
A_RATE = {"SHEEP": 4.0 / 3.0, "COW": 1.5, "GOOSE": 2.0}
A_LAG = {"SHEEP": 6, "COW": 8, "GOOSE": 4}
STRAW_AGES = (10, 12, 14, 16)
TOMATO_AGES = (8, 9, 10, 11)


def mm_revenue(p, inv0, day, cons, opp, ours):
    """Projected revenue of our daily supply `ours[t]` of product p from day `day` to the end."""
    inv = float(inv0)
    rev = 0.0
    for t in range(day, DAYS):
        i = t - day
        s = ours[i]
        net = opp[i] + s - cons[i]
        if s > 0:
            rev += s * market_price(p, int(inv + 0.5 * net))
        inv += net
    return rev


def quadrant_of(x, y):
    return ("N" if y < HALF else "S") + ("W" if x < HALF else "E")


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


DSHED = {}
NEAR_SHED = {}
for _y in range(N):
    for _x in range(N):
        _best = min(SHED_TILES, key=lambda s: (dist((_x, _y), s), s))
        DSHED[(_x, _y)] = dist((_x, _y), _best)
        NEAR_SHED[(_x, _y)] = _best


def step_toward(pos, target):
    x, y = pos
    tx, ty = target
    if x < tx:
        return "EAST"
    if x > tx:
        return "WEST"
    if y < ty:
        return "SOUTH"
    if y > ty:
        return "NORTH"
    return "PASS"


def g(o, k, d=None):
    if isinstance(o, dict):
        return o.get(k, d)
    return getattr(o, k, d)


# Day-0 opening, copied from a top-10 replay (2 cows + 3 sheep ring the shed, 6 melons, 10 wheat, 4 hands).
SCRIPT_D0 = [
    {"farmer": ["PASS"], "hands": [], "market": [["HIRE"], ["HIRE"], ["HIRE"], ["HIRE"], ["BUY_PRODUCT", "WHEAT", 4], ["BUY_ANIMAL", "COW", 2], ["BUY_SEED", "MELON", 6], ["BUY_ANIMAL", "SHEEP", 3], ["BUY_SEED", "WHEAT", 9]]},
    {"farmer": ["PICKUP", "COW", 1], "hands": [["PICKUP", "SHEEP", 1], ["PICKUP", "SHEEP", 1], ["PICKUP", "COW", 1], ["PICKUP", "SHEEP", 1]], "market": [["BUY_SEED", "WHEAT", 1]]},
    {"farmer": ["PICKUP", "WHEAT", 1], "hands": [["PICKUP", "WHEAT", 1], ["PICKUP", "WHEAT", 1], ["WEST"], ["PICKUP", "WHEAT", 1]], "market": []},
    {"farmer": ["WEST"], "hands": [["WEST"], ["NORTH"], ["NORTH"], ["NORTH"]], "market": []},
    {"farmer": ["NORTH"], "hands": [["WEST"], ["NORTH"], ["BUILD_PASTURE"], ["NORTH"]], "market": []},
    {"farmer": ["BUILD_PASTURE"], "hands": [["BUILD_PASTURE"], ["BUILD_PASTURE"], ["PLACE", "COW"], ["BUILD_PASTURE"]], "market": []},
    {"farmer": ["PLACE", "COW"], "hands": [["PLACE", "SHEEP"], ["PLACE", "SHEEP"], ["DROP"], ["PLACE", "SHEEP"]], "market": []},
    {"farmer": ["FEED"], "hands": [["FEED"], ["FEED"], ["WEST"], ["FEED"]], "market": []},
    {"farmer": ["CARE"], "hands": [["CARE"], ["CARE"], ["WEST"], ["CARE"]], "market": []},
    {"farmer": ["EAST"], "hands": [["EAST"], ["SOUTH"], ["WEST"], ["SOUTH"]], "market": []},
    {"farmer": ["SOUTH"], "hands": [["DROP"], ["DROP"], ["WEST"], ["SOUTH"]], "market": []},
    {"farmer": ["DROP"], "hands": [["WEST"], ["WEST"], ["NORTH"], ["DROP"]], "market": []},
    {"farmer": ["WEST"], "hands": [["WEST"], ["WEST"], ["PLANT", "WHEAT"], ["NORTH"]], "market": []},
    {"farmer": ["NORTH"], "hands": [["WEST"], ["PLANT", "MELON"], ["WATER"], ["NORTH"]], "market": []},
    {"farmer": ["NORTH"], "hands": [["PLANT", "MELON"], ["WATER"], ["NORTH"], ["NORTH"]], "market": []},
    {"farmer": ["PLANT", "MELON"], "hands": [["WATER"], ["NORTH"], ["PLANT", "WHEAT"], ["PLANT", "MELON"]], "market": []},
    {"farmer": ["WATER"], "hands": [["NORTH"], ["PLANT", "MELON"], ["WATER"], ["WATER"]], "market": []},
    {"farmer": ["WEST"], "hands": [["NORTH"], ["WATER"], ["NORTH"], ["NORTH"]], "market": []},
    {"farmer": ["NORTH"], "hands": [["PLANT", "WHEAT"], ["WEST"], ["PLANT", "WHEAT"], ["PLANT", "MELON"]], "market": []},
    {"farmer": ["PLANT", "WHEAT"], "hands": [["WATER"], ["NORTH"], ["WATER"], ["WATER"]], "market": []},
    {"farmer": ["WATER"], "hands": [["NORTH"], ["NORTH"], ["NORTH"], ["WEST"]], "market": []},
    {"farmer": ["NORTH"], "hands": [["NORTH"], ["PLANT", "WHEAT"], ["PLANT", "WHEAT"], ["PLANT", "WHEAT"]], "market": []},
    {"farmer": ["PLANT", "WHEAT"], "hands": [["PLANT", "WHEAT"], ["WATER"], ["WATER"], ["WATER"]], "market": []},
    {"farmer": ["WATER"], "hands": [["WATER"], ["PASS"], ["PASS"], ["PASS"]], "market": []},
]

DEFAULT_PARAMS = {
    "script": True,
    "lam": 10.0,             # value of one step of walking
    "stick": 50.0,           # bonus for staying on the current tile
    "melon_target": 10,      # early melons (D0-D1)
    "melon_last_day": 1,
    "straw_base": 10,
    "straw_per_shop": 7,
    "straw_cap": 40,
    "straw_last_day": 13,
    "tomato_per_shop": 5,
    "tomato_cap": 12,
    "tomato_first_day": 7,
    "tomato_last_day": 18,
    "sheep_base": 3,
    "sheep_per_yarn": 6,
    "sheep_cap": 18,
    "cow_base": 2,
    "cow_per_shop": 3,
    "cow_cap": 12,
    "goose_per_shop": 2,
    "goose_cap": 4,
    "animal_last_day": 18,
    "future_weight": 0.5,
    "max_hands": 11,
    "min_hands_early": 4,
    "move_mult": 2.3,
    "min_hands_mid": 7,
    "min_hands_late": 10,
    "land_days": (4, 6, 8),
    "land_last_day": 15,
    "land_reserve": 150,
    "cash_reserve": 30,
    "fert_keep_price": 40,
    "wheat_fert_price": 25,
    "crash_frac": 0.3,
    "pick_cap": 5,
    "labor_cap": 1000.0,
    "convert_last_day": -1,
    "melon_plan_last_day": 4,
    "urg_prod": True,
    "fert_drop_feeders": True,
    "melon_drop": 0.3,
    "land_max": 2,
    "zoning": False,
    "seed_buffer": 0,
    "zone_free_day": 5,
    "zone_w_max": 4,
    "surv_cap": 300.0,
    "mm": True,
    "mm_future_w": 0.5,
    "opp_growth": 0.5,
    "mm_labor": 10.0,
    "opp_scale": 1.0,
    "opp_scale_p": {},
    "straw_min": 0,
    "mm_carrot": True,
    "mm_future_w_p": {},
    "carrot_cap": 30,
    "goose_cap_hi": 10,
    "egg_hi": 75,
    "tick_n": 80,
    "tick_day": 8,
    "wheat_keep": False,
    "surv_mode": 1,
    "spent_full": True,
    "plant_deadline": True,
    "plan_valid": True,
    "urg_hour": 12,
    "urg_div": 4.0,
    "ratio_k": 0.0,
    "stick_mult": 1.25,
    "stay_mult": 3.0,
    "gate_feed": True,
    "land_free": 8,
    "drop_early": 0.5,
    "drop_late": 0.1,
    "shed_min": 30.0,
}


def make_agent(params=None):
    P = dict(DEFAULT_PARAMS)
    if params:
        P.update(params)
    MEM = {}

    def act(obs, config=None):
        try:
            return _act(obs, P, MEM)
        except Exception:  # never crash on the ladder
            return {"farmer": ["PASS"], "hands": [], "market": []}

    return act


def _script(step, me, priv, mem):
    if step == 0:
        if float(me["money"]) < 2990 or me["hands"]:
            mem["script"] = False
            return None
        mem["script"] = True
    if not mem.get("script"):
        return None
    if step >= 1 and len(me["hands"]) != 4:
        mem["script"] = False
        return None
    if step == 1:
        shed = priv["shed"]
        if int(shed.get("COW", 0)) < 2 or int(shed.get("SHEEP", 0)) < 3 or int(shed.get("WHEAT", 0)) < 4:
            mem["script"] = False
            return None
    a = SCRIPT_D0[step]
    out = {"farmer": list(a["farmer"]), "hands": [list(h) for h in a["hands"]],
           "market": [list(o) for o in a["market"]]}
    for act in [out["farmer"]] + out["hands"]:
        if act[0] == "PLANT" and act[1] == "MELON":
            mem["melons_planted"] = mem.get("melons_planted", 0) + 1
    return out


def _mm_targets(P, day, shops, minv, prices, tiles, opp, a_count, stock, animals, plants):
    """Demand-sized targets from a projected market (town consumption, visible rival assets, our assets)."""
    H = DAYS - day
    n_left = max(0, 8 - len(shops))
    cons = {}
    for p in ("WOOL", "MILK", "EGG", "STRAWBERRY", "TOMATO", "CARROT"):
        base = 1.0
        for s_ in shops:
            prods = SHOPS.get(s_, [])
            if p in prods:
                base += 12.0 if len(prods) == 1 else 6.0
        arr = []
        for i in range(H):
            t = day + i
            k = min(n_left, sum(1 for u in UNLOCK_DAYS if day < u <= t))
            arr.append(base + P["mm_future_w_p"].get(p, P["mm_future_w"]) * k * FUTURE_SHOP_RATE[p])
        cons[p] = arr
    growth = [1.0 + P["opp_growth"] * max(0.0, min(1.0, (min(day + i, 12) - day) / 12.0)) for i in range(H)]
    opp_s = {p: [0.0] * H for p in cons}
    if opp is not None:
        for row in opp["tiles"]:
            for t in row:
                if not isinstance(t, dict):
                    continue
                if t.get("animal"):
                    a = t["animal"]
                    p = ANIMALS[a]["product"]
                    start = t["placed_day"] + A_LAG[a] - day
                    for i in range(max(0, start), H):
                        opp_s[p][i] += A_RATE[a] * growth[i]
                elif t.get("kind") == "PLANT" and t["crop"] in ("STRAWBERRY", "TOMATO"):
                    ages = STRAW_AGES if t["crop"] == "STRAWBERRY" else TOMATO_AGES
                    for a_ in ages:
                        i = t["planted_day"] + a_ - day
                        if 0 <= i < H:
                            opp_s[t["crop"]][i] += 2.0
                elif t.get("kind") == "PLANT" and t["crop"] == "CARROT":
                    for i in range(max(0, t["planted_day"] + 3 - day), H):
                        opp_s["CARROT"][i] += 4.0 / 3.0
        # rival crop plantings still to come (scaled like their herd)
        for p in ("STRAWBERRY", "TOMATO", "CARROT"):
            for i in range(H):
                opp_s[p][i] *= growth[i]
        for p in opp_s:
            sc = P["opp_scale"] * P["opp_scale_p"].get(p, 1.0)
            for i in range(H):
                opp_s[p][i] *= sc
    ours = {p: [0.0] * H for p in cons}
    for (pos, t) in animals:
        a = t["animal"]
        p = ANIMALS[a]["product"]
        start = t["placed_day"] + A_LAG[a] - day
        for i in range(max(0, start), H):
            ours[p][i] += A_RATE[a]
    for a in ANIMALS:
        n = stock[a]
        p = ANIMALS[a]["product"]
        for i in range(min(H, A_LAG[a] + 1), H):
            ours[p][i] += A_RATE[a] * n
    for (pos, t) in plants:
        if t["crop"] in ("STRAWBERRY", "TOMATO"):
            ages = STRAW_AGES if t["crop"] == "STRAWBERRY" else TOMATO_AGES
            for a_ in ages:
                i = t["planted_day"] + a_ - day
                if 0 <= i < H:
                    ours[t["crop"]][i] += 2.0
        elif t["crop"] == "CARROT":
            for i in range(max(0, t["planted_day"] + 3 - day), H):
                ours["CARROT"][i] += 4.0 / 3.0
    if P.get("debug"):
        proj = {}
        for p in cons:
            inv = float(minv[p])
            arr = []
            for i in range(H):
                net = opp_s[p][i] + ours[p][i] - cons[p][i]
                arr.append(market_price(p, int(inv + 0.5 * net)))
                inv += net
            proj[p] = arr
        P["_proj"] = proj
    fert_v = min(60.0, float(prices["FERTILIZER"]))
    lab = P["mm_labor"]
    feed = max(25.0, float(prices["WHEAT"]))
    out = {}
    for a in ANIMALS:
        p = ANIMALS[a]["product"]
        cur = a_count[a] + stock[a]
        prof = [0.0] * H
        first = min(H, 1 + A_LAG[a])
        for i in range(first, H):
            prof[i] = A_RATE[a]
        days_alive = max(0, H - 1)
        unit_cost = ANIMALS[a]["cost"] + days_alive * (feed + 3.5 * lab - fert_v)
        best_n, prev = cur, mm_revenue(p, minv[p], day, cons[p], opp_s[p], ours[p])
        base = list(ours[p])
        for k in range(1, 16):
            arr = [base[i] + k * prof[i] for i in range(H)]
            rv = mm_revenue(p, minv[p], day, cons[p], opp_s[p], arr)
            if rv - prev < unit_cost:
                break
            prev = rv
            best_n = cur + k
        out[a] = best_n
    for c, ages, seedc, fert_n, labn in (("STRAWBERRY", STRAW_AGES, 100, 2, 14), ("TOMATO", TOMATO_AGES, 50, 2, 10)):
        cur = sum(1 for (_, t) in plants if t["crop"] == c)
        prof = [0.0] * H
        for a_ in ages:
            i = 1 + a_
            if i < H:
                prof[i] += 2.0
        unit_cost = seedc + fert_n * fert_v + labn * lab
        prev = mm_revenue(c, minv[c], day, cons[c], opp_s[c], ours[c])
        base = list(ours[c])
        best = cur
        for k in range(1, 50):
            arr = [base[i] + k * prof[i] for i in range(H)]
            rv = mm_revenue(c, minv[c], day, cons[c], opp_s[c], arr)
            if rv - prev < unit_cost:
                break
            prev = rv
            best = cur + k
        out[c] = best
    # carrots: continuously replanted tiles (4 carrots per 3 days with fertilizer)
    c = "CARROT"
    cur = sum(1 for (_, t) in plants if t["crop"] == c)
    prof = [0.0] * H
    for i in range(min(H, 4), H):
        prof[i] = 4.0 / 3.0
    unit_cost = max(0, H - 1) * (20.0 / 3.0 + 2.0 * lab + fert_v / 3.0)
    prev = mm_revenue(c, minv[c], day, cons[c], opp_s[c], ours[c])
    base = list(ours[c])
    best = cur
    for k in range(1, 40):
        arr = [base[i] + k * prof[i] for i in range(H)]
        rv = mm_revenue(c, minv[c], day, cons[c], opp_s[c], arr)
        if rv - prev < unit_cost:
            break
        prev = rv
        best = cur + k
    out[c] = best
    return out


def _prod_days(t):
    """Production days (end of day p) of an animal tile."""
    a = ANIMALS[t["animal"]]
    p0 = t["placed_day"] + a["first_yield_day"] - 1
    return p0, a["interval"]


def _next_prod(t, day):
    """First production day p >= day (production happens at end of day p)."""
    p0, iv = _prod_days(t)
    if day <= p0:
        return p0
    k = (day - p0 + iv - 1) // iv
    return p0 + k * iv


def _act(obs, P, MEM):
    me_id = int(g(obs, "player", 0) or 0)
    mem = MEM.setdefault(me_id, {})
    step = int(g(obs, "step", 0) or 0)
    farms = g(obs, "farms")
    me = farms[me_id]
    priv = g(obs, "private")
    if step < len(SCRIPT_D0) and P["script"]:
        a = _script(step, me, priv, mem)
        if a is not None:
            return a
    opp = farms[1 - me_id] if len(farms) > 1 else None
    market = g(obs, "market")
    town = g(obs, "town", None) or {}
    day, hour = divmod(step, TPD)
    days_left = DAYS - day
    last_day = day == DAYS - 1

    tiles = me["tiles"]
    money = float(me["money"])
    shed = {k: int(v) for k, v in dict(priv["shed"]).items()}
    seeds = {k: int(v) for k, v in dict(priv["seeds"]).items()}
    units = [tuple(me["farmer"])] + [tuple(h) for h in me["hands"]]
    invs = [{k: int(v) for k, v in dict(i).items() if int(v) > 0} for i in priv["inventories"]]
    while len(invs) < len(units):
        invs.append({})
    invs = invs[:len(units)]
    n_units = len(units)
    minv = {k: int(v) for k, v in dict(market["inventory"]).items()}
    prices = {k: int(v) for k, v in dict(market["prices"]).items()}
    shops = list(g(town, "unlocked_shops", []) or [])
    unlocked = list(me["unlocked_quadrants"])
    hires_today = int(me.get("hires_today", 0)) if isinstance(me, dict) else int(g(me, "hires_today", 0))

    # ------------------------------------------------------------------ survey
    plants, animals, empty_structs, weeds, empties = [], [], [], [], []
    a_count = {a: 0 for a in ANIMALS}
    c_count = {c: 0 for c in CROPS}
    n_past = n_coop = 0
    for y in range(N):
        row = tiles[y]
        for x in range(N):
            t = row[x]
            if t is None:
                empties.append((x, y))
            elif t == "LOCKED":
                continue
            elif isinstance(t, dict):
                k = t.get("kind")
                if k == "PLANT":
                    plants.append(((x, y), t))
                    c_count[t["crop"]] += 1
                elif k == "WEED":
                    weeds.append((x, y))
                else:
                    if k == "PASTURE":
                        n_past += 1
                    elif k == "COOP":
                        n_coop += 1
                    if t.get("animal"):
                        animals.append(((x, y), t))
                        a_count[t["animal"]] += 1
                    else:
                        empty_structs.append(((x, y), k))
    held = {}
    for inv in invs:
        for k, v in inv.items():
            held[k] = held.get(k, 0) + v
    stock = {a: shed.get(a, 0) + held.get(a, 0) for a in ANIMALS}

    opp_a = {a: 0 for a in ANIMALS}
    opp_c = {c: 0 for c in CROPS}
    if opp is not None:
        for row in opp["tiles"]:
            for t in row:
                if isinstance(t, dict):
                    if t.get("animal"):
                        opp_a[t["animal"]] += 1
                    elif t.get("kind") == "PLANT":
                        opp_c[t["crop"]] += 1

    # ------------------------------------------------------------------ demand
    cons = {p: (0.0 if p == "FERTILIZER" else 1.0) for p in PRODUCTS}
    for s in shops:
        prods = SHOPS.get(s, [])
        m = 12.0 if len(prods) == 1 else 6.0
        for p in prods:
            cons[p] += m
    n_future = 0
    if len(shops) < 8:
        n_future = min(8 - len(shops), len([d for d in range(3, 25, 3) if d > day]))
    fw = P["future_weight"]
    eff = {p: cons[p] + fw * n_future * FUTURE_SHOP_RATE[p] for p in PRODUCTS}
    n_yarn = shops.count("YARN_STORE")

    # ------------------------------------------------------------------ targets
    def shop_units(rate_per_shop, prod):
        # effective number of shops consuming prod (fractional incl. future)
        return max(0.0, (eff[prod] - 1.0) / rate_per_shop)

    sheep_t = min(P["sheep_cap"], P["sheep_base"] + int(round(P["sheep_per_yarn"] * shop_units(12.0, "WOOL"))))
    cow_t = min(P["cow_cap"], P["cow_base"] + int(round(P["cow_per_shop"] * shop_units(6.0, "MILK"))))
    goose_t = min(P["goose_cap"], int(round(P["goose_per_shop"] * shop_units(6.0, "EGG"))))
    base_p = {p: MARKET_PARAMS[p]["base"] for p in PRODUCTS}
    if prices["WOOL"] < 0.45 * base_p["WOOL"]:
        sheep_t = min(sheep_t, a_count["SHEEP"] + stock["SHEEP"])
    if prices["MILK"] < 0.45 * base_p["MILK"]:
        cow_t = min(cow_t, a_count["COW"] + stock["COW"])
    if prices["EGG"] < 0.6 * base_p["EGG"]:
        goose_t = min(goose_t, a_count["GOOSE"] + stock["GOOSE"])
    if day > P["animal_last_day"]:
        sheep_t = min(sheep_t, a_count["SHEEP"] + stock["SHEEP"])
        cow_t = min(cow_t, a_count["COW"] + stock["COW"])
        goose_t = min(goose_t, a_count["GOOSE"] + stock["GOOSE"])
    straw_t = min(P["straw_cap"], P["straw_base"] + int(round(P["straw_per_shop"] * shop_units(6.0, "STRAWBERRY"))))
    tomato_t = min(P["tomato_cap"], int(round(P["tomato_per_shop"] * shop_units(6.0, "TOMATO"))))
    carrot_t = 0
    if P["mm"] and not last_day:
        key = (day, len(shops))
        if mem.get("mm_key") != key or hour == 0:
            mem["mm_key"] = key
            mem["mm_t"] = _mm_targets(P, day, shops, minv, prices, tiles, opp, a_count, stock, animals, plants)
        mt = mem["mm_t"]
        if day <= P["animal_last_day"]:
            sheep_t = min(P["sheep_cap"], max(a_count["SHEEP"] + stock["SHEEP"], mt["SHEEP"]))
            cow_t = min(P["cow_cap"], max(a_count["COW"] + stock["COW"], mt["COW"]))
            gcap = P["goose_cap_hi"] if prices["EGG"] >= P["egg_hi"] else P["goose_cap"]
            goose_t = min(gcap, max(a_count["GOOSE"] + stock["GOOSE"], mt["GOOSE"]))
        straw_t = min(P["straw_cap"], max(P["straw_min"] if day <= P["straw_last_day"] else 0, mt["STRAWBERRY"]))
        carrot_t = min(P["carrot_cap"], mt.get("CARROT", 0)) if P["mm_carrot"] else 0
        tomato_t = min(P["tomato_cap"], mt["TOMATO"])

    # ------------------------------------------------------------------ values
    uv = {p: max(1, prices[p]) for p in PRODUCTS}
    fert_price = prices["FERTILIZER"]
    wheat_price = prices["WHEAT"]
    fert_wheat = fert_price <= P["wheat_fert_price"] and not last_day

    # ------------------------------------------------------------------ budget
    # expected proceeds of selling current shed stock (conservative: no drops of this turn)
    budget = money - P["cash_reserve"]
    orders_pre = []

    # hires (decided at hour 0/1)
    hire_n = 0
    if hour <= 1 and not (last_day and hour > 0):
        W = 0.0
        for (pos, t) in animals:
            W += 3.4
        for (pos, t) in plants:
            c = t["crop"]
            W += {"WHEAT": 1.8, "CARROT": 2.0, "TOMATO": 1.3, "STRAWBERRY": 0.9, "MELON": 0.9}[c]
        W += 2.0 * len(empties) + 1.0 * len(weeds) + 2.5 * len(empty_structs)
        mult = mem.get("mult", P["move_mult"])
        want_units = int(math.ceil(W * mult / 23.0))
        want_h = max(0, min(P["max_hands"], want_units - 1))
        if day <= 9:
            want_h = max(want_h, P["min_hands_early"] if day <= 5 else P["min_hands_mid"])
        elif day <= DAYS - 3 and len(plants) + len(animals) >= 40:
            want_h = max(want_h, P["min_hands_late"])
        if day >= DAYS - 2:
            want_h = min(want_h, max(4, want_units - 1))
        k = max(0, want_h - hires_today)
        # affordability: hires come after steep sells in the order list
        sell_cash = 0.0
        for p in PRODUCTS:
            if p == "WHEAT":
                continue
            n = shed.get(p, 0)
            if n > 0:
                sell_cash += sell_proceeds(p, minv[p], n)[0]
        avail = money + sell_cash
        cost = 0
        n = 0
        while n < k:
            c = FIB[min(hires_today + n, len(FIB) - 1)]
            if cost + c > avail:
                break
            cost += c
            n += 1
        hire_n = n
        budget -= cost
        if hour == 0:
            mem["hire_plan"] = hire_n

    # ------------------------------------------------------------------ land
    land_order = False
    n_extra = len(unlocked) - 1
    free_now = len(empties) + len(weeds)
    if n_extra < P["land_max"] and day >= P["land_days"][n_extra] and day <= P["land_last_day"] and not last_day:
        price = LAND_PRICES[n_extra]
        sell_cash = 0.0
        for p in PRODUCTS:
            n = shed.get(p, 0)
            if p == "WHEAT":
                n = max(0, n - len(animals) - 5)
            if n > 0:
                sell_cash += sell_proceeds(p, minv[p], n)[0]
        if budget + sell_cash - price >= P["land_reserve"] and (free_now <= P["land_free"] or budget + sell_cash >= 1.6 * price):
            land_order = True
            budget -= price

    # ------------------------------------------------------------------ plan
    plan = mem.setdefault("plan", {})
    free_set = set(empties) | set(weeds)
    crop_ok_day = {"MELON": P["melon_plan_last_day"], "STRAWBERRY": P["straw_last_day"], "TOMATO": P["tomato_last_day"],
                   "WHEAT": DAYS - 4, "CARROT": DAYS - 3, "PASTURE": P["animal_last_day"], "COOP": P["animal_last_day"]}
    for pos in list(plan):
        if pos not in free_set or (P["plan_valid"] and day > crop_ok_day.get(plan[pos], 99)):
            del plan[pos]

    def ring(pos):
        return DSHED[pos] <= 2

    # structures
    past_total = n_past + sum(1 for k in plan.values() if k == "PASTURE")
    coop_total = n_coop + sum(1 for k in plan.values() if k == "COOP")
    want_past = sheep_t + cow_t
    want_coop = goose_t
    # budget-limited structure planning (animal must be affordable)
    animal_budget = budget
    open_past = len([1 for (p, k) in empty_structs if k == "PASTURE"]) + sum(1 for k in plan.values() if k == "PASTURE")
    open_coop = len([1 for (p, k) in empty_structs if k == "COOP"]) + sum(1 for k in plan.values() if k == "COOP")
    animal_budget -= max(0, open_past - stock["COW"] - stock["SHEEP"]) * 400
    animal_budget -= max(0, open_coop - stock["GOOSE"]) * 300
    cands = sorted([p for p in free_set if plan.get(p) not in ("PASTURE", "COOP")], key=lambda p: (DSHED[p], p[1], p[0]))
    if day <= P["animal_last_day"] and not last_day:
        for pos in cands:
            if past_total < want_past and animal_budget >= 450 and DSHED[pos] <= 3:
                plan[pos] = "PASTURE"
                past_total += 1
                animal_budget -= 450
            elif coop_total < want_coop and animal_budget >= 300 and DSHED[pos] <= 3:
                plan[pos] = "COOP"
                coop_total += 1
                animal_budget -= 300

    melons_planted = mem.get("melons_planted", 0)
    planned = {c: sum(1 for k in plan.values() if k == c) for c in CROPS}

    LAB = {"WHEAT": 1.7, "CARROT": 1.8, "TOMATO": 1.4, "STRAWBERRY": 1.0, "MELON": 0.9}
    lab = [3.6 * (len(animals) + stock["COW"] + stock["SHEEP"] + stock["GOOSE"])
           + sum(LAB[t["crop"]] for (_, t) in plants)]

    def choose_crop(pos, cnt):
        """Crop for a free tile (cnt: running counts incl. planned)."""
        if last_day:
            return None
        c = _choose_crop(pos, cnt)
        if c in ("WHEAT", "CARROT") and lab[0] + LAB[c] > P["labor_cap"]:
            return None
        if c:
            lab[0] += LAB[c]
        return c

    def _choose_crop(pos, cnt):
        rg = ring(pos) and day <= P["animal_last_day"]
        if day <= P["melon_last_day"] and melons_planted + cnt["MELON"] < P["melon_target"] and not rg:
            return "MELON"
        if day <= DAYS - 4 and c_count["CARROT"] + cnt["CARROT"] < carrot_t:
            return "CARROT"
        prem = not rg
        if P["zoning"] and day > P["zone_free_day"]:
            prem = DSHED[pos] > P["zone_w_max"]
        if day <= P["straw_last_day"] and c_count["STRAWBERRY"] + cnt["STRAWBERRY"] < straw_t and prem and day >= 2:
            return "STRAWBERRY"
        if P["tomato_first_day"] <= day <= P["tomato_last_day"] and c_count["TOMATO"] + cnt["TOMATO"] < tomato_t and prem:
            return "TOMATO"
        if day <= DAYS - 4:
            return "WHEAT"
        if day <= DAYS - 3:
            return "CARROT"
        return None

    for pos in sorted([p for p in free_set if p not in plan], key=lambda p: (-DSHED[p], p[1], p[0])):
        c = choose_crop(pos, planned)
        if c:
            plan[pos] = c
            planned[c] += 1

    # ------------------------------------------------------------------ tile work
    # op tuple: (action_list, need, value)   need in None|"WHEAT"|"FERT"|"FED"|"SEED:x"|"ANIMAL:kind"|"PLANTED"
    tasks = {}
    feed_need_today = 0
    fert_need_today = 0
    fert_need_next = 0
    crit_left = 0

    def replant_ops(pos, cnt_override=None):
        c = plan.get(pos)
        if c is None:
            c = choose_crop(pos, planned)
            if c is None:
                return []
            plan[pos] = c
            planned[c] += 1
        if c in ("PASTURE", "COOP"):
            return [(["BUILD_" + c], None, 80.0), (["PLACE", c], "ANIMAL:" + c, 300.0)]
        v = {"MELON": 200.0, "STRAWBERRY": 150.0, "TOMATO": 100.0, "WHEAT": 45.0, "CARROT": 35.0}[c]
        return [(["PLANT", c], "SEED:" + c, v), (["WATER"], "PLANTED", 40.0)]

    urg = 1.0 + max(0, hour - P["urg_hour"]) / P["urg_div"]
    conv = [budget]
    urg2 = urg if P["urg_prod"] else 1.0

    def surv_val(crop, age, yu):
        """Value of keeping a plant alive tonight (its remaining expected revenue)."""
        u = uv[crop]
        if not P["surv_mode"]:
            return (150.0 if CROPS[crop]["ongoing"] else 120.0) + CROPS[crop]["seed"]
        if crop == "STRAWBERRY":
            rem = sum(1 for a_ in (9, 11, 13, 15) if a_ >= age and DAYS - 2 >= day + (a_ - age))
            v = rem * 2 * u + yu * u
        elif crop == "TOMATO":
            rem = sum(1 for a_ in (7, 8, 9, 10) if a_ >= age and DAYS - 2 >= day + (a_ - age))
            v = rem * 2 * u + yu * u
        elif crop == "MELON":
            v = 6 * u
        elif crop == "WHEAT":
            v = 5 * u
        else:
            v = 4 * u
        return min(P["surv_cap"], max(120.0, 0.8 * v)) * urg

    for (pos, t) in plants:
        crop = t["crop"]
        cd = CROPS[crop]
        age = day - t["planted_day"]
        yu = int(t["yield_units"])
        watered = t["watered_today"]
        cu = int(t["consecutive_unwatered"])
        fert_on = t["fertilized_until_day"] >= day
        ops = []
        u = uv[crop]
        if not cd["ongoing"]:
            ws = (cd["max_yield_day"] + 1) // 2
            mx = cd["max_yield_day"]
            in_win = ws <= age <= mx
            # harvest decision
            if last_day:
                harvest_now = age >= cd["first_yield_day"]
            elif crop == "WHEAT":
                harvest_now = age >= 4 or (age == 3 and fert_on)
                if (not harvest_now and age >= 2 and day <= P["convert_last_day"] and conv[0] >= 100
                        and _choose_crop(pos, planned) == "STRAWBERRY"):
                    harvest_now = True
                    conv[0] -= 100
            elif crop == "CARROT":
                harvest_now = age >= 3
            else:  # MELON
                harvest_now = age >= 10
            will_yield = yu
            if not watered and in_win and yu < cd["max_yield"] and (harvest_now or True):
                bonus = 2 if fert_on else 1
                gain = min(cd["max_yield"] - yu, bonus)
                if not (harvest_now and age < cd["first_yield_day"]):
                    ops.append((["WATER"], None, gain * u + ((surv_val(crop, age, yu) if P["surv_mode"] else 60.0) if cu >= 1 else 0.0)))
                    will_yield = yu + gain
            elif not watered and not harvest_now and (age == 0 or cu >= 1):
                ops.append((["WATER"], None, surv_val(crop, age, yu)))
                crit_left += 1
            # fertilize wheat/carrot at window start
            f_ok = fert_wheat or (crop == "CARROT" and uv["CARROT"] >= 2.0 * fert_price and not last_day)
            if (crop in ("WHEAT", "CARROT") and f_ok and age == ws and t["fertilized_until_day"] < day
                    and not harvest_now):
                ops.insert(0, (["FERTILIZE"], "FERT", 2.0 * u))
                fert_need_today += 1
            if crop in ("WHEAT", "CARROT") and f_ok and age == ws - 1:
                fert_need_next += 1
            if harvest_now and will_yield > 0 and age >= cd["first_yield_day"]:
                decaying = age > mx
                hv = will_yield * u * (1.0 if decaying else 0.35) + (100.0 if crop == "MELON" else 10.0)
                ops.append((["HARVEST"], None, hv))
                if not last_day:
                    ops.extend(replant_ops(pos))
        else:
            if crop == "STRAWBERRY":
                prod_days = (9, 11, 13, 15)
                fert_days = (9, 13)
                last_prod = 15
            else:
                prod_days = (7, 8, 9, 10)
                fert_days = (7, 10)
                last_prod = 10
            spent = age > last_prod
            fert_now = False
            if age in fert_days and t["fertilized_until_day"] < day and not last_day:
                gain_units = 2 if crop == "STRAWBERRY" else (3 if age == 7 else 1)
                if crop == "STRAWBERRY" or age == 7 or fert_price < 30:
                    ops.append((["FERTILIZE"], "FERT", gain_units * u * urg2))
                    fert_need_today += 1
                    fert_now = True
            if age + 1 in fert_days and not last_day:
                fert_need_next += 1
            if not watered and not spent and not last_day:
                if age == 0 or cu >= 1:
                    ops.append((["WATER"], None, surv_val(crop, age, yu)))
                    crit_left += 1
                elif age in prod_days and (fert_on or fert_now):
                    ops.append((["WATER"], "FERTOK" if fert_now else None, 1.0 * u * urg2))
            # harvest
            if yu > 0:
                prod_tonight = age in prod_days
                amt = 2 if (fert_on or fert_now) else 1
                overflow = prod_tonight and yu + amt > cd["max_yield"]
                if last_day or spent or yu >= cd["max_yield"] or overflow or (day >= DAYS - 2):
                    ops.append((["HARVEST"], None, yu * u * (1.0 if (spent and P["spent_full"]) else 0.35) + (yu + amt - 4) * u * (1 if overflow else 0) + 10.0))
            if spent and not last_day and (yu == 0 or ops and ops[-1][0][0] == "HARVEST"):
                if day <= DAYS - 3:
                    ops.append((["DIG"], None, 50.0 if P["spent_full"] else 30.0))
                    ops.extend(replant_ops(pos))
        if ops:
            tasks[pos] = ops

    # animals
    for (pos, t) in animals:
        a = t["animal"]
        ad = ANIMALS[a]
        prod = ad["product"]
        u = uv[prod]
        yu = int(t["yield_units"])
        pend = int(t.get("pending_care_bonus", 0) or 0)
        np_ = _next_prod(t, day)
        prod_tonight = np_ == day and day <= DAYS - 2
        after = _next_prod(t, day + 1)
        care_useful = after <= DAYS - 2
        crashed = u < P["crash_frac"] * base_p[prod]
        ops = []
        feed = False
        if not last_day and not t["fed_today"]:
            if t["consecutive_unfed"] >= 1 and (care_useful or prod_tonight or yu > 0 or day < DAYS - 2):
                feed = True
            elif prod_tonight and (pend > 0 or yu < ad["max_held"]):
                feed = True
            elif care_useful and not crashed:
                feed = True
        if feed:
            v = 25.0 + (u if (care_useful and not crashed) else 0.0)
            if t["consecutive_unfed"] >= 1:
                v += 400.0
                crit_left += 1
            if prod_tonight:
                v += pend * u
            ops.append((["FEED"], "WHEAT", v))
            feed_need_today += 1
        if not last_day and not t["cared_today"] and care_useful and not crashed and (t["fed_today"] or feed):
            ops.append((["CARE"], "FED", float(u)))
        if t["fertilizer_available"]:
            ops.append((["COLLECT_FERTILIZER"], None, float(max(15, min(100, fert_price)))))
        if yu > 0:
            amt = 1 + pend if prod_tonight else 0
            overflow = prod_tonight and yu + amt > ad["max_held"]
            hmin = 2 if a == "GOOSE" else 3
            do_h = False
            if last_day or day >= DAYS - 2:
                do_h = True
            elif overflow:
                do_h = True
            elif crashed:
                do_h = yu >= ad["max_held"] - 1
            elif day <= 10 or yu >= hmin:
                do_h = True
            if do_h:
                hv = yu * u * 0.25 + (yu + amt - ad["max_held"]) * u * (1 if overflow else 0) + 10.0
                ops.append((["HARVEST"], None, hv))
        if ops:
            # cheap ops first so the unit stays for the valuable FEED/CARE at the end of the burst
            pass  # ops.sort(key=lambda o: ANIMAL_OP_ORDER[o[0][0]])
            tasks[pos] = ops

    # empty structures -> place animal
    for (pos, k) in empty_structs:
        if not last_day:
            tasks[pos] = [(["PLACE", k], "ANIMAL:" + k, 300.0)]

    # planned free tiles
    for pos in free_set:
        if pos in tasks:
            continue
        c = plan.get(pos)
        if c is None:
            if pos in weeds and days_left >= 4:
                tasks[pos] = [(["DIG"], None, 15.0)]
            continue
        ops = []
        if pos in weeds:
            ops.append((["DIG"], None, 20.0))
        ops.extend(replant_ops(pos))
        tasks[pos] = ops

    # ------------------------------------------------------------------ animal purchases
    buy_animals = {a: 0 for a in ANIMALS}
    open_p = len([1 for (p, k) in empty_structs if k == "PASTURE"]) + sum(1 for k in plan.values() if k == "PASTURE")
    open_c = len([1 for (p, k) in empty_structs if k == "COOP"]) + sum(1 for k in plan.values() if k == "COOP")
    need_p = open_p - stock["COW"] - stock["SHEEP"]
    need_c = open_c - stock["GOOSE"]
    shed_room = 100 - sum(shed.values())
    sheep_tot = a_count["SHEEP"] + stock["SHEEP"]
    cow_tot = a_count["COW"] + stock["COW"]
    if not last_day and day <= P["animal_last_day"] + 1:
        while need_p > 0 and shed_room > 0:
            ds = sheep_t - sheep_tot
            dc = cow_t - cow_tot
            sp = "SHEEP" if (ds > dc or (ds == dc and n_yarn > 0)) else "COW"
            if ds <= 0 and dc <= 0:
                sp = "SHEEP" if prices["WOOL"] / 1.33 > prices["MILK"] / 1.5 * 1.0 else "COW"
            cst = ANIMALS[sp]["cost"]
            if budget < cst:
                break
            buy_animals[sp] += 1
            budget -= cst
            need_p -= 1
            shed_room -= 1
            if sp == "SHEEP":
                sheep_tot += 1
            else:
                cow_tot += 1
        while need_c > 0 and shed_room > 0 and budget >= 300:
            buy_animals["GOOSE"] += 1
            budget -= 300
            need_c -= 1
            shed_room -= 1

    # ------------------------------------------------------------------ assignment
    unit_items = [dict(i) for i in invs]
    seed_stock = dict(seeds)
    seed_buy = {c: 0 for c in CROPS}
    actions = [None] * n_units
    wheat_carried = sum(it.get("WHEAT", 0) for it in unit_items)
    fert_carried = sum(it.get("FERTILIZER", 0) for it in unit_items)
    S = {"wheat_unc": feed_need_today - wheat_carried, "fert_unc": fert_need_today - fert_carried}
    shed_left = dict(shed)
    # animals to place: open structures minus animals carried
    place_need = {"COOP": len([1 for (p, k) in empty_structs if k == "COOP"]) + sum(1 for k in plan.values() if k == "COOP"),
                  "PASTURE": len([1 for (p, k) in empty_structs if k == "PASTURE"]) + sum(1 for k in plan.values() if k == "PASTURE")}
    for it in unit_items:
        place_need["COOP"] -= it.get("GOOSE", 0)
        place_need["PASTURE"] -= it.get("COW", 0) + it.get("SHEEP", 0)

    def cargo(i):
        it = unit_items[i]
        out = {}
        for k, v in it.items():
            if v <= 0 or k not in PRODUCTS:
                continue
            if not last_day:
                if k == "WHEAT" and feed_need_today > 0:
                    continue
                if k == "FERTILIZER" and fert_need_today > 0 and not (P["fert_drop_feeders"] and it.get("WHEAT", 0) > 0):
                    continue
            out[k] = v
        return out

    drop_f = P["drop_early"] if day <= 9 else P["drop_late"]

    def shed_choice(i):
        """(value, action, kind) of the best shed interaction for unit i."""
        it = unit_items[i]
        best = (0.0, None, None)
        c = cargo(i)
        if last_day:
            if c:
                cv = sum(v * uv[k] for k, v in c.items())
                return (cv + 50.0, ["DROP"], "drop")
            return best
        if place_need["PASTURE"] > 0 and it.get("COW", 0) + it.get("SHEEP", 0) == 0:
            sp = "SHEEP" if shed_left.get("SHEEP", 0) > 0 else ("COW" if shed_left.get("COW", 0) > 0 else None)
            if sp:
                best = (300.0, ["PICKUP", sp, 1], "animal")
        if place_need["COOP"] > 0 and it.get("GOOSE", 0) == 0 and shed_left.get("GOOSE", 0) > 0 and best[0] < 300:
            best = (300.0, ["PICKUP", "GOOSE", 1], "animal")
        if S["wheat_unc"] > 0 and it.get("WHEAT", 0) == 0 and shed_left.get("WHEAT", 0) > 0:
            k = min(shed_left["WHEAT"], S["wheat_unc"], P["pick_cap"])
            v = 45.0 * k
            if v > best[0]:
                best = (v, ["PICKUP", "WHEAT", k], "wheat")
        if S["fert_unc"] > 0 and it.get("FERTILIZER", 0) == 0 and shed_left.get("FERTILIZER", 0) > 0:
            k = min(shed_left["FERTILIZER"], S["fert_unc"], P["pick_cap"])
            v = 60.0 * k
            if v > best[0]:
                best = (v, ["PICKUP", "FERTILIZER", k], "fert")
        if c:
            cv = sum(v * uv[k] for k, v in c.items())
            v = cv * drop_f + c.get("MELON", 0) * uv["MELON"] * P["melon_drop"]
            if v > best[0]:
                keep = any(k not in c and v2 > 0 for k, v2 in it.items())
                if keep:
                    kb = max(c, key=lambda k: c[k] * uv[k])
                    best = (v, ["PLACE", kb, c[kb]], "drop1")
                else:
                    best = (v, ["DROP"], "drop")
        return best

    def apply_shed(i, choice, here):
        v, a, kind = choice
        it = unit_items[i]
        if kind == "animal":
            sp = a[1]
            shed_left[sp] -= 1
            if sp == "GOOSE":
                place_need["COOP"] -= 1
            else:
                place_need["PASTURE"] -= 1
            if here:
                it[sp] = it.get(sp, 0) + 1
        elif kind == "wheat":
            shed_left["WHEAT"] -= a[2]
            S["wheat_unc"] -= a[2]
            if here:
                it["WHEAT"] = it.get("WHEAT", 0) + a[2]
        elif kind == "fert":
            shed_left["FERTILIZER"] -= a[2]
            S["fert_unc"] -= a[2]
            if here:
                it["FERTILIZER"] = it.get("FERTILIZER", 0) + a[2]
        elif kind == "drop" and here:
            for k in list(it):
                shed_left[k] = shed_left.get(k, 0) + it[k]
                it[k] = 0
        elif kind == "drop1" and here:
            k = a[1]
            shed_left[k] = shed_left.get(k, 0) + it[k]
            it[k] = 0

    # pre-pass: units standing on shed tiles do their best shed interaction first
    for i, pos in enumerate(units):
        if pos not in SHED_SET:
            continue
        ch = shed_choice(i)
        if ch[1] is not None and ch[0] >= P["shed_min"]:
            actions[i] = list(ch[1])
            apply_shed(i, ch, True)

    lam = P["lam"]
    hours_left = TPD - hour  # actions left today incl. this one
    gate_feed = P["gate_feed"] and (shed_left.get("WHEAT", 0) > 0 or sum(it.get("WHEAT", 0) for it in unit_items) > 0)
    task_items = list(tasks.items())

    def eval_ops(ops, it, pos, d):
        """Value of the ops this unit can execute; first executable op."""
        w = it.get("WHEAT", 0)
        f = it.get("FERTILIZER", 0)
        if gate_feed and w <= 0 and ops and ops[0][1] == "WHEAT":
            return 0.0, None, 0  # leave the whole animal burst to a wheat carrier
        tile = tiles[pos[1]][pos[0]]
        fed = isinstance(tile, dict) and tile.get("fed_today", False)
        planted = False
        fert_done = False
        total = 0.0
        first = None
        n_ex = 0
        for (op, need, v) in ops:
            okk = True
            if need == "WHEAT":
                okk = w > 0
                if okk:
                    w -= 1
                    fed = True
            elif need == "FED":
                okk = fed
            elif need == "FERT":
                okk = f > 0
                if okk:
                    f -= 1
                    fert_done = True
            elif need == "FERTOK":
                okk = fert_done
            elif need == "PLANTED":
                okk = planted
            elif need is not None and need.startswith("SEED:"):
                c = need[5:]
                okk = (seed_stock.get(c, 0) > 0 or budget >= CROPS[c]["seed"]) and (d + n_ex + 2 <= hours_left or not P["plant_deadline"])
                if okk:
                    planted = True
            elif need is not None and need.startswith("ANIMAL:"):
                kind = need[7:]
                if kind == "COOP":
                    okk = it.get("GOOSE", 0) > 0
                else:
                    okk = it.get("COW", 0) + it.get("SHEEP", 0) > 0
            if okk:
                total += v
                n_ex += 1
                if first is None:
                    first = (op, need)
        return total, first, n_ex

    pairs = []
    prev_t = mem.get("targets", {}) if mem.get("targets_step") == step - 1 else {}
    new_t = {}
    for i, pos in enumerate(units):
        if actions[i] is not None:
            continue
        it = unit_items[i]
        for (tpos, ops) in task_items:
            d = dist(pos, tpos)
            if d >= hours_left:
                continue
            if last_day and step + d + 1 + DSHED[tpos] + 1 > LAST_STEP:
                continue
            val, first, n_ex = eval_ops(ops, it, tpos, d)
            if first is None or val <= 0:
                continue
            sc = val / (d + n_ex + P["ratio_k"])
            if d == 0:
                sc *= P["stay_mult"]
            elif prev_t.get(i) == tpos:
                sc *= P["stick_mult"]
            pairs.append((sc, d, i, tpos, first))
        if pos not in SHED_SET:
            ch = shed_choice(i)
            d = DSHED[pos]
            if ch[1] is not None and d < hours_left:
                pairs.append((ch[0] / (d + 1 + P["ratio_k"]), d, i, ("SHED", i), ch))
    pairs.sort(key=lambda z: (-z[0], z[1], z[2]))
    if P.get("debug"):
        mem["_dbg"] = {"tasks": {k: v for k, v in tasks.items()}, "pairs": pairs[:60], "feed_need": feed_need_today,
                       "S": dict(S), "budget": budget}
    taken_u, taken_t = set(), set()
    for sc, d, i, tpos, first in pairs:
        if i in taken_u or tpos in taken_t:
            continue
        it = unit_items[i]
        if tpos[0] == "SHED":
            ch = shed_choice(i)  # re-validate against updated counters
            if ch[1] is None or ch[0] / (d + 1 + P["ratio_k"]) < sc * 0.7:
                continue
            taken_u.add(i)
            apply_shed(i, ch, False)
            actions[i] = [step_toward(units[i], NEAR_SHED[units[i]])]
            continue
        op, need = first
        if need is not None and need.startswith("SEED:"):
            c = need[5:]
            if seed_stock.get(c, 0) <= 0:
                if budget < CROPS[c]["seed"]:
                    continue
                budget -= CROPS[c]["seed"]
                if d <= 1:
                    seed_buy[c] += 1
                    if d == 0:
                        # seed arrives next turn; wait here
                        taken_u.add(i)
                        taken_t.add(tpos)
                        actions[i] = ["PASS"]
                        continue
                    seed_stock[c] = seed_stock.get(c, 0) + 1
        else:
            # a later op on this tile may need a seed: buy it when close
            for (op2, need2, v2) in tasks[tpos]:
                if need2 is not None and need2.startswith("SEED:") and d <= 1:
                    c = need2[5:]
                    if seed_stock.get(c, 0) <= 0 and budget >= CROPS[c]["seed"]:
                        seed_buy[c] += 1
                        seed_stock[c] = seed_stock.get(c, 0) + 1
                        budget -= CROPS[c]["seed"]
                    break
        taken_u.add(i)
        taken_t.add(tpos)
        new_t[i] = tpos
        if d == 0:
            a = list(op)
            if a[0] == "PLACE" and a[1] in ("COOP", "PASTURE"):
                if a[1] == "COOP":
                    a[1] = "GOOSE"
                else:
                    a[1] = "SHEEP" if it.get("SHEEP", 0) > 0 else "COW"
                it[a[1]] -= 1
            elif a[0] == "FEED":
                it["WHEAT"] = it.get("WHEAT", 0) - 1
            elif a[0] == "FERTILIZE":
                it["FERTILIZER"] = it.get("FERTILIZER", 0) - 1
            elif a[0] == "PLANT":
                seed_stock[a[1]] = seed_stock.get(a[1], 0) - 1
                if a[1] == "MELON":
                    mem["melons_planted"] = mem.get("melons_planted", 0) + 1
            actions[i] = a
        else:
            if need is not None and need.startswith("SEED:") and seed_stock.get(need[5:], 0) > 0 and d <= 1:
                seed_stock[need[5:]] -= 1
            actions[i] = [step_toward(units[i], tpos)]

    for i in range(n_units):
        if actions[i] is None:
            actions[i] = ["PASS"]
    mem["targets"] = new_t
    mem["targets_step"] = step
    # small seed buffer for pending plantings (avoids a wasted turn waiting for a seed)
    if P["seed_buffer"] and not last_day and hour < TPD - 2:
        pend = collections.Counter(c for c in plan.values() if c in CROPS)
        for (tpos, ops) in tasks.items():
            for (op2, need2, v2) in ops:
                if need2 is not None and need2.startswith("SEED:") and tiles[tpos[1]][tpos[0]] is not None:
                    pend[need2[5:]] += 1
        for c, n in pend.items():
            want = min(n, P["seed_buffer"] if CROPS[c]["seed"] <= 20 else 1)
            have = seed_stock.get(c, 0)
            while have < want and budget >= CROPS[c]["seed"] + 50:
                seed_buy[c] += 1
                have += 1
                budget -= CROPS[c]["seed"]

    # stats for hire feedback
    if hour >= 2:
        mem["uturns"] = mem.get("uturns", 0) + n_units
        mem["idle"] = mem.get("idle", 0) + sum(1 for a in actions if a and a[0] == "PASS")
    if hour == TPD - 1:
        idle = mem.get("idle", 0) / max(1, mem.get("uturns", 1))
        mult = mem.get("mult", P["move_mult"])
        if crit_left > 2:
            mult = min(2.6, mult + 0.15)
        elif idle > 0.22:
            mult = max(1.2, mult - 0.1)
        elif idle < 0.06:
            mult = min(2.6, mult + 0.05)
        mem["mult"] = mult
        mem["idle"] = 0
        mem["uturns"] = 0

    # ------------------------------------------------------------------ market
    shed_after = dict(shed)
    for i, a in enumerate(actions):
        if not a:
            continue
        if a[0] == "DROP" and units[i] in SHED_SET:
            for k, v in invs[i].items():
                shed_after[k] = shed_after.get(k, 0) + v
        elif a[0] == "PLACE" and units[i] in SHED_SET and a[1] in PRODUCTS:
            shed_after[a[1]] = shed_after.get(a[1], 0) + min(int(a[2]) if len(a) > 2 else 1, invs[i].get(a[1], 0))
        elif a[0] == "PICKUP":
            shed_after[a[1]] = shed_after.get(a[1], 0) - int(a[2])

    n_anim = len(animals) + sum(buy_animals.values()) + stock["COW"] + stock["SHEEP"] + stock["GOOSE"]
    wheat_carried = sum(it.get("WHEAT", 0) for it in unit_items)
    if last_day:
        wheat_res = 0
        fert_res = 0
    else:
        wheat_res = max(0, feed_need_today - wheat_carried) + (n_anim + 3 if (hour >= 12 or P["wheat_keep"]) else 0)
        fert_res = max(0, fert_need_today - sum(it.get("FERTILIZER", 0) for it in unit_items)) + fert_need_next
        if fert_price < P["fert_keep_price"]:
            fert_res = max(fert_res, 30)
    tick = mem.get("tick_wheat")
    tick_sell = tick[1] if (tick and tick[0] == step - 1) else 0
    mem["tick_wheat"] = None
    sells = []
    for item in PRODUCTS:
        have = shed_after.get(item, 0)
        if item == "WHEAT":
            have = min(shed_after.get(item, 0), max(0, have - tick_sell - wheat_res) + tick_sell)
        elif item == "FERTILIZER":
            have -= fert_res
        if have <= 0:
            continue
        sells.append([item, have])
    # overflow guard: end-of-day drop destroys items beyond shed capacity
    if hour == TPD - 1 and not last_day:
        carried = sum(sum(it.values()) for it in unit_items)
        projected = sum(v for v in shed_after.values() if v > 0) - sum(n for _, n in sells) + carried
        excess = projected - 100 + 2
        if excess > 0:
            for item in ("WHEAT", "FERTILIZER", "EGG", "CARROT"):
                if excess <= 0:
                    break
                have = shed_after.get(item, 0) - sum(n for it2, n in sells if it2 == item)
                k = min(have, excess)
                if k > 0:
                    found = False
                    for s in sells:
                        if s[0] == item:
                            s[1] += k
                            found = True
                    if not found:
                        sells.append([item, k])
                    excess -= k
    sells.sort(key=lambda s: SELL_PRIO[s[0]])
    sell_orders = [["SELL", s[0], int(s[1])] for s in sells if s[1] > 0]
    steep = [o for o in sell_orders if o[1] in STEEP]
    other = [o for o in sell_orders if o[1] not in STEEP]

    orders = list(steep)
    room = 10 - len(orders)
    hires = []
    if hour == 0:
        k = min(hire_n, max(0, room - 1))
        hires = [["HIRE"]] * k
        mem["hire_left"] = hire_n - k
    elif hour == 1:
        k = min(mem.get("hire_left", 0), room)
        hires = [["HIRE"]] * max(0, k)
        mem["hire_left"] = 0
    orders += hires
    orders += other
    if land_order:
        orders.append(["BUY_LAND"])
    for a_, n in buy_animals.items():
        if n > 0:
            orders.append(["BUY_ANIMAL", a_, n])
    for c, n in seed_buy.items():
        if n > 0:
            orders.append(["BUY_SEED", c, n])
    # feed wheat top-up
    if not last_day:
        wheat_have = shed_after.get("WHEAT", 0) + wheat_carried
        need_w = feed_need_today
        if hour >= 16:
            need_w += n_anim
        short = need_w - wheat_have
        if short > 0 and wheat_price <= 70:
            orders.append(["BUY_PRODUCT", "WHEAT", int(short)])
    orders = orders[:10]
    # wheat tick trade: buy last before a shop tick (orders at hours 0,4,..,20), sell back next step
    if (P["tick_n"] > 0 and step % 4 == 0 and day >= P["tick_day"] and step <= LAST_STEP - 2 and len(orders) < 10):
        shed_tot = sum(v for v in shed_after.values() if v > 0) - sum(int(o[2]) for o in orders if o[0] == "SELL")
        near_cargo = 0
        for i, pos in enumerate(units):
            if DSHED[pos] <= 1:
                near_cargo += sum(unit_items[i].values())
        room = 100 - shed_tot - near_cargo - 12 - sum(int(o[2]) for o in orders if o[0] in ("BUY_PRODUCT", "BUY_ANIMAL"))
        cash = money + sum(sell_proceeds(o[1], minv[o[1]], int(o[2]))[0] for o in orders if o[0] == "SELL") - 1500
        for o in orders:
            if o[0] == "HIRE":
                cash -= 150
            elif o[0] == "BUY_LAND":
                cash -= 4000
            elif o[0] == "BUY_ANIMAL":
                cash -= ANIMALS[o[1]]["cost"] * int(o[2])
            elif o[0] == "BUY_SEED":
                cash -= CROPS[o[1]]["seed"] * int(o[2])
            elif o[0] == "BUY_PRODUCT":
                cash -= 60 * int(o[2])
        n = int(min(P["tick_n"], room, cash // max(1, wheat_price + 3)))
        if n >= 5:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            mem["tick_wheat"] = (step, n)
    return {"farmer": actions[0], "hands": actions[1:], "market": orders}


_AGENT = make_agent()


def agent(obs, config=None):
    return _AGENT(obs, config)
