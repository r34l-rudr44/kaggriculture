"""Kaggriculture agent v5_script: scripted opening + adaptive midgame.

Structure of one turn:
  1. survey own farm, opponent farm, market, shops
  2. strategic plan: herd targets, hires, land, tile roles (structures / crops)
  3. purchases under a priority budget (feed wheat > hires > land > animals > seeds)
  4. tile jobs (bursts of FEED/CARE/COLLECT/HARVEST, crop calendars) and shed jobs
  5. greedy unit assignment (value - distance), one unit per tile
  6. market orders: steep sells first, hires, land, animals, wheat, seeds
Standard library only. State is kept per player id.
"""
import math

N = 10
HALF = 5
TPD = 24
DAYS = 30
LAST_STEP = 718

SHED_TILES = ((4, 4), (5, 4), (4, 5), (5, 5))
SHED_SET = set(SHED_TILES)

CROPS = {
    "WHEAT":      {"seed": 10, "fyd": 2, "mxd": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20, "fyd": 2, "mxd": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50, "fyd": 8, "mxd": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "fyd": 10, "mxd": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80, "fyd": 10, "mxd": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}
ANIMALS = {
    "GOOSE": {"cost": 300, "kind": "COOP", "fyd": 4, "interval": 1, "cap": 4, "product": "EGG"},
    "COW":   {"cost": 400, "kind": "PASTURE", "fyd": 8, "interval": 2, "cap": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "kind": "PASTURE", "fyd": 6, "interval": 3, "cap": 6, "product": "WOOL"},
}
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
MP = {
    "WHEAT":      (25, 400, "sqrt", 0.80, "log", 0.20),
    "CARROT":     (35, 450, "hinge", 1.00, "sqrt", 0.70),
    "TOMATO":     (60, 200, "hinge", 0.40, "sqrt", 0.60),
    "STRAWBERRY": (120, 100, "sqrt", 0.70, "linear", 1.60),
    "MELON":      (250, 300, "log", 0.20, "sq", 3.60),
    "EGG":        (50, 332, "hinge", 0.40, "log", 0.20),
    "MILK":       (160, 122, "sqrt", 0.60, "linear", 1.60),
    "WOOL":       (200, 105, "log", 0.20, "sq", 3.20),
    "FERTILIZER": (100, 200, "linear", 0.40, "linear", 0.40),
}
BASE = {k: v[0] for k, v in MP.items()}
I0 = 10000
SHOPS = {
    "BAKERY": ["EGG", "WHEAT"], "PIZZA_SHOP": ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT": ["EGG", "WHEAT", "STRAWBERRY"], "YARN_STORE": ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"], "PET_CAFE": ["CARROT"],
    "SMOOTHIE_SHOP": ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
LAND_PRICES = [1000, 2000, 4000]
# sell order: steepest price curves first (order book runs slot by slot)
SELL_ORDER = ["WOOL", "MILK", "STRAWBERRY", "MELON", "TOMATO", "CARROT", "EGG", "WHEAT", "FERTILIZER"]


def _shape(func, x, T):
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


_AMP = {}
for _k, (_b, _T, _bf, _bt, _af, _at) in MP.items():
    _AMP[_k] = (_bt * _b / _shape(_bf, _T, _T), _at * _b / _shape(_af, _T, _T))


def market_price(item, inv):
    b, T, bf, bt, af, at = MP[item]
    ab, aa = _AMP[item]
    if inv < I0:
        p = b + ab * _shape(bf, I0 - inv, T)
    else:
        p = b - aa * _shape(af, inv - I0, T)
    return max(1, int(round(p)))


def sell_revenue(item, inv, n):
    tot = 0
    for _ in range(n):
        p = market_price(item, inv)
        tot += p
        if p > 1:
            inv += 1
    return tot


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


SD = {}
NEAR_SHED = {}
for _x in range(N):
    for _y in range(N):
        _best = min(SHED_TILES, key=lambda s: (dist((_x, _y), s), SHED_TILES.index(s)))
        SD[(_x, _y)] = dist((_x, _y), _best)
        NEAR_SHED[(_x, _y)] = _best


def quad(p):
    return ("N" if p[1] < HALF else "S") + ("W" if p[0] < HALF else "E")


def _cross(p):
    return p[0] in (4, 5) or p[1] in (4, 5)


ZONE = set(p for p in SD if SD[p] <= 2)
STRUCT_ORDER = sorted(SD, key=lambda p: (SD[p], 0 if _cross(p) else 1, p[1], p[0]))
CROP_ORDER = sorted(SD, key=lambda p: (SD[p], p[1], p[0]))
CROP_RANK = {p: i for i, p in enumerate(CROP_ORDER)}

MELON_D0 = [(3, 3), (4, 1), (3, 2), (2, 3), (1, 4), (2, 2)]
MELON_D1 = [(4, 0), (3, 1), (1, 3), (0, 4)]
MELON_TILES = set(MELON_D0 + MELON_D1)
D0_PASTURES = [(4, 4), (3, 4), (4, 3), (2, 4), (4, 2)]

# expected extra demand (units/day) added by one future shop unlock, per product
UNLOCK_E = {}
for _p in PRODUCTS:
    _s = 0.0
    for _name, _prods in SHOPS.items():
        if _p in _prods:
            _s += 12.0 if len(_prods) == 1 else 6.0
    UNLOCK_E[_p] = _s / len(SHOPS)
# units above I0 at which the price is roughly 55-60% of base (market "slack")
X_MAX = {"STRAWBERRY": 28, "MILK": 34, "WOOL": 39, "TOMATO": 60, "CARROT": 100, "MELON": 100,
         "EGG": 400, "WHEAT": 2000, "FERTILIZER": 0}


def daily_demand(p, shops):
    if p == "FERTILIZER":
        return 0.0
    r = 1.0
    for s in shops:
        prods = SHOPS.get(s, ())
        if p in prods:
            r += 12.0 if len(prods) == 1 else 6.0
    return r


def future_demand(p, day, shops, w_future):
    """expected town consumption of p from today to the end of the game."""
    known = daily_demand(p, shops)
    n_left = max(0, 8 - len(shops))
    unlocks = [d for d in range(3, 25, 3) if d > day][:n_left]
    tot = 0.0
    e = UNLOCK_E[p] * w_future
    for t in range(day, DAYS):
        k = 0
        for u in unlocks:
            if u <= t:
                k += 1
        tot += known + e * k
    return tot


def project_supply(tiles, day):
    """remaining sellable production of a farm (assumes care + fertilizer like top agents)."""
    sup = {p: 0.0 for p in PRODUCTS}
    last = DAYS - 2  # production at end of day 28 is the last one that can be sold
    for row in tiles:
        for t in row:
            if not isinstance(t, dict):
                continue
            if t.get("kind") == "PLANT":
                crop = t["crop"]
                pd = t["planted_day"]
                yu = int(t.get("yield_units", 0))
                if crop == "STRAWBERRY":
                    n = sum(1 for a in (9, 11, 13, 15) if day <= pd + a <= last)
                    sup[crop] += 2 * n + yu
                elif crop == "TOMATO":
                    n = sum(1 for a in (7, 8, 9, 10) if day <= pd + a <= last)
                    sup[crop] += 2 * n + yu
                elif crop == "MELON":
                    if pd + 10 <= DAYS - 1:
                        sup[crop] += 6
                elif crop == "WHEAT":
                    sup[crop] += 5
                elif crop == "CARROT":
                    sup[crop] += 4
            elif t.get("animal"):
                a = t["animal"]
                ad = ANIMALS[a]
                first = t["placed_day"] + ad["fyd"] - 1
                iv = ad["interval"]
                steady = {"SHEEP": 4, "COW": 3, "GOOSE": 2}[a]
                p = first
                if day > first:
                    p = first + ((day - first + iv - 1) // iv) * iv
                tot = int(t.get("yield_units", 0))
                while p <= last:
                    tot += ad["cap"] if p == first else steady
                    p += iv
                sup[ad["product"]] += tot
    return sup


def new_animal_units(a, day):
    """units a newly bought animal (placed today) yields by the end."""
    ad = ANIMALS[a]
    first = day + ad["fyd"] - 1
    steady = {"SHEEP": 4, "COW": 3, "GOOSE": 2}[a]
    tot = 0
    p = first
    while p <= DAYS - 2:
        tot += ad["cap"] if p == first else steady
        p += ad["interval"]
    return tot


MILK_SHOPS = ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP")
EGG_SHOPS = ("BAKERY", "BRUNCH_SPOT")
BERRY_SHOPS = ("BRUNCH_SPOT", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP", "FARMERS_MARKET")
TOMATO_SHOPS = ("PIZZA_SHOP", "FARMERS_MARKET")
CARROT_SHOPS = ("PET_CAFE", "FARMERS_MARKET")

DEFAULT_PARAMS = {
    "w_dist": 20.0,
    "burst": 6.0,
    "stick": 8.0,
    "melon_n": 10,
    "straw_first": 2,
    "straw_last": 13,
    "straw_base": 28,
    "straw_per_shop": 3,
    "straw_cap": 42,
    "tom_first": 8,
    "tom_last": 18,
    "tom_base": 0,
    "tom_per_shop": 6,
    "tom_cap": 20,
    "herd_day": 6,
    "sheep_per_yarn": 5,
    "sheep_cap": 16,
    "cow_base": 4,
    "cow_per_milk": 2,
    "cow_cap": 12,
    "goose_base": 2,
    "goose_per_egg": 2,
    "goose_cap": 4,
    "animal_cap": 24,
    "cow_last": 17,
    "sheep_last": 20,
    "goose_last": 15,
    "maint_frac": 0.30,
    "land_first": [4, 8, 10],
    "land_last": [14, 14, 0],
    "land_reserve": 0,
    "hires": [4, 4, 6, 6, 6, 6, 8, 9, 9, 10, 11] + [12] * 17 + [11, 10],
    "fert_wheat_ratio": 1.6,
    "zone_release_day": 13,
    "wheat_last": 26,
    "carrot_last": 26,
    "sell_hold_frac": 0.0,
    "early_drop_day": 11,
    "w_future": 0.3,
    "opp_straw_final": 30,
    "straw_min": 10,
    "demand_model": True,
    "room_mult": 0.7,
    "hire_cap_day": 10,
    "zone_margin": 4,
    "placeholder": False,
    "night_hour": 17,
    "alloc_order": False,
    "wheat_keep_hour": 12,
    "animal_roi": 1.0,
    "last_margin": 1,
    "last_carry_val": 150,
    "tom_min_price": 70,
    "fert_prio": 105.0,
    "final_harv_prio": 115.0,
    "xmax": {"TOMATO": 20, "CARROT": 40},
    "nofert_skip": True,
    "work_mult": 1.5,
    "crop_mode": "rule",
    "prem_disc": 0.85,
    "straw_bias": 0.0,
    "labor_coin": 0.0,
    "collect_base": 55.0,
    "collect_mult": 0.5,
    "partial_pen": 0.0,
    "steep_drop": 0.0,
    "steep_drop_cap": 90.0,
    "arb_n": 0,
    "hire_fb": False,
    "hire_fb_max": 13,
    "hire_fb_idle": 12,
}


def g(o, k, d=None):
    if isinstance(o, dict):
        return o.get(k, d)
    try:
        return o[k]
    except Exception:
        return getattr(o, k, d)


def fib_sum(a, b):
    """cost of hires number a..b-1 of the day (0-indexed)."""
    f = [1, 1]
    while len(f) < b + 2:
        f.append(f[-1] + f[-2])
    return sum(f[i] for i in range(a, b))


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


def make_agent(params=None):
    P = dict(DEFAULT_PARAMS)
    if params:
        P.update(params)
    MEM = {}

    def act(obs, config=None):
        try:
            return _act(obs, P, MEM)
        except Exception:
            if P.get("debug"):
                import traceback
                traceback.print_exc()
            return {"farmer": ["PASS"], "hands": [], "market": []}

    return act


def _act(obs, P, MEM):
    me_id = int(g(obs, "player", 0) or 0)
    step = int(g(obs, "step", 0) or 0)
    mem = MEM.get(me_id)
    if mem is None or step == 0 or mem.get("last_step", -1) >= step:
        mem = {}
        MEM[me_id] = mem
    mem["last_step"] = step
    day, hour = divmod(step, TPD)
    last_day = day == DAYS - 1

    farms = g(obs, "farms")
    me = farms[me_id]
    opp = farms[1 - me_id] if len(farms) > 1 else None
    priv = g(obs, "private")
    market = g(obs, "market")
    town = g(obs, "town") or {}
    tiles = me["tiles"]
    money = float(me["money"])
    shed = {k: int(v) for k, v in dict(priv["shed"]).items()}
    seeds = {k: int(v) for k, v in dict(priv["seeds"]).items()}
    units = [tuple(me["farmer"])] + [tuple(h) for h in me["hands"]]
    raw_invs = list(priv["inventories"])
    uitems = []
    for i in range(len(units)):
        inv = dict(raw_invs[i]) if i < len(raw_invs) else {}
        uitems.append({k: int(v) for k, v in inv.items() if int(v) > 0})
    minv = {k: int(v) for k, v in dict(market["inventory"]).items()}
    prices = {k: int(v) for k, v in dict(market["prices"]).items()}
    shops = list(g(town, "unlocked_shops", []) or [])
    n_quads = len(me["unlocked_quadrants"])
    hires_today = int(me.get("hires_today", 0) if isinstance(me, dict) else g(me, "hires_today", 0))

    # ------------------------------------------------------------ survey
    animals = []          # (pos, tile)
    estruct = {"COOP": [], "PASTURE": []}
    plants = []           # (pos, tile)
    weeds = []
    empties = []
    cnt_animal = {a: 0 for a in ANIMALS}
    cnt_crop = {c: 0 for c in CROPS}
    for y in range(N):
        row = tiles[y]
        for x in range(N):
            t = row[x]
            p = (x, y)
            if t is None:
                empties.append(p)
            elif t == "LOCKED":
                continue
            elif isinstance(t, dict):
                k = t.get("kind")
                if k == "PLANT":
                    plants.append((p, t))
                    cnt_crop[t["crop"]] += 1
                elif k == "WEED":
                    weeds.append(p)
                elif t.get("animal"):
                    animals.append((p, t))
                    cnt_animal[t["animal"]] += 1
                elif k in estruct:
                    estruct[k].append(p)
    opp_animal = {a: 0 for a in ANIMALS}
    opp_crop = {c: 0 for c in CROPS}
    if opp is not None:
        for row in opp["tiles"]:
            for t in row:
                if isinstance(t, dict):
                    if t.get("animal"):
                        opp_animal[t["animal"]] += 1
                    elif t.get("kind") == "PLANT":
                        opp_crop[t["crop"]] += 1

    carried = {}
    for it in uitems:
        for k, v in it.items():
            carried[k] = carried.get(k, 0) + v
    stock = {a: shed.get(a, 0) + carried.get(a, 0) for a in ANIMALS}
    have = {a: cnt_animal[a] + stock[a] for a in ANIMALS}

    if "melons" not in mem:
        mem["melons"] = 0
    fert_price = prices["FERTILIZER"]
    wheat_price = prices["WHEAT"]

    # ------------------------------------------------------------ animal policy
    feed_mode = {}
    for a, ad in ANIMALS.items():
        pr = prices[ad["product"]]
        mode = "full"
        if day >= 8 and pr < P["maint_frac"] * BASE[ad["product"]]:
            mode = "maint"
        feed_mode[a] = mode

    def animal_info(t):
        a = t["animal"]
        ad = ANIMALS[a]
        first = t["placed_day"] + ad["fyd"] - 1
        iv = ad["interval"]
        prod_today = day >= first and (day - first) % iv == 0
        if first > DAYS - 2:
            lastp = None
        else:
            lastp = first + ((DAYS - 2 - first) // iv) * iv
        if day <= first:
            nextp = first
        else:
            nextp = first + ((day - first + iv - 1) // iv) * iv
        return ad, prod_today, lastp, nextp

    feed_jobs = 0  # animals that still need FEED today
    animal_task = {}
    for (p, t) in animals:
        ad, prod_today, lastp, nextp = animal_info(t)
        a = t["animal"]
        mode = feed_mode[a]
        pend = int(t.get("pending_care_bonus", 0) or 0)
        cu = int(t.get("consecutive_unfed", 0))
        fed = bool(t.get("fed_today"))
        cared = bool(t.get("cared_today"))
        yu = int(t.get("yield_units", 0))
        future = lastp is not None and day <= lastp
        bank_after = 0 if prod_today else pend
        care_useful = (mode == "full" and lastp is not None and day < lastp and (1 + bank_after) < ad["cap"]
                       and not last_day)
        need_feed = False
        if not fed and not last_day and future:
            if care_useful:
                need_feed = True
            elif prod_today and pend > 0:
                need_feed = True
            elif cu >= 1:
                need_feed = True
        need_care = care_useful and not cared
        # harvest policy
        exp_prod = (1 + (pend if (fed or need_feed) else 0)) if prod_today else 0
        must_harv = yu > 0 and prod_today and yu + exp_prod > ad["cap"]
        want_harv = False
        if yu > 0:
            thr = {"SHEEP": 4, "COW": 4, "GOOSE": 3}[a]
            if day <= P["early_drop_day"]:
                thr = 1
            if yu >= thr or last_day or (lastp is not None and day > lastp) or day >= DAYS - 2:
                want_harv = True
            if mode == "maint" and not must_harv and not last_day and day < DAYS - 2:
                want_harv = yu >= ad["cap"] - 1
        collect = bool(t.get("fertilizer_available"))
        if need_feed:
            feed_jobs += 1
        animal_task[p] = (a, need_feed, need_care, collect, must_harv, want_harv, cu, prod_today, pend, fed)

    # ------------------------------------------------------------ fertilizer policy
    fert_on_wheat = fert_price < P["fert_wheat_ratio"] * wheat_price and not last_day

    def plant_info(t):
        crop = t["crop"]
        cd = CROPS[crop]
        age = day - t["planted_day"]
        return crop, cd, age

    # ------------------------------------------------------------ hires plan
    sched = P["hires"]
    hire_target = sched[min(day, len(sched) - 1)]
    # workload cap (rough unit-turn estimate)
    work = 3.0 * len(animals) + 4.0 * sum(stock.values())
    for (p, t) in plants:
        work += 1.6 if t["crop"] in ("STRAWBERRY",) else 2.0
    work += 2.5 * (len(empties) + len(weeds))
    need_units = int(math.ceil(work * P["work_mult"] / 22.0))
    if day >= P["hire_cap_day"]:
        hire_target = max(0, min(hire_target, max(3, need_units - 1)))
    if P["hire_fb"] and day >= 11 and not last_day:
        adj = mem.get("hire_adj", 0)
        hire_target = max(3, min(P["hire_fb_max"], hire_target + adj))

    # ------------------------------------------------------------ market sale estimate (for budget)
    # drops happen this turn only for units standing at shed; estimated later. Use shed now.
    # ------------------------------------------------------------ herd targets
    ny = shops.count("YARN_STORE")
    nm = sum(shops.count(s) for s in MILK_SHOPS)
    ne = sum(shops.count(s) for s in EGG_SHOPS)
    nb = sum(shops.count(s) for s in BERRY_SHOPS)
    nt = sum(shops.count(s) for s in TOMATO_SHOPS)
    # ---- demand model: room (units) each product can still absorb at a decent price
    room = {}
    if P["demand_model"]:
        sup_me = project_supply(tiles, day)
        sup_op = project_supply(opp["tiles"], day) if opp is not None else {p: 0.0 for p in PRODUCTS}
        # opponent strawberries still to be planted (top agents reach ~30 by day 13)
        if day <= 12:
            extra = max(0, P["opp_straw_final"] - opp_crop["STRAWBERRY"])
            sup_op["STRAWBERRY"] += extra * 8 * max(0.0, (13 - day) / 13.0)
        for p in PRODUCTS:
            dem = future_demand(p, day, shops, P["w_future"])
            xm = P["xmax"].get(p, X_MAX[p]) if P.get("xmax") else X_MAX[p]
            room[p] = P["room_mult"] * (xm + (I0 - minv[p])) + dem - sup_op[p] - sup_me[p]
        mem["room"] = room
    if day < P["herd_day"]:
        tgt = {"COW": 2, "SHEEP": 3, "GOOSE": 0}
    elif P["demand_model"]:
        tgt = {}
        for a, ad in ANIMALS.items():
            per = new_animal_units(a, day)
            add = int(max(0.0, room[ad["product"]]) // max(1, per)) if per > 0 else 0
            # payback filter: product value of a new animal must clearly exceed cost + feed
            pr_exp = min(prices[ad["product"]], BASE[ad["product"]] * 1.2)
            feed_days = max(0, DAYS - 2 - day)
            val = per * pr_exp - ad["cost"] - feed_days * wheat_price
            if val < P["animal_roi"] * ad["cost"]:
                add = 0
            capk = {"SHEEP": P["sheep_cap"], "COW": P["cow_cap"], "GOOSE": P["goose_cap"]}[a]
            tgt[a] = max(have[a], min(capk, have[a] + add))
    else:
        tgt = {
            "SHEEP": min(P["sheep_cap"], 3 + P["sheep_per_yarn"] * ny),
            "COW": min(P["cow_cap"], P["cow_base"] + P["cow_per_milk"] * nm),
            "GOOSE": min(P["goose_cap"], P["goose_base"] + P["goose_per_egg"] * ne),
        }
    last_buy = {"COW": P["cow_last"], "SHEEP": P["sheep_last"], "GOOSE": P["goose_last"]}
    for a, ad in ANIMALS.items():
        if day > last_buy[a] or (day >= P["herd_day"] and prices[ad["product"]] < 0.75 * BASE[ad["product"]]):
            tgt[a] = min(tgt[a], have[a])
    tot_t = sum(tgt.values())
    if tot_t > P["animal_cap"]:
        # trim lowest-value species first
        for a in ("GOOSE", "COW", "SHEEP"):
            ex = sum(tgt.values()) - P["animal_cap"]
            if ex <= 0:
                break
            cut = min(ex, max(0, tgt[a] - have[a]))
            tgt[a] -= cut

    # ------------------------------------------------------------ budget
    # estimate this turn's sale proceeds from shed stock (drops added later are ignored for budget)
    budget = money
    reserve_cash = 0.0
    orders_hire = 0
    if hour <= 3 and hires_today < hire_target:
        orders_hire = hire_target - hires_today
    hire_cost = fib_sum(hires_today, hires_today + orders_hire) if orders_hire else 0

    # ------------------------------------------------------------ tile roles
    free = sorted(empties + weeds, key=lambda p: CROP_RANK[p])
    free_set = set(free)
    # structures needed for animals not yet placed plus animals we plan to buy
    unplaced = {"COOP": stock["GOOSE"], "PASTURE": stock["COW"] + stock["SHEEP"]}
    want_new = {a: max(0, tgt[a] - have[a]) for a in ANIMALS}

    plan = {}  # pos -> ("BUILD", kind) | ("PLANT", crop)
    struct_tiles = [p for p in STRUCT_ORDER if p in free_set]
    if day == 0:
        struct_tiles = [p for p in D0_PASTURES if p in free_set] + [p for p in struct_tiles if p not in D0_PASTURES]
    used = set()

    def take_struct_tile():
        for p in struct_tiles:
            if p in used:
                continue
            if day <= 9 and p in MELON_TILES:
                continue
            used.add(p)
            return p
        return None

    for kind in ("PASTURE", "COOP"):
        need = unplaced[kind] - len(estruct[kind])
        for _ in range(max(0, need)):
            p = take_struct_tile()
            if p is None:
                break
            plan[p] = ("BUILD", kind)

    # animal purchases (budget permitting): each needs a structure (existing empty or new tile)
    buy_animals = {a: 0 for a in ANIMALS}
    spare_struct = {k: len(estruct[k]) - unplaced[k] for k in estruct}
    spend_first = []  # list of (priority, cost, callback)

    # --- compute budget items in priority order
    est_sales = 0.0  # filled after sell planning; used conservatively
    # feed wheat need
    wheat_have = shed.get("WHEAT", 0) + carried.get("WHEAT", 0)
    wheat_buy = 0
    if not last_day:
        wneed = feed_jobs - wheat_have
        if hour <= 20 and wneed > 0:
            wheat_buy = wneed + (0 if day < 3 else (1 if day < 8 else 2))

    # land
    land_buy = False
    n_extra = n_quads - 1

    # seeds to buy
    seed_buy = {c: 0 for c in CROPS}

    # ---------------------------------------------------------- sell planning (before budget)
    # shed after this turn's unit actions is unknown until assignment; plan sells after assignment.
    # For budget we approximate proceeds from shed stock minus reserves.
    fert_reserve_need = 0
    for (p, t) in plants:
        crop, cd, age = plant_info(t)
        if crop == "STRAWBERRY" and age + 2 >= 9 and age <= 13:
            if t.get("fertilized_until_day", -1) < day + 1:
                fert_reserve_need += 1
        elif crop == "TOMATO" and age + 2 >= 7 and age <= 10:
            if t.get("fertilized_until_day", -1) < day + 1:
                fert_reserve_need += 1
        elif crop in ("WHEAT", "CARROT") and fert_on_wheat and age <= 2:
            if t.get("fertilized_until_day", -1) < day:
                fert_reserve_need += 1
    if fert_on_wheat:
        fert_reserve_need += len(empties) // 3
    fert_reserve = max(0, fert_reserve_need - carried.get("FERTILIZER", 0))
    wheat_reserve = 0 if last_day else max(0, feed_jobs - carried.get("WHEAT", 0))
    if not last_day and hour >= P["wheat_keep_hour"] and day < DAYS - 1:
        # keep tomorrow's feed instead of selling tonight and buying back at hour 0
        wheat_reserve += len(animals) + sum(stock.values()) + 2

    def sellable_from(shed_state):
        out = {}
        for item in PRODUCTS:
            h = shed_state.get(item, 0)
            if item == "WHEAT":
                h -= wheat_reserve
            elif item == "FERTILIZER":
                h -= fert_reserve
            if h > 0:
                out[item] = h
        return out

    pre_sell = sellable_from(shed)
    for item, n in pre_sell.items():
        est_sales += sell_revenue(item, minv[item], n)
    budget = money + 0.92 * est_sales
    budget -= hire_cost
    budget -= wheat_buy * (wheat_price + 2)
    # overnight reserve: tomorrow's hires + morning feed wheat must be affordable at hour 0
    if hour >= P["night_hour"] and not last_day:
        nxt = sched[min(day + 1, len(sched) - 1)]
        morning = fib_sum(0, nxt) + max(0, len(animals) + sum(stock.values()) - shed.get("WHEAT", 0)) * (wheat_price + 2)
        budget -= morning

    # land
    saving = False
    cheap_extra = 0.0
    if n_extra < 3 and P["land_first"][n_extra] <= day <= P["land_last"][n_extra]:
        price = LAND_PRICES[n_extra]
        if budget >= price + P["land_reserve"]:
            land_buy = True
            budget -= price
        else:
            # liquid value: cash + shed goods + products waiting on animals / ripe melons
            liquid = budget
            for (p_, t_) in animals:
                liquid += 0.9 * int(t_.get("yield_units", 0)) * prices[ANIMALS[t_["animal"]]["product"]]
            for (p_, t_) in plants:
                if t_["crop"] == "MELON" and day - t_["planted_day"] >= 9:
                    liquid += 0.9 * 6 * prices["MELON"]
            if liquid >= price + P["land_reserve"]:
                saving = True
                cheap_extra = min(price, max(0.0, budget), 250.0)  # wheat placeholders may use the reserve
                budget -= price  # reserve: animals/seeds only from the surplus

    # new land bought this turn: its tiles become free next turn (no planning now)

    # ---------------------------------------------------------- crop plan for remaining free tiles
    n_straw = cnt_crop["STRAWBERRY"]
    n_tom = cnt_crop["TOMATO"]
    if P["demand_model"]:
        add_s = int(max(0.0, room["STRAWBERRY"]) // 8)
        s_target = min(P["straw_cap"], n_straw + add_s)
        if day <= 6:
            s_target = max(s_target, P["straw_min"])
        add_t = int(max(0.0, room["TOMATO"]) // 8)
        t_target = min(P["tom_cap"], n_tom + add_t)
        if prices["TOMATO"] < P["tom_min_price"]:
            t_target = n_tom
        carrot_ok = room["CARROT"] > 0 and prices["CARROT"] > 1.25 * wheat_price + 3
    else:
        s_target = min(P["straw_cap"], P["straw_base"] + P["straw_per_shop"] * nb)
        t_target = 0
        if nt > 0:
            t_target = min(P["tom_cap"], P["tom_base"] + P["tom_per_shop"] * nt)
        carrot_ok = False
    n_carrot_plan = 0
    carrot_cap = int(max(0.0, room.get("CARROT", 0)) // 4) if P["demand_model"] else 0
    # capital allocation: reserve money for strawberries (highest return per coin), then cows/sheep,
    # tomatoes, geese last
    free_crop_n = sum(1 for p in free if p not in plan and p not in ZONE and p not in MELON_TILES)
    if day >= 10:
        free_crop_n += sum(1 for p in free if p in MELON_TILES and p not in plan)
    straw_res = 0.0
    tom_res = 0.0
    if P["alloc_order"] and P["straw_first"] <= day <= P["straw_last"]:
        ns = max(0, min(s_target - n_straw, free_crop_n) - seeds.get("STRAWBERRY", 0))
        straw_res = ns * CROPS["STRAWBERRY"]["seed"]
        free_crop_n -= min(s_target - n_straw, free_crop_n) if s_target > n_straw else 0
    if P["alloc_order"] and P["tom_first"] <= day <= P["tom_last"]:
        nt_ = max(0, min(t_target - n_tom, free_crop_n) - seeds.get("TOMATO", 0))
        tom_res = nt_ * CROPS["TOMATO"]["seed"]
    order_a = ["SHEEP", "COW", "GOOSE"] if ny > 0 else ["COW", "SHEEP", "GOOSE"]
    for a in order_a:
        kind = ANIMALS[a]["kind"]
        cost = ANIMALS[a]["cost"]
        res = straw_res + (tom_res if a == "GOOSE" else 0.0)
        while want_new[a] > 0 and budget - res >= cost:
            if spare_struct[kind] > 0:
                spare_struct[kind] -= 1
            else:
                p = take_struct_tile()
                if p is None:
                    break
                plan[p] = ("BUILD", kind)
            buy_animals[a] += 1
            want_new[a] -= 1
            budget -= cost
    melons_left = max(0, P["melon_n"] - mem["melons"])
    seeds_left = dict(seeds)
    zone_hold = day < P["zone_release_day"]
    hours_left = TPD - hour
    crop_tiles = [p for p in free if p not in plan]
    # keep zone tiles next to the shed free for animals still to come
    zone_free = [p for p in struct_tiles if p in ZONE and p in free_set and p not in plan and p not in MELON_TILES]
    fut_need = sum(max(0, tgt[a] - have[a] - buy_animals[a]) for a in ANIMALS)
    if day < P["zone_release_day"]:
        fut_need += P["zone_margin"]
    if day > P["sheep_last"]:
        fut_need = 0
    keep = set(zone_free[:max(0, fut_need)])
    crop_tiles = [p for p in crop_tiles if p not in keep]
    planted_plan = {c: 0 for c in CROPS}
    wait_for_cash = 0
    for p in crop_tiles:
        if hours_left < 2:
            break
        choice = None
        if day <= 1 and p in MELON_TILES and melons_left > 0:
            if day == 0 and p in MELON_D1:
                continue  # reserved for day-1 melons
            choice = "MELON"
            melons_left -= 1
        elif day <= 9 and p in MELON_TILES and (day <= 1 or cnt_crop["MELON"] > 0):
            # keep template melon tiles for melons only (day<=1); later normal
            if day <= 1:
                continue
        if choice is None and P["crop_mode"] == "value":
            in_zone = p in ZONE and zone_hold
            fprice = fert_price
            cands = []
            lam = P["labor_coin"]
            if day <= P["wheat_last"]:
                if fert_on_wheat:
                    cands.append(((5 * wheat_price - 10 - fprice) / 3.0 - 2.0 * lam, "WHEAT"))
                else:
                    cands.append(((4 * wheat_price - 10) / 4.0 - 1.5 * lam, "WHEAT"))
            if not in_zone and P["straw_first"] <= day <= P["straw_last"] and n_straw < s_target:
                npd = sum(1 for a_ in (9, 11, 13, 15) if day + a_ <= DAYS - 2)
                life = min(17, DAYS - day)
                v = (2 * npd * prices["STRAWBERRY"] * P["prem_disc"] - 100 - 2 * fprice) / life
                cands.append((v + P["straw_bias"] - 0.8 * lam, "STRAWBERRY"))
            if not in_zone and P["tom_first"] <= day <= P["tom_last"] and n_tom < t_target:
                npd = sum(1 for a_ in (7, 8, 9, 10) if day + a_ <= DAYS - 2)
                life = min(12, DAYS - day)
                v = (2 * npd * prices["TOMATO"] * P["prem_disc"] - 50 - 2 * fprice) / life
                cands.append((v - 1.0 * lam, "TOMATO"))
            if room.get("CARROT", 0) > 0 and n_carrot_plan < carrot_cap and day <= P["carrot_last"]:
                if fert_on_wheat:
                    cands.append(((4 * prices["CARROT"] - 20 - fprice) / 3.0 - 2.0 * lam, "CARROT"))
                else:
                    cands.append(((3 * prices["CARROT"] - 20) / 3.0 - 1.7 * lam, "CARROT"))
            if cands:
                cands.sort(key=lambda z: -z[0])
                choice = cands[0][1]
                if choice == "STRAWBERRY":
                    n_straw += 1
                elif choice == "TOMATO":
                    n_tom += 1
                elif choice == "CARROT":
                    n_carrot_plan += 1
        if choice is None and P["crop_mode"] != "value":
            in_zone = p in ZONE and zone_hold
            if (not in_zone and P["straw_first"] <= day <= P["straw_last"] and n_straw < s_target):
                choice = "STRAWBERRY"
                n_straw += 1
            elif (not in_zone and P["tom_first"] <= day <= P["tom_last"] and n_tom < t_target):
                choice = "TOMATO"
                n_tom += 1
            elif carrot_ok and n_carrot_plan < carrot_cap and day <= P["carrot_last"]:
                choice = "CARROT"
                n_carrot_plan += 1
            elif day <= P["wheat_last"]:
                choice = "WHEAT"
            elif day <= P["carrot_last"]:
                choice = "CARROT"
        if choice is None:
            continue
        cost = CROPS[choice]["seed"]
        if seeds_left.get(choice, 0) > 0:
            seeds_left[choice] -= 1
        elif budget >= cost:
            seed_buy[choice] += 1
            budget -= cost
        else:
            if choice in ("STRAWBERRY", "TOMATO", "MELON") and day <= 12:
                wait_for_cash += 1
                if not P["placeholder"] or choice == "MELON":
                    continue  # keep tile free for the premium crop
                if choice == "STRAWBERRY":
                    n_straw -= 1
                elif choice == "TOMATO":
                    n_tom -= 1
            if budget + cheap_extra >= CROPS["WHEAT"]["seed"] and day <= P["wheat_last"]:
                choice = "WHEAT"
                if seeds_left.get("WHEAT", 0) > 0:
                    seeds_left["WHEAT"] -= 1
                else:
                    seed_buy["WHEAT"] += 1
                    if budget >= CROPS["WHEAT"]["seed"]:
                        budget -= CROPS["WHEAT"]["seed"]
                    else:
                        cheap_extra -= CROPS["WHEAT"]["seed"]
            else:
                continue
        plan[p] = ("PLANT", choice)
        planted_plan[choice] += 1

    # early wheat harvest to free tiles for strawberries (days 2-6)
    early_wheat = 0
    prem_want = 0
    if P["straw_first"] <= day <= P["straw_last"]:
        prem_want += max(0, s_target - n_straw)
    if P["tom_first"] <= day <= P["tom_last"]:
        prem_want += max(0, t_target - n_tom)
    if prem_want > 0:
        affordable = int(max(0, budget) // 60)
        early_wheat = max(0, min(affordable, prem_want))

    # ------------------------------------------------------------ tile jobs
    # job: [pos, prio_full, act_full, need_full, prio_part, act_part, n_acts]
    jobs = []
    fert_jobs = 0

    def add_job(p, pf, af, nf, pp, ap, n):
        jobs.append((p, pf, af, nf, pp, ap, n))

    # animals
    for (p, t) in animals:
        a, need_feed, need_care, collect, must_harv, want_harv, cu, prod_today, pend, fed = animal_task[p]
        prod = ANIMALS[a]["product"]
        pr = prices[prod]
        acts_full = []
        acts_part = []
        if need_feed:
            v = 95.0
            if cu >= 1:
                v = 140.0 + 3 * hour
            if prod_today and pend > 0:
                v = max(v, 130.0 + 3 * hour)
            acts_full.append((v, ["FEED"]))
            if need_care:
                acts_full.append((90.0, ["CARE"]))
        elif need_care and fed:
            acts_full.append((90.0, ["CARE"]))
            acts_part.append((90.0, ["CARE"]))
        if collect:
            cv = 85.0 if day < 10 else (P["collect_base"] + P["collect_mult"] * fert_price)
            acts_full.append((cv, ["COLLECT_FERTILIZER"]))
            acts_part.append((cv, ["COLLECT_FERTILIZER"]))
        if must_harv:
            acts_full.append((105.0, ["HARVEST"]))
            acts_part.append((105.0, ["HARVEST"]))
        elif want_harv:
            hv = 45.0 + min(40.0, 0.05 * pr * t["yield_units"])
            if last_day or day <= P["early_drop_day"]:
                hv = 90.0
            acts_full.append((hv, ["HARVEST"]))
            acts_part.append((hv, ["HARVEST"]))
        if not acts_full and not acts_part:
            continue
        if need_feed:
            pf = max(v for v, _ in acts_full)
            af = acts_full[0][1]
            if acts_part:
                pp = max(v for v, _ in acts_part) - P["partial_pen"]
                ap = acts_part[0][1]
            else:
                pp, ap = None, None
            add_job(p, pf, af, "WHEAT", pp, ap, len(acts_full))
        else:
            pf = max(v for v, _ in acts_full)
            add_job(p, pf, acts_full[0][1], None, None, None, len(acts_full))

    # empty structures -> PLACE
    for kind, lst in estruct.items():
        for p in lst:
            add_job(p, 150.0, ["PLACE", kind], "ANIMAL:" + kind, None, None, 3)

    # plants
    for (p, t) in plants:
        crop, cd, age = plant_info(t)
        watered = bool(t.get("watered_today"))
        cu = int(t.get("consecutive_unwatered", 0))
        yu = int(t.get("yield_units", 0))
        fut = int(t.get("fertilized_until_day", -1))
        acts = []   # (prio, op, need)
        if not cd["ongoing"]:
            ws = (cd["mxd"] + 1) // 2
            in_window = ws <= age <= cd["mxd"]
            fert_now = False
            if crop in ("WHEAT", "CARROT") and fert_on_wheat and age == ws and fut < day and not watered \
                    and not last_day:
                fert_now = True
            if crop == "WHEAT":
                h_age = 3 if fut >= day - 1 else 4
                if early_wheat > 0 and age >= 2 and day <= max(P["straw_last"], P["tom_last"]):
                    h_age = 2
            elif crop == "CARROT":
                h_age = 3 if fut < day - 1 else 2
                h_age = 3
            else:  # melon
                h_age = 10
            if last_day or (day == DAYS - 2 and age + 1 > cd["mxd"]):
                h_age = cd["fyd"]
            ready = age >= max(h_age, cd["fyd"]) and yu > 0
            if crop == "WHEAT" and ready and h_age == 2 and age < 3:
                early_wheat -= 1
            must_w = (not watered) and cu >= 1 and not (ready and not in_window)
            yield_w = (not watered) and in_window and yu < cd["max_yield"]
            if last_day and not ready:
                must_w = False
                yield_w = yield_w and False
            if fert_now:
                acts.append((92.0, ["FERTILIZE"], "FERTILIZER"))
                fert_jobs += 1
            if must_w or yield_w:
                if must_w and not yield_w:
                    pr = (120.0 if crop == "MELON" else 100.0) + 2 * hour
                    if ready:
                        pr = 0
                else:
                    pr = 95.0 if crop == "MELON" else 88.0
                    if must_w:
                        pr = max(pr, (120.0 if crop == "MELON" else 100.0) + 2 * hour)
                if pr > 0:
                    acts.append((pr, ["WATER"], None))
            if ready:
                hv = 85.0
                if crop == "MELON":
                    hv = 150.0
                if crop == "WHEAT" and age >= 4:
                    hv = 110.0
                acts.append((hv, ["HARVEST"], None))
        else:
            fyd = cd["fyd"]
            iv = cd["interval"]
            k = age + 1 - fyd
            prod_today = k >= 0 and k % iv == 0 and (k // iv + 1) <= cd["max_yield"]
            last_prod_age = fyd - 1 + (cd["max_yield"] - 1) * iv
            done = age > last_prod_age
            fert_active = fut >= day
            # production doubling needs watered_today and fertilized_until>=day at day end; order is free
            fert_now = prod_today and not fert_active and not last_day
            must_w = (not watered) and cu >= 1 and not done
            prod_w = (not watered) and prod_today and (fert_active or fert_now)
            if last_day:
                must_w = False
                prod_w = False
            if fert_now:
                acts.append((P["fert_prio"] if crop == "STRAWBERRY" else P["fert_prio"] - 5, ["FERTILIZE"], "FERTILIZER"))
                fert_jobs += 1
            if must_w or prod_w:
                pr = 88.0 if prod_w else 70.0
                if prod_w and fert_active:
                    pr = P["fert_prio"] + 2 * hour  # fertilizer already invested: the water makes it count
                if must_w:
                    pr = max(pr, 100.0 + 2 * hour)
                # watering a production day only pays with fertilizer: a unit without fertilizer
                # may only do it when the plant would otherwise die tonight
                acts.append((pr, ["WATER"], None if (must_w or fert_active or not P["nofert_skip"]) else "NOFERT_SKIP"))
            harv = yu > 0 and age >= fyd and (yu >= 2 or done or last_day or day >= DAYS - 2
                                                or (prod_today and yu + 2 > cd["max_yield"]))
            if harv:
                hv = 75.0
                if prod_today and yu + (2 if fert_active else 1) > cd["max_yield"]:
                    hv = 100.0
                if done:
                    hv = P["final_harv_prio"] + 2 * hour  # decays to weed tomorrow
                if last_day:
                    hv = 110.0
                acts.append((hv, ["HARVEST"], None))
            if done and yu == 0 and not last_day:
                acts.append((45.0, ["DIG"], None))
        if not acts:
            continue
        # first action in order; if first needs fertilizer, partial job skips it
        pf = max(a[0] for a in acts)
        first = acts[0]
        if first[2] == "FERTILIZER":
            rest = [a_ for a_ in acts[1:] if a_[2] != "NOFERT_SKIP"]
            if rest:
                pp = max(a[0] for a in rest)
                add_job(p, pf + 5, first[1], "FERTILIZER", pp - 25.0, rest[0][1], len(acts))
            else:
                add_job(p, pf + 5, first[1], "FERTILIZER", None, None, len(acts))
        else:
            acts2 = [a_ for a_ in acts if a_[2] != "NOFERT_SKIP"]
            if not acts2:
                continue
            add_job(p, max(a_[0] for a_ in acts2), acts2[0][1], None, None, None, len(acts2))

    # free tiles with a plan
    for p, (kind, what) in plan.items():
        t = tiles[p[1]][p[0]]
        if isinstance(t, dict) and t.get("kind") == "WEED":
            add_job(p, 60.0, ["DIG"], None, None, None, 3)
            continue
        if kind == "BUILD":
            add_job(p, 110.0, ["BUILD_" + what], None, None, None, 2)
        else:
            pv = 75.0 if what in ("STRAWBERRY", "TOMATO", "MELON") else 62.0
            add_job(p, pv, ["PLANT", what], "SEED:" + what, None, None, 2)
    # weeds not planned: dig anyway (they block future use)
    for p in weeds:
        if p not in plan and day <= DAYS - 4:
            add_job(p, 30.0, ["DIG"], None, None, None, 1)

    if P.get("debug_step") == step:
        print("ROOM", {k: round(v) for k, v in room.items()}, "tgt", tgt, "have", have, "buy", buy_animals, "saving", saving, "land_buy", land_buy)
        print("DEBUG step", step, "free", len(free), "plan", plan, "keep", sorted(keep), "seeds", seeds, "seed_buy", seed_buy,
              "budget", round(budget), "s_target", s_target, "t_target", t_target, "carrot_ok", carrot_ok)
        for j in sorted(jobs, key=lambda j: -j[1]):
            print("   job", j)
    # ------------------------------------------------------------ assignment
    n_units = len(units)
    W = P["w_dist"]
    BURST = P["burst"]
    STICK = P["stick"]
    prev_tgt = mem.get("tgt", {}) if mem.get("tgt_day") == day else {}
    seed_avail = dict(seeds)            # for immediate PLANT
    seed_future = dict(seeds)
    for c, n in seed_buy.items():
        seed_future[c] = seed_future.get(c, 0) + n
    actions = [None] * n_units
    tgt_now = {}
    shed_left = dict(shed)
    uncovered_feed = feed_jobs - carried.get("WHEAT", 0)
    uncovered_fert = fert_jobs - carried.get("FERTILIZER", 0)
    # animals waiting in shed to be placed (not carried)
    open_slots = {k: len(estruct[k]) + sum(1 for pp, (kk, ww) in plan.items() if kk == "BUILD" and ww == k)
                  for k in estruct}
    carried_kind = {"COOP": carried.get("GOOSE", 0), "PASTURE": carried.get("COW", 0) + carried.get("SHEEP", 0)}
    animal_pick = {"COOP": max(0, min(shed.get("GOOSE", 0), open_slots["COOP"] - carried_kind["COOP"])),
                   "PASTURE": max(0, min(shed.get("COW", 0) + shed.get("SHEEP", 0),
                                         open_slots["PASTURE"] - carried_kind["PASTURE"]))}

    def sell_value(it):
        v = 0.0
        for k, n in it.items():
            if k in ("WHEAT",) or k in ANIMALS:
                continue
            if k == "FERTILIZER" and uncovered_fert > -3 and day >= 9:
                continue
            v += n * prices.get(k, 0)
        return v

    early = day < P["early_drop_day"]
    last_drop_step = LAST_STEP
    crew = hire_target + 1 if hour == 0 else n_units

    def shed_action(i):
        """Best (value, action) for unit i if it is at / goes to a shed tile."""
        it = uitems[i]
        best = (None, None)
        # drop
        sv = sell_value(it)
        dv = 0.0
        if sv > 0:
            if last_day:
                dv = 60.0 + (100.0 if step >= LAST_STEP - 8 else 0.0)
            elif early:
                dv = min(130.0, 40.0 + sv / 8.0)
            else:
                dv = min(70.0, sv / 25.0)
                if P["steep_drop"] > 0:
                    steep_v = sum(n * prices.get(k, 0) for k, n in it.items()
                                  if k in ("MILK", "WOOL", "STRAWBERRY", "MELON"))
                    dv = max(dv, min(P["steep_drop_cap"], steep_v * P["steep_drop"]))
        if dv > 0:
            best = (dv, ["DROP"])
        # animal pickup
        if it.get("GOOSE", 0) + it.get("COW", 0) + it.get("SHEEP", 0) == 0:
            for kind, animals_k in (("PASTURE", ("SHEEP", "COW")), ("COOP", ("GOOSE",))):
                if animal_pick[kind] > 0:
                    for a in animals_k:
                        if shed_left.get(a, 0) > 0:
                            v = 150.0
                            if best[0] is None or v > best[0]:
                                best = (v, ["PICKUP", a, 1])
                            break
        # wheat pickup
        if it.get("WHEAT", 0) == 0 and uncovered_feed > 0 and shed_left.get("WHEAT", 0) > 0:
            k = min(shed_left["WHEAT"], max(2, int(math.ceil(uncovered_feed / max(1, n_units, crew))) + 1))
            v = 100.0 + (2 * hour if hour > 12 else 0)
            if best[0] is None or v > best[0]:
                best = (v, ["PICKUP", "WHEAT", k])
        if it.get("FERTILIZER", 0) == 0 and uncovered_fert > 0 and shed_left.get("FERTILIZER", 0) > 0:
            k = min(shed_left["FERTILIZER"], max(2, int(math.ceil(uncovered_fert / 3.0))))
            v = 92.0
            if best[0] is None or v > best[0]:
                best = (v, ["PICKUP", "FERTILIZER", k])
        return best

    def apply_shed(i, act):
        nonlocal uncovered_feed, uncovered_fert
        if act[0] == "PICKUP":
            item, k = act[1], int(act[2])
            shed_left[item] = shed_left.get(item, 0) - k
            if item == "WHEAT":
                uncovered_feed -= k
            elif item == "FERTILIZER":
                uncovered_fert -= k
            elif item in ANIMALS:
                animal_pick[ANIMALS[item]["kind"]] -= 1

    # last day: every unit carrying goods must reach a shed tile and DROP by the final step
    if last_day:
        for i, pos in enumerate(units):
            it = uitems[i]
            val = sum(n * max(1, prices.get(k, 0)) for k, n in it.items() if k in prices)
            if val <= 0:
                continue
            d = dist(pos, NEAR_SHED[pos])
            if step + d >= LAST_STEP - P["last_margin"] or (val >= P["last_carry_val"] and step + d >= LAST_STEP - 6):
                if pos in SHED_SET:
                    actions[i] = ["DROP"]
                else:
                    actions[i] = [step_toward(pos, NEAR_SHED[pos])]
    # pre-pass: units standing on shed tiles take pickups/drops when valuable
    for i, pos in enumerate(units):
        if pos in SHED_SET and actions[i] is None:
            v, act = shed_action(i)
            if act is None:
                continue
            # compare against best tile job at distance 0 (the shed tile itself may hold an animal)
            local = 0.0
            for j in jobs:
                if j[0] == pos:
                    local = max(local, j[1] if (j[3] is None or _has(uitems[i], j[3], seed_avail)) else (j[4] or 0))
            if act[0] == "DROP" and v < local:
                continue
            if act[0] == "PICKUP" and act[1] in ("WHEAT", "FERTILIZER") and v < local - 20:
                continue
            actions[i] = act
            apply_shed(i, act)

    pairs = []
    for i, pos in enumerate(units):
        if actions[i] is not None:
            continue
        it = uitems[i]
        pt = prev_tgt.get(i)
        for ji, j in enumerate(jobs):
            p, pf, af, nf, pp, ap, n = j
            d = dist(pos, p)
            if hour + d > TPD - 1:
                continue
            if last_day and af[0] == "HARVEST" and step + d + 1 + SD[p] + 1 > last_drop_step:
                continue
            if nf is None or _has_future(it, nf, seed_future):
                v = pf
                full = True
                if nf is not None and nf.startswith("ANIMAL:"):
                    v += W * d
            elif pp is not None:
                v = pp
                full = False
            else:
                continue
            s = v + BURST * (n - 1) - W * d
            if pt == p:
                s += STICK
            pairs.append((s, d, i, ji, full))
        # shed option
        v, act = shed_action(i)
        if act is not None:
            ns = NEAR_SHED[pos]
            d = dist(pos, ns)
            if hour + d <= TPD - 1:
                pairs.append((v - W * d, d, i, -1, act))
    pairs.sort(key=lambda z: (-z[0], z[1], z[2]))
    taken_u = set(i for i in range(n_units) if actions[i] is not None)
    taken_j = set()
    seed_res = {}
    for s, d, i, ji, extra in pairs:
        if i in taken_u:
            continue
        if ji == -1:
            v, act = shed_action(i)
            if act is None:
                continue
            taken_u.add(i)
            pos = units[i]
            if pos in SHED_SET:
                actions[i] = act
                apply_shed(i, act)
            else:
                actions[i] = [step_toward(pos, NEAR_SHED[pos])]
                tgt_now[i] = NEAR_SHED[pos]
            continue
        if ji in taken_j:
            continue
        p, pf, af, nf, pp, ap, n = jobs[ji]
        full = extra
        it = uitems[i]
        need = nf if full else None
        act = af if full else ap
        if need is not None and need.startswith("SEED:"):
            c = need[5:]
            if d == 0:
                if seed_avail.get(c, 0) <= 0:
                    continue
                seed_avail[c] -= 1
                seed_future[c] -= 1
            else:
                if seed_future.get(c, 0) <= 0:
                    continue
                seed_future[c] -= 1
        if need is not None and need.startswith("ANIMAL:") and d > 0:
            pass
        taken_u.add(i)
        taken_j.add(ji)
        tgt_now[i] = p
        if d == 0:
            act = list(act)
            if act[0] == "PLACE":
                kind = act[1]
                if kind == "COOP":
                    if it.get("GOOSE", 0) <= 0:
                        actions[i] = ["PASS"]
                        continue
                    act = ["PLACE", "GOOSE", 1]
                else:
                    if it.get("SHEEP", 0) > 0:
                        act = ["PLACE", "SHEEP", 1]
                    elif it.get("COW", 0) > 0:
                        act = ["PLACE", "COW", 1]
                    else:
                        actions[i] = ["PASS"]
                        continue
            elif act[0] == "PLANT":
                if act[1] == "MELON":
                    mem["melons"] += 1
            actions[i] = act
        else:
            actions[i] = [step_toward(units[i], p)]

    for i in range(n_units):
        if actions[i] is None:
            actions[i] = ["PASS"]
    if P.get("stats") is not None:
        st = P["stats"]
        if hour == 12:
            st.setdefault("daily", {})[day] = (len(empties), len(weeds), len(plants), len(animals),
                                               int(money), n_units, n_quads, dict(cnt_crop), dict(cnt_animal))
        for i in range(n_units):
            a0 = actions[i][0]
            if a0 in ("NORTH", "SOUTH", "EAST", "WEST"):
                st["moves"] = st.get("moves", 0) + 1
                if i in prev_tgt and i in tgt_now and prev_tgt[i] != tgt_now[i] and units[i] != prev_tgt[i]:
                    st["switch"] = st.get("switch", 0) + 1
            elif a0 == "PASS":
                st["pass"] = st.get("pass", 0) + 1
                ph = st.setdefault("pass_hour", [0] * 24)
                ph[hour] += 1
                pd = st.setdefault("pass_day", [0] * 30)
                pd[day] += 1
            else:
                st["work"] = st.get("work", 0) + 1
    mem["tgt"] = tgt_now
    mem["tgt_day"] = day
    if P["hire_fb"]:
        if hour >= 2 and hour <= 19:
            mem["idle_n"] = mem.get("idle_n", 0) + sum(1 for a in actions if a[0] == "PASS")
        if hour == TPD - 1:
            crit = 0
            for (p_, t_) in animals:
                if animal_task[p_][1]:
                    crit += 1
            for (p_, t_) in plants:
                if not t_.get("watered_today") and int(t_.get("consecutive_unwatered", 0)) >= 1:
                    crit += 1
            idle = mem.get("idle_n", 0)
            adj = mem.get("hire_adj", 0)
            if crit >= 2:
                adj += 1
            elif idle >= P["hire_fb_idle"]:
                adj -= 1
            mem["hire_adj"] = max(-4, min(3, adj))
            mem["idle_n"] = 0

    # atomic PLANT guard: never exceed seeds per crop
    plant_cnt = {}
    for i, a in enumerate(actions):
        if a and a[0] == "PLANT":
            c = a[1]
            plant_cnt[c] = plant_cnt.get(c, 0) + 1
            if plant_cnt[c] > seeds.get(c, 0):
                actions[i] = ["PASS"]
                if c == "MELON":
                    mem["melons"] -= 1

    # ------------------------------------------------------------ market orders
    shed_after = dict(shed)
    for i, a in enumerate(actions):
        if a[0] == "DROP" and units[i] in SHED_SET:
            for k, v in uitems[i].items():
                shed_after[k] = shed_after.get(k, 0) + v
        elif a[0] == "PICKUP" and units[i] in SHED_SET:
            k = a[1]
            shed_after[k] = max(0, shed_after.get(k, 0) - int(a[2]))
    sells = sellable_from(shed_after)
    # overflow guard at end of day: everything carried is dumped into the shed (cap 100)
    if hour == TPD - 1 and not last_day:
        carried_after = sum(sum(it.values()) for it in uitems)
        for i, a in enumerate(actions):
            if a[0] == "DROP" and units[i] in SHED_SET:
                carried_after -= sum(uitems[i].values())
        total_after = sum(shed_after.values()) - sum(sells.values()) + carried_after
        excess = total_after - 100
        if excess > 0:
            for item in ["FERTILIZER", "WHEAT", "EGG", "CARROT", "TOMATO", "STRAWBERRY", "MILK", "WOOL", "MELON"]:
                if excess <= 0:
                    break
                can = shed_after.get(item, 0) - sells.get(item, 0)
                k = min(can, excess)
                if k > 0:
                    sells[item] = sells.get(item, 0) + k
                    excess -= k
    # hold crashed premium goods (optional)
    if P["sell_hold_frac"] > 0 and day < DAYS - 2:
        for item in ("MILK", "WOOL", "STRAWBERRY", "TOMATO"):
            if item in sells and prices[item] < P["sell_hold_frac"] * BASE[item] and shed_after.get(item, 0) < 30:
                del sells[item]

    arb_prev = mem.pop("arb", 0) if mem.get("arb_step") == step - 1 else 0
    if arb_prev > 0:
        have_w = shed_after.get("WHEAT", 0) - sells.get("WHEAT", 0)
        k = min(arb_prev, max(0, have_w))
        if k > 0:
            sells["WHEAT"] = sells.get("WHEAT", 0) + k
    steep = []
    cheap = []
    for item in SELL_ORDER:
        n = sells.get(item, 0)
        if n > 0:
            (steep if item in ("WOOL", "MILK", "STRAWBERRY", "MELON", "TOMATO") else cheap).append(["SELL", item, n])
    hire_orders = []
    if hour <= 3 and hires_today < hire_target:
        hire_orders = [["HIRE"]] * (hire_target - hires_today)
    buys = []
    if land_buy:
        buys.append(["BUY_LAND"])
    for a in ("SHEEP", "COW", "GOOSE"):
        if buy_animals[a] > 0:
            buys.append(["BUY_ANIMAL", a, buy_animals[a]])
    if wheat_buy > 0:
        buys.append(["BUY_PRODUCT", "WHEAT", wheat_buy])
    for c in ("MELON", "STRAWBERRY", "TOMATO", "WHEAT", "CARROT"):
        if seed_buy[c] > 0:
            buys.append(["BUY_SEED", c, seed_buy[c]])
    # priority when over the 10-order cap: steep sells, hires, cheap sells, buys
    if len(steep) + len(hire_orders) + len(cheap) + len(buys) > 10:
        room_left = 10 - len(steep)
        h = hire_orders[:max(0, room_left)]
        room_left -= len(h)
        c = cheap[:max(0, room_left)]
        room_left -= len(c)
        b = buys[:max(0, room_left)]
        orders = steep + h + c + b
    else:
        orders = steep + cheap + hire_orders + buys
    if step == 0:
        orders = [["HIRE"], ["HIRE"], ["HIRE"], ["HIRE"], ["BUY_ANIMAL", "COW", 2], ["BUY_ANIMAL", "SHEEP", 3],
                  ["BUY_SEED", "MELON", 6], ["BUY_PRODUCT", "WHEAT", 4], ["BUY_SEED", "WHEAT", 10]]
    orders = orders[:10]
    # wheat tick arbitrage: shops consume after this step's orders at step % 4 == 0; buy last, sell next step
    if P["arb_n"] > 0 and step % 4 == 0 and day >= 8 and day <= DAYS - 3 and len(orders) < 10             and not any(o[0] == "SELL" and o[1] == "WHEAT" for o in orders):
        carried_now = sum(sum(it.values()) for it in uitems)
        room_shed = 100 - (sum(shed_after.values()) - sum(sells.values())) - (carried_now if hour == TPD - 1 else 0) - 15
        spare = money + 0.9 * est_sales - 1500.0
        n_arb = int(min(P["arb_n"], room_shed, spare // (wheat_price + 3)))
        if n_arb >= 5:
            orders.append(["BUY_PRODUCT", "WHEAT", n_arb])
            mem["arb"] = n_arb
            mem["arb_step"] = step
    return {"farmer": actions[0], "hands": actions[1:], "market": orders}


def _has(it, need, seeds):
    if need is None:
        return True
    if need == "WHEAT":
        return it.get("WHEAT", 0) > 0
    if need == "FERTILIZER":
        return it.get("FERTILIZER", 0) > 0
    if need.startswith("SEED:"):
        return seeds.get(need[5:], 0) > 0
    if need == "ANIMAL:COOP":
        return it.get("GOOSE", 0) > 0
    if need == "ANIMAL:PASTURE":
        return it.get("COW", 0) + it.get("SHEEP", 0) > 0
    return it.get(need, 0) > 0


def _has_future(it, need, seed_future):
    return _has(it, need, seed_future)


_AGENT = make_agent()


def agent(obs, config=None):
    return _AGENT(obs, config)
