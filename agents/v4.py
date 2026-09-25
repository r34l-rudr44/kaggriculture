"""Kaggriculture agent: task-assignment farm manager.

Each turn:
  1. Build a list of tile tasks (water, harvest, feed, care, plant, build, ...).
  2. Greedily match farmer + hands to tasks by priority minus walking distance.
  3. Issue market orders: sell with price floors, buy seeds/animals/wheat/land, hire.
"""
import math

N = 10
HALF = N // 2
TPD = 24
DAYS = 30
LAST_STEP = 718  # last step the interpreter processes

SHED_TILES = [(HALF - 1, HALF - 1), (HALF, HALF - 1), (HALF - 1, HALF), (HALF, HALF)]
SHED_SET = set(SHED_TILES)

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
LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]


def _shape(func, x, T=None):
    x = max(0.0, x)
    if func == "linear": return x
    if func == "sq": return x * x
    if func == "sqrt": return math.sqrt(x)
    if func == "log": return math.log(1.0 + x)
    if func == "log10": return math.log10(1.0 + x)
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


def quadrant_of(x, y):
    return ("N" if y < HALF else "S") + ("W" if x < HALF else "E")


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step_toward(pos, target):
    x, y = pos
    tx, ty = target
    if x < tx: return "EAST"
    if x > tx: return "WEST"
    if y < ty: return "SOUTH"
    if y > ty: return "NORTH"
    return "PASS"


def nearest_shed(pos):
    return min(SHED_TILES, key=lambda s: dist(pos, s))


def g(o, k, d=None):
    if isinstance(o, dict):
        return o.get(k, d)
    return getattr(o, k, d)


DEFAULT_PARAMS = {
    "melon_total": 18,        # max melons planted over the season
    "melon_last_day": 19,     # last day to plant melon (harvest at age 10)
    "melon_floor": 40,        # min melon sell price before the last days
    "premium_floor_frac": 0.35,
    "goose_care": False,      # geese fed every other day, no CARE (labor-lean)
    "cow_cap": 8,
    "sheep_cap": 6,
    "cow_last_day": 19,
    "sheep_last_day": 21,
    "goose_last_day": 23,
    "wheat_base_tiles": 2,
    "max_hands": 14,
    "max_hire_marginal": 400,
    "unload_at": 12,
    "melon_unload": 6,
    "guard_hour": 17,
    "shed_target": 88,
    "cash_reserve": 150,
    "fert_floor": 10,
    "land_last_day": 21,
    "land_reserve": 1200,
    "day0_geese": 0,
    "fertilize_wheat": True,
    "walk_factor": 2.0,
    "labor_cost": 45,
    "hire_feedback": False,
    "idle_hi": 0.18,
    "idle_lo": 0.06,
    "wheat_bias": 10,
    "land_free_tiles": 3,
}


def make_agent(params=None):
    P = dict(DEFAULT_PARAMS)
    if params:
        P.update(params)
    mem = {}

    def act(obs, config=None):
        try:
            return _act(obs, P, mem)
        except Exception:  # never crash on the ladder
            import traceback
            traceback.print_exc()
            return {"farmer": ["PASS"], "hands": [], "market": []}

    return act


def fib_costs(n):
    out, a, b = [], 1, 1
    for _ in range(n):
        out.append(a)
        a, b = b, a + b
    return out


def _act(obs, P, mem_all):
    me_id = g(obs, "player", 0)
    mem = mem_all.setdefault(me_id, {})
    farms = g(obs, "farms")
    me = farms[me_id]
    priv = g(obs, "private")
    market = g(obs, "market")
    town = g(obs, "town", {}) or {}
    day = g(obs, "day", 0)
    hour = g(obs, "hour", 0)
    step = g(obs, "step", day * TPD + hour)
    day, hour = step // TPD, step % TPD
    days_left = DAYS - day  # including today
    last_day = day == DAYS - 1

    tiles = me["tiles"]
    money = float(me["money"])
    shed = {k: int(v) for k, v in dict(priv["shed"]).items()}
    seeds = {k: int(v) for k, v in dict(priv["seeds"]).items()}
    invs = [dict(i) for i in priv["inventories"]]
    units = [tuple(me["farmer"])] + [tuple(h) for h in me["hands"]]
    while len(invs) < len(units):
        invs.append({})
    minv = {k: int(v) for k, v in dict(market["inventory"]).items()}
    prices = {k: int(v) for k, v in dict(market["prices"]).items()}
    shops = list(g(town, "unlocked_shops", []) or [])
    unlocked = list(me["unlocked_quadrants"])

    # ------------------------------------------------------------------ survey
    plants, structs, weeds, empties = [], [], [], []
    animal_count = {a: 0 for a in ANIMALS}
    crop_count = {c: 0 for c in CROPS}
    for y in range(N):
        for x in range(N):
            t = tiles[y][x]
            if t is None:
                empties.append((x, y))
            elif t == "LOCKED":
                continue
            elif isinstance(t, dict):
                k = t.get("kind")
                if k == "PLANT":
                    plants.append((x, y, t))
                    crop_count[t["crop"]] += 1
                elif k == "WEED":
                    weeds.append((x, y))
                else:
                    structs.append((x, y, t))
                    if t.get("animal"):
                        animal_count[t["animal"]] += 1

    held = {}
    for inv in invs:
        for k, v in inv.items():
            held[k] = held.get(k, 0) + int(v)
    stock = {a: shed.get(a, 0) + held.get(a, 0) for a in ANIMALS}
    empty_structs = {"COOP": [], "PASTURE": []}
    for (x, y, t) in structs:
        if not t.get("animal"):
            empty_structs[t["kind"]].append((x, y))

    # Town demand per day (shops consume every 4 turns -> 6x/day).
    demand = {p: 1.0 for p in PRODUCTS}
    demand["FERTILIZER"] = 0.0
    for sname in shops:
        prods = {
            "BAKERY": ["EGG", "WHEAT"], "PIZZA_SHOP": ["MILK", "TOMATO", "WHEAT"],
            "BRUNCH_SPOT": ["EGG", "WHEAT", "STRAWBERRY"], "YARN_STORE": ["WOOL"],
            "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"], "PET_CAFE": ["CARROT"],
            "SMOOTHIE_SHOP": ["STRAWBERRY", "MILK"],
            "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
        }.get(sname, [])
        for p in prods:
            demand[p] += 12.0 if len(prods) == 1 else 6.0

    fert_price = prices.get("FERTILIZER", 100)
    wheat_price = prices.get("WHEAT", 25)
    # Use fertilizer on wheat when its sale price is below ~2 wheat.
    fert_use = P["fertilize_wheat"] and fert_price < 1.8 * wheat_price and not last_day

    orders = []
    budget = money - P["cash_reserve"]

    # ---------------------------------------------------------------- hiring
    n_geese = animal_count["GOOSE"] + stock["GOOSE"]
    n_big = animal_count["COW"] + animal_count["SHEEP"] + stock["COW"] + stock["SHEEP"]
    if hour == 0:
        work = 0.0
        for (x, y, t) in plants:
            work += 1.3
        for (x, y, t) in structs:
            a = t.get("animal")
            if a == "GOOSE":
                work += 3.0 if P["goose_care"] else 1.9
            elif a:
                work += 3.3
            else:
                work += 1.0
        work += len(weeds) * 0.7 + len(empties) * 1.5
        work *= P["walk_factor"]  # walking overhead
        need_units = int(math.ceil(work / 23.0))
        if P["hire_feedback"] and "units_prev" in mem:
            # Feedback on yesterday: idle share and critical backlog.
            prev = mem["units_prev"]
            idle = mem.get("idle", 0) / max(1, mem.get("uturns", 1))
            crit = mem.get("crit_eod", 0)
            tgt = prev + (need_units - mem.get("formula_prev", need_units))
            if crit > 0:
                tgt += 1 + min(2, crit // 3)
            elif idle > P["idle_hi"]:
                tgt -= 2 if idle > P["idle_hi"] + 0.12 else 1
            elif idle < P["idle_lo"]:
                tgt += 1
            need_units = max(1, int(tgt))
        mem["formula_prev"] = int(math.ceil(work / 23.0))
        mem["idle"], mem["uturns"], mem["crit_eod"] = 0, 0, 0
        want = max(0, min(P["max_hands"], need_units - 1))
        costs = fib_costs(want)
        n, spent = 0, 0
        for c in costs:
            if c > P["max_hire_marginal"] or spent + c > max(60.0, budget * 0.35):
                break
            spent += c
            n += 1
        mem["hire_plan"] = (day, n)
        mem["units_prev"] = n + 1
        mem["hired_today"] = 0
        budget -= spent
    hp = mem.get("hire_plan", (-1, 0))
    if hp[0] == day and hour <= 2:
        remaining = hp[1] - int(me.get("hires_today", 0) if isinstance(me, dict) else 0)
        k = max(0, min(remaining, 8))
        for _ in range(k):
            orders.append(["HIRE"])
        if hour > 0:
            budget -= sum(fib_costs(int(me["hires_today"]) + k)[int(me["hires_today"]):])

    # ----------------------------------------------------------- tile roles
    plan = {}  # (x,y) -> ("PLANT", crop) | ("BUILD", kind)
    seed_need = {c: 0 for c in CROPS}
    animal_buy = {a: 0 for a in ANIMALS}

    cow_target = min(P["cow_cap"], 2 + int(demand["MILK"] / 1.5))
    sheep_target = min(P["sheep_cap"], 1 + int(demand["WOOL"] / 1.33))
    if prices.get("MILK", 160) < 110:
        cow_target = min(cow_target, animal_count["COW"] + stock["COW"])
    if prices.get("WOOL", 200) < 130:
        sheep_target = min(sheep_target, animal_count["SHEEP"] + stock["SHEEP"])
    cows_total = animal_count["COW"] + stock["COW"]
    sheep_total = animal_count["SHEEP"] + stock["SHEEP"]

    # Animals for already-built empty structures.
    free_coops = len(empty_structs["COOP"]) - stock["GOOSE"]
    free_past = len(empty_structs["PASTURE"]) - stock["COW"] - stock["SHEEP"]
    for _ in range(max(0, free_coops)):
        if day <= P["goose_last_day"] and budget >= ANIMALS["GOOSE"]["cost"]:
            animal_buy["GOOSE"] += 1
            budget -= ANIMALS["GOOSE"]["cost"]
    for _ in range(max(0, free_past)):
        if cows_total < cow_target and day <= P["cow_last_day"]:
            want = "COW"
        elif day <= P["sheep_last_day"]:
            want = "SHEEP"
        else:
            break
        if budget >= ANIMALS[want]["cost"]:
            animal_buy[want] += 1
            budget -= ANIMALS[want]["cost"]
            if want == "COW":
                cows_total += 1
            else:
                sheep_total += 1

    melons_planted = mem.get("melons_planted", 0)
    feed_per_day = (n_geese + animal_buy["GOOSE"]) * (1.0 if P["goose_care"] else 0.5) + n_big + animal_buy["COW"] + animal_buy["SHEEP"]
    wheat_target = int(math.ceil(feed_per_day * 1.1)) + P["wheat_base_tiles"]

    fert_stock = shed.get("FERTILIZER", 0) + held.get("FERTILIZER", 0)
    fert_price_eff = fert_price if fert_price > 15 else fert_price * 0.5
    milk_p = prices.get("MILK", 160)
    wool_p = prices.get("WOOL", 200)
    egg_p = prices.get("EGG", 50)
    carrot_p = prices.get("CARROT", 35)
    empties_sorted = sorted(empties, key=lambda p: (dist(p, nearest_shed(p)), p[1], p[0]))
    wheat_now = crop_count["WHEAT"]
    geese_planned = 0
    hours_left_today = TPD - hour
    for pos in empties_sorted:
        if hours_left_today < 3:
            break
        choice = None
        if wheat_now < wheat_target and days_left >= 5 and budget >= 10:
            choice = ("PLANT", "WHEAT")
            wheat_now += 1
        elif melons_planted + seed_need["MELON"] < P["melon_total"] and day <= P["melon_last_day"] \
                and budget >= CROPS["MELON"]["seed"] and not (day == 0 and geese_planned < P["day0_geese"]):
            choice = ("PLANT", "MELON")
        else:
            # Price-aware choice between animals and short crops.
            lam = P["labor_cost"]
            R = max(1, days_left)
            fe = fert_price_eff
            opts = []
            if cows_total < cow_target and day <= P["cow_last_day"] - 1 and budget >= ANIMALS["COW"]["cost"]:
                prod = max(0, R - 8) / R
                opts.append((prod * 1.5 * milk_p + fe * (R - 1) / R - wheat_price - 400.0 / R - 3.3 * lam, "COW"))
            if sheep_total < sheep_target and day <= P["sheep_last_day"] - 1 and budget >= ANIMALS["SHEEP"]["cost"]:
                prod = max(0, R - 6) / R
                opts.append((prod * 1.33 * wool_p + fe * (R - 1) / R - wheat_price - 500.0 / R - 3.3 * lam, "SHEEP"))
            if day <= P["goose_last_day"] - 1 and budget >= ANIMALS["GOOSE"]["cost"]:
                prod = max(0, R - 4) / R
                opts.append((prod * egg_p + fe * (R - 1) / R - 0.5 * wheat_price - 300.0 / R - 1.9 * lam, "GOOSE"))
            if R >= 5 and budget >= 10:
                y = 6 if fert_use else 4
                opts.append(((y * wheat_price * 0.95 - 10) / 4.0 - 1.3 * lam + P["wheat_bias"], "WHEAT"))
            if R >= 4 and budget >= 20:
                y = 4 if fert_use else 3
                opts.append(((y * carrot_p - 20) / 3.0 - 1.5 * lam, "CARROT"))
            if opts:
                opts.sort(key=lambda o: -o[0])
                best = opts[0][1]
                if best == "COW":
                    choice = ("BUILD", "PASTURE")
                    cows_total += 1
                    budget -= ANIMALS["COW"]["cost"]
                elif best == "SHEEP":
                    choice = ("BUILD", "PASTURE")
                    sheep_total += 1
                    budget -= ANIMALS["SHEEP"]["cost"]
                elif best == "GOOSE":
                    choice = ("BUILD", "COOP")
                    geese_planned += 1
                    budget -= ANIMALS["GOOSE"]["cost"]
                else:
                    choice = ("PLANT", best)
        if choice is None:
            if days_left >= 5 and budget >= 10:
                choice = ("PLANT", "WHEAT")
            elif days_left >= 4 and budget >= 20:
                choice = ("PLANT", "CARROT")
        if choice is None:
            continue
        if choice[0] == "PLANT":
            c = choice[1]
            seed_need[c] += 1
            budget -= CROPS[c]["seed"]
        plan[pos] = choice

    for c, n in seed_need.items():
        buy = n - seeds.get(c, 0)
        if buy > 0:
            orders.append(["BUY_SEED", c, buy])
    for a, n in animal_buy.items():
        if n > 0:
            orders.append(["BUY_ANIMAL", a, n])

    # ------------------------------------------------------------ tile tasks
    tasks = []  # (prio, (x,y), op, need_item)
    fert_holders = sum(1 for inv in invs if int(inv.get("FERTILIZER", 0)) > 0)

    def harvest_age(crop):
        if last_day or (day == DAYS - 2 and crop != "WHEAT"):
            return CROPS[crop]["first_yield_day"]
        return {"WHEAT": 4, "CARROT": 3, "MELON": 10}.get(crop, CROPS[crop]["first_yield_day"])

    fert_tasks = 0
    for (x, y, t) in plants:
        crop = t["crop"]
        cd = CROPS[crop]
        age = day - t["planted_day"]
        watered = t["watered_today"]
        ws = (cd["max_yield_day"] + 1) // 2
        in_window = (not cd["ongoing"]) and ws <= age <= cd["max_yield_day"]
        ready = (not cd["ongoing"]) and age >= harvest_age(crop) and t["yield_units"] > 0
        if cd["ongoing"]:
            if t["yield_units"] > 0 and age >= cd["first_yield_day"]:
                tasks.append((70, (x, y), ["HARVEST"], None))
            elif not watered:
                tasks.append((85, (x, y), ["WATER"], None))
            continue
        if crop in ("WHEAT", "CARROT") and fert_use and not watered and age == ws \
                and t["fertilized_until_day"] < day and hour < 18:
            fert_tasks += 1
            if fert_holders > 0:
                tasks.append((91, (x, y), ["FERTILIZE"], "FERTILIZER"))
                if hour < 14:
                    continue
        if not watered and (in_window or not ready):
            if in_window and t["yield_units"] < cd["max_yield"]:
                tasks.append((88, (x, y), ["WATER"], None))
            elif not ready:
                pr = 92 if t["consecutive_unwatered"] >= 1 else 30
                if last_day:
                    pr = 5
                tasks.append((pr, (x, y), ["WATER"], None))
            else:
                tasks.append((75, (x, y), ["HARVEST"], None))
        elif ready:
            tasks.append((75, (x, y), ["HARVEST"], None))

    fert_stock = shed.get("FERTILIZER", 0) + held.get("FERTILIZER", 0)
    fert_val = max(fert_price, 1.8 * wheat_price) if (fert_use and fert_stock < 15) else fert_price
    for (x, y, t) in structs:
        a = t.get("animal")
        if not a:
            continue
        ad = ANIMALS[a]
        lean = (a == "GOOSE" and not P["goose_care"])
        opts = []
        if not last_day and not t["fed_today"]:
            if t["consecutive_unfed"] >= 1:
                opts.append((100 + 6 * hour, ["FEED"], "WHEAT"))
            elif not lean:
                opts.append((90, ["FEED"], "WHEAT"))
        if not lean and not last_day and not t["cared_today"]:
            opts.append((84, ["CARE"], None))
        if t["yield_units"] > 0:
            pr = 40 + 12 * t["yield_units"]
            if t["yield_units"] >= ad["max_held"] - 1:
                pr = 95
            if last_day:
                pr = 95
            opts.append((pr, ["HARVEST"], None))
        if t.get("fertilizer_available") and fert_val >= 8:
            opts.append((20 + 0.7 * min(fert_val, 100), ["COLLECT_FERTILIZER"], None))
        if opts:
            opts.sort(key=lambda o: -o[0])
            pr, op, need = opts[0]
            tasks.append((pr, (x, y), op, need))

    for (x, y, t) in structs:
        if t.get("animal"):
            continue
        tasks.append((140, (x, y), ["PLACE_ANIMAL", t["kind"]], t["kind"]))

    for (x, y) in weeds:
        if days_left >= 4:
            tasks.append((25, (x, y), ["DIG"], None))

    for pos, (kind, what) in plan.items():
        if kind == "PLANT":
            tasks.append((66, pos, ["PLANT", what], "SEED:" + what))
        else:
            tasks.append((62, pos, ["BUILD_" + what], None))

    # ------------------------------------------------------------ assignment
    n_units = len(units)
    unit_items = [dict((k, int(v)) for k, v in invs[i].items()) for i in range(n_units)]
    seed_avail = dict(seeds)

    def unit_has(i, need):
        if need is None:
            return True
        if need == "NOWHEAT":
            return unit_items[i].get("WHEAT", 0) < 2
        if need.startswith("SEED:"):
            return seed_avail.get(need[5:], 0) > 0
        if need == "COOP":
            return unit_items[i].get("GOOSE", 0) > 0
        if need == "PASTURE":
            return unit_items[i].get("COW", 0) > 0 or unit_items[i].get("SHEEP", 0) > 0
        return unit_items[i].get(need, 0) > 0

    def consume(i, need, op):
        if need is None or need == "NOWHEAT":
            return
        if need.startswith("SEED:"):
            seed_avail[need[5:]] -= 1
        elif need == "COOP":
            unit_items[i]["GOOSE"] -= 1
        elif need == "PASTURE":
            if unit_items[i].get("COW", 0) > 0:
                unit_items[i]["COW"] -= 1
                op[1] = "COW"
            else:
                unit_items[i]["SHEEP"] -= 1
                op[1] = "SHEEP"
        else:
            unit_items[i][need] -= 1

    actions = [None] * n_units
    drop_items = set(PRODUCTS) - {"WHEAT"}

    def n_sellable(i):
        s = 0
        for k, v in unit_items[i].items():
            if k in drop_items:
                if k == "FERTILIZER" and fert_use:
                    v = max(0, v - 4)
                s += v
        return s

    # Pre-pass: units standing at the shed restock / unload.
    unfed_need = 0
    for (x, y, t) in structs:
        a = t.get("animal")
        if a and not t["fed_today"] and not last_day:
            lean = (a == "GOOSE" and not P["goose_care"])
            if not lean or t["consecutive_unfed"] >= 1:
                unfed_need += 1
    share_w = int(math.ceil(unfed_need / max(1, n_units))) + 2
    wheat_held = sum(min(it.get("WHEAT", 0), share_w) for it in unit_items)
    need_place = {"GOOSE": len(empty_structs["COOP"]), "PASTURE": len(empty_structs["PASTURE"])}
    for it in unit_items:
        need_place["GOOSE"] -= it.get("GOOSE", 0)
        need_place["PASTURE"] -= it.get("COW", 0) + it.get("SHEEP", 0)
    fert_need = fert_tasks - sum(it.get("FERTILIZER", 0) for it in unit_items)
    shed_left = dict(shed)
    # End-of-day overflow guard: everything carried is dumped into the shed
    # (cap 100) at day end and the excess is destroyed, so unload early.
    must_unload = set()
    if hour >= P["guard_hour"] and not last_day:
        projected = sum(shed.values()) + sum(sum(it.values()) for it in unit_items)
        cands = sorted(range(n_units), key=lambda i: (dist(units[i], nearest_shed(units[i])) - n_sellable(i) * 0.5))
        for i in cands:
            if projected <= P["shed_target"]:
                break
            ns = n_sellable(i)
            if ns <= 0:
                continue
            if dist(units[i], nearest_shed(units[i])) + hour >= TPD:
                continue
            must_unload.add(i)
            projected -= ns
    for i, pos in enumerate(units):
        if pos not in SHED_SET:
            continue
        ns = n_sellable(i)
        if ns > 0 and (ns >= 2 or last_day or hour >= TPD - 4 or i in must_unload):
            actions[i] = ["DROP"]
            continue
        if shed_left.get("GOOSE", 0) > 0 and need_place["GOOSE"] > 0 and unit_items[i].get("GOOSE", 0) == 0:
            k = min(shed_left["GOOSE"], need_place["GOOSE"], 2)
            actions[i] = ["PICKUP", "GOOSE", k]
            shed_left["GOOSE"] -= k
            need_place["GOOSE"] -= k
            continue
        picked = False
        for a in ("COW", "SHEEP"):
            if shed_left.get(a, 0) > 0 and need_place["PASTURE"] > 0 \
                    and unit_items[i].get("COW", 0) + unit_items[i].get("SHEEP", 0) == 0:
                actions[i] = ["PICKUP", a, 1]
                shed_left[a] -= 1
                need_place["PASTURE"] -= 1
                picked = True
                break
        if picked:
            continue
        deficit = unfed_need - wheat_held
        if deficit > 0 and shed_left.get("WHEAT", 0) > 0 and unit_items[i].get("WHEAT", 0) < 2:
            k = min(shed_left["WHEAT"], max(5, share_w))
            actions[i] = ["PICKUP", "WHEAT", k]
            shed_left["WHEAT"] -= k
            wheat_held += k
            continue
        if fert_use and fert_need > 0 and shed_left.get("FERTILIZER", 0) > 0 and unit_items[i].get("FERTILIZER", 0) == 0:
            k = min(shed_left["FERTILIZER"], max(3, fert_need // max(1, n_units) + 1))
            actions[i] = ["PICKUP", "FERTILIZER", k]
            shed_left["FERTILIZER"] -= k
            fert_need -= k
            continue

    # Greedy global assignment.
    pairs = []
    deficit = unfed_need - wheat_held
    if deficit > 0 and shed_left.get("WHEAT", 0) > 0 and not last_day:
        for k in range(min(n_units, int(math.ceil(deficit / max(1, share_w))))):
            tasks.append((96 + 3 * hour, SHED_TILES[k % 4], ["PICKUP", "WHEAT", max(5, share_w)], "NOWHEAT"))
    for i in must_unload:
        if actions[i] is None:
            actions[i] = [step_toward(units[i], nearest_shed(units[i]))]
    for i, pos in enumerate(units):
        if actions[i] is not None:
            continue
        for ti, (pr, tpos, op, need) in enumerate(tasks):
            d = dist(pos, tpos)
            if last_day and step + d + 1 + dist(tpos, nearest_shed(tpos)) + 1 > LAST_STEP:
                continue
            pairs.append((pr - 6.0 * d, d, i, ti))
    pairs.sort(key=lambda z: (-z[0], z[1], z[2], z[3]))
    taken_units, taken_tasks = set(), set()
    for score, d, i, ti in pairs:
        if i in taken_units or ti in taken_tasks:
            continue
        pr, tpos, op, need = tasks[ti]
        if not unit_has(i, need):
            continue
        if d > 0 and (n_sellable(i) >= P["unload_at"] or unit_items[i].get("MELON", 0) >= P["melon_unload"]):
            continue
        taken_units.add(i)
        taken_tasks.add(ti)
        if d == 0:
            op = list(op)
            if op[0] == "PLACE_ANIMAL":
                op = ["PLACE", "GOOSE" if op[1] == "COOP" else "COW"]
            consume(i, need, op)
            actions[i] = op
        else:
            if need is not None and need.startswith("SEED:"):
                seed_avail[need[5:]] -= 1  # reserve
            actions[i] = [step_toward(units[i], tpos)]

    # Remaining units: unload, restock, or idle.
    unclaimed_needs = set(tasks[ti][3] for ti in range(len(tasks)) if ti not in taken_tasks)
    for i, pos in enumerate(units):
        if actions[i] is not None:
            continue
        ns = n_sellable(i)
        go_shed = False
        if ns >= P["unload_at"] or (last_day and ns > 0) or unit_items[i].get("MELON", 0) >= P["melon_unload"]:
            go_shed = True
        elif "WHEAT" in unclaimed_needs and shed.get("WHEAT", 0) > 0 and unit_items[i].get("WHEAT", 0) == 0:
            go_shed = True
        elif "FERTILIZER" in unclaimed_needs and shed.get("FERTILIZER", 0) > 0 and unit_items[i].get("FERTILIZER", 0) == 0:
            go_shed = True
        elif (need_place["GOOSE"] > 0 and shed.get("GOOSE", 0) > 0) or \
                (need_place["PASTURE"] > 0 and (shed.get("COW", 0) + shed.get("SHEEP", 0)) > 0):
            go_shed = True
        elif ns > 0 and step >= LAST_STEP - 12:
            go_shed = True
        if go_shed:
            if pos in SHED_SET:
                actions[i] = ["DROP"] if ns > 0 else ["PASS"]
            else:
                actions[i] = [step_toward(pos, nearest_shed(pos))]
        else:
            actions[i] = ["PASS"]

    for i, a in enumerate(actions):
        if a and a[0] == "PLANT" and a[1] == "MELON":
            mem["melons_planted"] = mem.get("melons_planted", 0) + 1
    if hour >= 2:
        mem["uturns"] = mem.get("uturns", 0) + n_units
        mem["idle"] = mem.get("idle", 0) + sum(1 for a in actions if a and a[0] == "PASS")
    if hour == TPD - 1:
        crit = 0
        for (x, y, t) in structs:
            if t.get("animal") and not t["fed_today"] and t["consecutive_unfed"] >= 1:
                crit += 1
            elif t.get("animal") and t["yield_units"] >= ANIMALS[t["animal"]]["max_held"]:
                crit += 1
        for (x, y, t) in plants:
            if not t["watered_today"] and t["consecutive_unwatered"] >= 1:
                crit += 1
        mem["crit_eod"] = crit

    # ------------------------------------------------------------ selling
    shed_after = dict(shed)
    for i, a in enumerate(actions):
        if a and a[0] == "DROP":
            for k, v in invs[i].items():
                shed_after[k] = shed_after.get(k, 0) + int(v)
        if a and a[0] == "PICKUP":
            shed_after[a[1]] = shed_after.get(a[1], 0) - int(a[2])

    sell_orders = []
    endgame = day >= DAYS - 2
    wheat_reserve = 0 if last_day else int(math.ceil(feed_per_day * 1.3)) + 3
    for item in PRODUCTS:
        have = shed_after.get(item, 0)
        if item == "WHEAT":
            have -= wheat_reserve
        if item == "FERTILIZER" and fert_use:
            have -= 12
        if have <= 0:
            continue
        base = MARKET_PARAMS[item]["base"]
        if last_day:
            floor = 1
        elif item == "MELON":
            floor = P["melon_floor"] if (day <= 12 and not endgame) else 1
        elif item in ("STRAWBERRY", "MILK", "WOOL"):
            floor = int(base * P["premium_floor_frac"]) if not endgame else 2
        elif item == "FERTILIZER":
            floor = P["fert_floor"] if (not endgame and have < 20) else 1
        elif item == "WHEAT":
            floor = 12
        else:
            floor = 5
        inv = minv[item]
        n = 0
        while n < have and market_price(item, inv) >= floor:
            inv += 1 if market_price(item, inv) > 1 else 0
            n += 1
        if n > 0:
            sell_orders.append(["SELL", item, n])
    hire_orders = [o for o in orders if o[0] == "HIRE"]
    other = [o for o in orders if o[0] != "HIRE"]
    orders = hire_orders + sell_orders + other

    # Wheat top-up for feeding.
    wheat_total = shed_after.get("WHEAT", 0) + sum(it.get("WHEAT", 0) for it in unit_items)
    need_w = int(math.ceil(feed_per_day)) + 2
    if not last_day and wheat_total < need_w and wheat_price <= 70:
        orders.append(["BUY_PRODUCT", "WHEAT", need_w - wheat_total])

    # Land.
    n_extra = len(unlocked) - 1
    if n_extra < 3 and day <= P["land_last_day"] and len(empties) + len(weeds) <= P["land_free_tiles"]:
        price = LAND_PRICES[n_extra]
        if money - price > P["land_reserve"]:
            orders.append(["BUY_LAND"])

    orders = orders[:10]
    return {"farmer": actions[0], "hands": actions[1:], "market": orders}


_AGENT = make_agent()


def agent(obs, config=None):
    return _AGENT(obs, config)
