"""Kaggriculture v5 "calendar planner" agent (standard library only, single file).

Architecture (one pass per turn, all derived from the observation + small per-player memory):
  (a) layout planner   : fixed NW opening (pastures on (4,4),(3,4),(4,3),(3,3),(4,2); 6+4 melons; 10 wheat),
                         animal ring = 6 tiles nearest each quadrant's shed tile, crops assigned far-first.
  (b) calendars        : per tile, today's minimal op list (WATER / FERTILIZE / HARVEST / DIG / PLANT /
                         FEED / CARE / COLLECT_FERTILIZER / BUILD / PLACE), each valued as coins lost if
                         skipped today (care bank incl. pre-first-production slack and endgame cut-off,
                         production-day water+fertilizer, survival waters, forced harvests).
  (c) labor planner    : hire floor 4,4,6..12 + task estimate; steady-state labor load gate on new
                         plantings with an adaptive capacity (idle turns vs unfinished must-tasks);
                         intra-day triage drops the lowest value-per-op tasks when labor is short.
  (d) router           : greedy unit -> tile-burst matching, score = compressed value + neighbour
                         bonus - lambda*travel - sector/revisit penalties; burst rule, committed
                         targets, shed detours for wheat/fertilizer/animals, morning fertilizer pickup.
  (e) economic planner : demand pools (shops + expected future shops + deficit - own and rival
                         pipelines) size strawberries / tomatoes / herd; species care modes by price;
                         land bought when cash covers price + a fill reserve.
  (f) market           : steep goods first, all sells before hires when cash is short, no wheat or
                         fertilizer churn, just-in-time seeds, overflow guard from hour 19, surplus
                         wheat drops, liquidation by step 718.
"""
import math
import collections

N = 10
HALF = 5
TPD = 24
LAST_STEP = 718
END_DAY = 29           # day 29 has no end-of-day processing
LAST_PROD_DAY = 28     # last end-of-day production that can still be sold

SHED_TILES = ((4, 4), (5, 4), (4, 5), (5, 5))
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
MP = {
    "WHEAT":      {"base":  25, "T": 400, "bf": "sqrt",  "bt": 0.80, "af": "log",    "at": 0.20},
    "CARROT":     {"base":  35, "T": 450, "bf": "hinge", "bt": 1.00, "af": "sqrt",   "at": 0.70},
    "TOMATO":     {"base":  60, "T": 200, "bf": "hinge", "bt": 0.40, "af": "sqrt",   "at": 0.60},
    "STRAWBERRY": {"base": 120, "T": 100, "bf": "sqrt",  "bt": 0.70, "af": "linear", "at": 1.60},
    "MELON":      {"base": 250, "T": 300, "bf": "log",   "bt": 0.20, "af": "sq",     "at": 3.60},
    "EGG":        {"base":  50, "T": 332, "bf": "hinge", "bt": 0.40, "af": "log",    "at": 0.20},
    "MILK":       {"base": 160, "T": 122, "bf": "sqrt",  "bt": 0.60, "af": "linear", "at": 1.60},
    "WOOL":       {"base": 200, "T": 105, "bf": "log",   "bt": 0.20, "af": "sq",     "at": 3.20},
    "FERTILIZER": {"base": 100, "T": 200, "bf": "linear", "bt": 0.40, "af": "linear", "at": 0.40},
}
I0 = 10000
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
EXP_NEW = {p: 0.0 for p in PRODUCTS}
for _s, _ps in SHOPS.items():
    for _p in _ps:
        EXP_NEW[_p] += (12.0 if len(_ps) == 1 else 6.0) / len(SHOPS)
LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]
PRODUCT_OF = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
STRUCT_OF = {"GOOSE": "COOP", "COW": "PASTURE", "SHEEP": "PASTURE"}
SELLABLE = ("WOOL", "MILK", "STRAWBERRY", "MELON", "TOMATO", "EGG", "CARROT", "FERTILIZER", "WHEAT")
STEEP_ORDER = ["WOOL", "MILK", "STRAWBERRY", "MELON", "TOMATO", "EGG", "CARROT", "FERTILIZER", "WHEAT"]
FIB = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597]


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


def mprice(item, inv):
    p = MP[item]
    base, T = p["base"], p["T"]
    if inv < I0:
        f = p["bf"]
        price = base + p["bt"] * base / _shape(f, T, T) * _shape(f, I0 - inv, T)
    else:
        f = p["af"]
        price = base - p["at"] * base / _shape(f, T, T) * _shape(f, inv - I0, T)
    return max(1, int(round(price)))


def quad_of(x, y):
    return ("N" if y < HALF else "S") + ("W" if x < HALF else "E")


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


SHED_D = {}
NEAR_SHED = {}
for _x in range(N):
    for _y in range(N):
        _best = min(SHED_TILES, key=lambda s: (dist((_x, _y), s), s))
        NEAR_SHED[(_x, _y)] = _best
        SHED_D[(_x, _y)] = dist((_x, _y), _best)


ANGLE = {(_x, _y): math.atan2(_y - 4.5, _x - 4.5) for _x in range(N) for _y in range(N)}


def _sectors(C, tasks):
    """Angular sectors around the shed with equal workload; one per unit (soft zones for routing)."""
    M = C.M
    n = len(C.units)
    key = (C.day, n)
    if M.get("sec_key") == key and M.get("sec") is not None:
        return M["sec"]
    items = sorted((ANGLE[T.pos], T.nops + 1.5) for T in tasks)
    W = sum(w for a, w in items)
    bounds = []
    acc = 0.0
    k = 1
    for a, w in items:
        acc += w
        while k < n and acc >= W * k / n:
            bounds.append(a)
            k += 1
    while len(bounds) < n - 1:
        bounds.append(math.pi)
    # sector mid angles
    edges = [-math.pi] + bounds + [math.pi]
    mids = [(edges[j] + edges[j + 1]) / 2.0 for j in range(n)]
    # pair units (sorted by angle of position) with sectors (sorted by mid angle)
    uang = sorted(range(n), key=lambda i: (ANGLE[C.units[i]], i))
    usec = [0] * n
    for rank, i in enumerate(uang):
        usec[i] = rank
    M["sec_key"] = key
    M["sec"] = (bounds, usec)
    return M["sec"]


def _sec_of(bounds, pos):
    a = ANGLE[pos]
    lo = 0
    for b in bounds:
        if a >= b:
            lo += 1
        else:
            break
    return lo


def mirror(p, q):
    x, y = p
    if q[1] == "E":
        x = N - 1 - x
    if q[0] == "S":
        y = N - 1 - y
    return (x, y)


# Animal ring: NW-form list, mirrored into the other quadrants.
RING_BASE = [(4, 4), (3, 4), (4, 3), (3, 3), (4, 2), (2, 4), (2, 3), (3, 2), (1, 4), (4, 1)]
# NW opening layout (as played by several top-10 teams).
NW_ANIMALS = [(4, 4), (3, 4), (4, 3), (3, 3), (4, 2)]
NW_MELON0 = [(4, 1), (3, 2), (2, 3), (1, 4), (2, 4), (4, 0)]
NW_MELON1 = [(3, 1), (2, 2), (1, 3), (0, 4)]
NW_WHEAT0 = [(3, 0), (2, 1), (1, 2), (0, 3), (2, 0), (1, 1), (0, 2), (1, 0), (0, 1), (0, 0)]


def step_toward(pos, target):
    x, y = pos
    tx, ty = target
    dx, dy = tx - x, ty - y
    if dx == 0 and dy == 0:
        return "PASS"
    if abs(dx) >= abs(dy):
        return "EAST" if dx > 0 else "WEST"
    return "SOUTH" if dy > 0 else "NORTH"


def _g(o, k, d=None):
    if o is None:
        return d
    if isinstance(o, dict):
        return o.get(k, d)
    return getattr(o, k, d)


def prod_day(placed, fyd, iv, d):
    """True if an animal/ongoing crop placed on `placed` produces at the end of day d."""
    dsf = d + 1 - placed - fyd
    return dsf >= 0 and dsf % iv == 0


def next_prod_after(placed, fyd, iv, d):
    """First production day strictly after day d (animals)."""
    D = d + 1
    dsf = D + 1 - placed - fyd
    if dsf < 0:
        return placed + fyd - 1
    r = dsf % iv
    return D if r == 0 else D + (iv - r)


def crop_prod_days(crop, planted):
    cd = CROPS[crop]
    out = []
    iv = cd["interval"]
    fyd = cd["first_yield_day"]
    for k in range(cd["max_yield"]):
        out.append(planted + fyd - 1 + k * iv)
    return out


DEFAULTS = {
    # ---- router (worker assignment)
    "lam": 40.0,              # coins per step of travel (linear scoring)
    "score_mode": "linear",   # "linear": value - lam*travel ; "density": value / (travel + ops + k)
    "dens_k": 1.0,
    "dens_spen": 0.2,
    "stick_frac": 0.3,
    "stick": 25.0,            # bonus for keeping the previous step's target
    "commit": True,           # units keep their walking target (processed before other pairs)
    "urgency": 1.5,           # must-task value multiplier growth over the day
    "burst_min": 3.0,         # keep working the current tile while its doable value >= this
    "vcap": 80.0,             # value compression cap for routing (0 = off)
    "vcap_grow": 2.0,         # compression cap grows over the day (value matters more late)
    "place_bonus": 120.0,     # routing priority for placing waiting animals
    "nb_w": 0.25,             # weight of neighbouring task values (chaining)
    "look_w": 0.0,            # weight of the best follow-up task (2-step look-ahead)
    "sec_pen": 30.0,          # soft penalty for tasks outside the unit's angular sector
    "min_task_val": 4.0,      # tasks worth less are only done when passing by
    "revisit_pen": 45.0,      # penalty for a partial visit (items missing for some ops)
    "triage": True,           # skip lowest value-per-op tasks when labor cannot cover today's work
    "triage_prod": 0.5,
    "morning_fert": True,     # units at the shed in the first hours pick up a share of today's fertilizer
    "morning_fert_hour": 2,
    "morning_wheat": False,   # units at the shed in the first hours pick up a share of today's feed wheat
    "proactive_pick": False,  # at the shed, pick up the wheat/fertilizer the unit's sector needs
    "pick_cap": 10,
    "wheat_pick": 8,
    "wheat_share_min": 4,
    "fert_pick": 8,
    # ---- drops / cash flow
    "starved_drop": 0.30,     # extra drop value (fraction of price) while cash-starved
    "starved_cash": 200,
    "starved_bonus": 60.0,
    "carry_heavy": 14,
    "urg_premium": 0.12,      # drop urgency (fraction of price per unit) for wool/milk/strawberries
    "shed_drop_val": 40.0,
    "shed_drop_items": 4,
    "early_cash_day": 10,
    # ---- labor planner
    "cap_adapt": True,        # adapt the capacity estimate to yesterday's idle turns / unfinished must-tasks
    "cap_step": 0.05,
    "cap_idle_hi": 0.07,
    "cap_lm_hi": 8,
    "cap_lm_lo": 3,
    "cap_min": 0.8,
    "cap_max": 1.5,
    "load_animal": 3.6,       # steady-state ops/day of a fully cared animal
    "load_animal_maint": 2.0,
    "load_crop": {"WHEAT": 2.4, "CARROT": 2.1, "STRAWBERRY": 0.95, "TOMATO": 1.2, "MELON": 0.9},
    "prod_frac": 0.52,        # productive fraction of unit-turns (rest: moves/pickups)
    "load_max_lo": 1.0,       # wheat/carrot plantings allowed while load < capacity * this
    "load_max_hi": 1.15,      # strawberry/tomato/melon plantings allowed while load < capacity * this
    "hire_floor": [4, 4, 6, 6, 6, 6, 8, 9, 9, 10, 11, 12],
    "max_hires": 12,
    "max_hires_peak": 12,
    "peak_days": [9, 14],
    "hire_end": [11, 10, 9],  # hire floor on days 27, 28, 29
    "min_hires_d0": 4,
    "hire_walk": 1.35,        # walking steps per tile visit (labor estimate)
    "hire_eff": 0.92,         # usable fraction of unit-turns
    "hire_value": 26.0,       # coins per unit-turn used to cap marginal hire cost
    # ---- economic planner
    "opening": "fish",        # "fish" (2 cows 3 sheep 6+4 melons) or "tfc" (3 cows 2 sheep 7 melons)
    "melon_total": 10,
    "melon_bonus": 60.0,      # routing priority for ripe melons (race the rival to the market)
    "melon2_price": 235,      # extra melons after D1 only if the price is that high
    "melon2_max": 4,
    "melon_last_day": 17,
    "straw_last_day": 13,
    "straw_late_day": 15,     # allow 3-production plants until this day if room is large
    "straw_min": 10,
    "straw_max": 46,
    "straw_share": 0.55,      # share of the strawberry demand pool we try to fill
    "straw_slack": 40.0,
    "opp_straw_assume": 0,
    "future_w": 0.7,          # weight of expected (not yet unlocked) shops in demand pools
    "tom_first_day": 7,
    "tom_last_day": 18,
    "tom_min": 0,
    "tom_max": 20,
    "tom_share": 0.55,
    "tom_slack": 60.0,
    "animal_buy_start": 6,
    "animal_last_day": 20,
    "animal_max": 24,
    "animal_share": 0.6,
    "goose_max": 30,          # cap on geese (labor-heavy, low value per op)
    "wool_slack": 30.0,
    "milk_slack": 25.0,
    "egg_slack": 80.0,
    "slots_per_quad": 6,
    "land_first_day": 4,
    "land_last_day": 13,
    "land_reserve": 0,
    "land_fill": [1200, 1500, 2500],   # cash to keep after buying land (to fill it)
    "keep_for_straw": False,
    "far_first": True,        # assign crops to free tiles far-first (strawberries outer, wheat inner)
    "cash_reserve": 0,
    "full_frac": 0.30,        # FULL care while product price >= frac * base
    "goose_full": 0,          # if > 0: geese get daily FEED+CARE only when eggs sell at least this
    "maint_min": 4,           # keep feeding (maintenance) while product or fert price >= this
    "wheat_fert_ratio": 1.6,  # fertilize wheat when fert price < ratio * wheat price
    "fert_keep_days": 3,
    "fert_buy_max": 15,
    "fert_wheat_buf": 0.5,    # keep this many fertilizer per wheat tile when it is cheap enough for wheat
    "wheat_reserve_days": 1.2,
    "early_wheat_harvest": True,
    "ongo_harv_min": 2,       # strawberries/tomatoes: harvest during watering visits once yield >= this
    "ongo_harv_frac": 0.15,
    # ---- market
    "sell_floor": {"WOOL": 0.22, "MILK": 0.22, "STRAWBERRY": 0.22, "MELON": 0.35, "TOMATO": 0.25,
                   "EGG": 0.35, "CARROT": 0.25, "FERTILIZER": 0.0, "WHEAT": 0.6},
    "drop_carry_value": 260.0,
    "guard_hour": 19,         # overflow guard starts selling shed goods from this hour
    "guard_room": 0.6,
    "risk_hour": 12,
    "risk_rate": 0.5,
    "risk_item_val": 8.0,     # drop value per carried item at risk of end-of-day overflow
    "wheat_drop_min": 4,
    "proj_floor": False,      # sell floors from projected end-of-season prices
    "proj_frac": 0.85,
    "proj_cap": 0.9,
}


class Ctx(object):
    pass


class Task(object):
    __slots__ = ("pos", "ops", "must", "nops", "tag", "bonus")

    def __init__(self, pos, tag=""):
        self.pos = pos
        self.ops = []      # [action(list), need(str|None), value(float)]
        self.must = False
        self.nops = 0
        self.tag = tag
        self.bonus = 0.0   # uncompressed routing priority

    def add(self, action, need, value):
        self.ops.append((action, need, value))
        self.nops += 1

    def value_all(self):
        return sum(o[2] for o in self.ops)

    def needs(self):
        s = []
        for o in self.ops:
            if o[1] in ("W", "F", "P", "C") and o[1] not in s:
                s.append(o[1])
        return s


def has_need(inv, need):
    if need is None or need.startswith("S:"):
        return True
    if need == "W":
        return inv.get("WHEAT", 0) > 0
    if need == "F":
        return inv.get("FERTILIZER", 0) > 0
    if need == "P":
        return inv.get("COW", 0) > 0 or inv.get("SHEEP", 0) > 0
    if need == "C":
        return inv.get("GOOSE", 0) > 0
    return True


# --------------------------------------------------------------------------------------------
def make_agent(params=None):
    P = dict(DEFAULTS)
    if params:
        P.update(params)
    MEM = {}

    def act(obs, config=None):
        try:
            return _act(obs, P, MEM)
        except Exception:
            try:
                import traceback
                if P.get("debug"):
                    traceback.print_exc()
            except Exception:
                pass
            return _safe_fallback(obs)

    return act


def _safe_fallback(obs):
    """Emergency action if planning raised: keep units idle but still sell what is in the shed."""
    try:
        pid = int(_g(obs, "player", 0) or 0)
        farm = _g(obs, "farms")[pid]
        n_hands = len(_g(farm, "hands", []) or [])
        shed = dict(_g(_g(obs, "private", {}), "shed", {}) or {})
        step = int(_g(obs, "step", 0) or 0)
        orders = []
        for item in STEEP_ORDER:
            q = int(shed.get(item, 0) or 0)
            if item == "WHEAT" and step < LAST_STEP - 30:
                q -= 30
            if q > 0:
                orders.append(["SELL", item, q])
        return {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": orders[:10]}
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}


# --------------------------------------------------------------------------------------------
def _parse(obs, P, MEM):
    C = Ctx()
    C.P = P
    pid = int(_g(obs, "player", 0) or 0)
    C.pid = pid
    M = MEM.setdefault(pid, {})
    C.M = M
    step = int(_g(obs, "step", 0) or 0)
    C.step = step
    C.day, C.hour = divmod(step, TPD)
    farms = _g(obs, "farms")
    farm = farms[pid]
    C.farm = farm
    C.ofarm = farms[1 - pid] if len(farms) > 1 else None
    priv = _g(obs, "private") or {}
    C.money = float(_g(farm, "money", 0))
    C.tiles = _g(farm, "tiles")
    C.shed = {k: int(v) for k, v in dict(_g(priv, "shed", {}) or {}).items()}
    C.seeds = {k: int(v) for k, v in dict(_g(priv, "seeds", {}) or {}).items()}
    units = [tuple(_g(farm, "farmer"))] + [tuple(h) for h in (_g(farm, "hands", []) or [])]
    C.units = units
    invs_raw = list(_g(priv, "inventories", []) or [])
    invs = []
    for i in range(len(units)):
        if i < len(invs_raw) and invs_raw[i]:
            invs.append({k: int(v) for k, v in dict(invs_raw[i]).items() if int(v) > 0})
        else:
            invs.append({})
    C.invs = invs
    market = _g(obs, "market", {}) or {}
    C.minv = {k: int(v) for k, v in dict(_g(market, "inventory", {}) or {}).items()}
    C.prices = {k: int(v) for k, v in dict(_g(market, "prices", {}) or {}).items()}
    for p in PRODUCTS:
        C.minv.setdefault(p, I0)
        C.prices.setdefault(p, MP[p]["base"])
    town = _g(obs, "town", {}) or {}
    C.shops = list(_g(town, "unlocked_shops", []) or [])
    C.unlocked = list(_g(farm, "unlocked_quadrants", ["NW"]) or ["NW"])
    C.hires_today = int(_g(farm, "hires_today", 0) or 0)
    if M.get("day") != C.day:
        M["day"] = C.day
        M["tgt"] = {}
        M["prev_actions"] = None
    return C


def _survey(C):
    C.free = []
    C.weeds = []
    C.plants = []
    C.animals = []
    C.empty_structs = []
    C.crop_count = {c: 0 for c in CROPS}
    C.animal_count = {a: 0 for a in ANIMALS}
    for y in range(N):
        row = C.tiles[y]
        for x in range(N):
            t = row[x]
            if t is None:
                C.free.append((x, y))
            elif t == "LOCKED":
                continue
            elif isinstance(t, dict) or hasattr(t, "get"):
                k = t.get("kind")
                if k == "PLANT":
                    C.plants.append(((x, y), t))
                    C.crop_count[t["crop"]] += 1
                elif k == "WEED":
                    C.weeds.append((x, y))
                elif t.get("animal"):
                    C.animals.append(((x, y), t))
                    C.animal_count[t["animal"]] += 1
                else:
                    C.empty_structs.append(((x, y), k))
    held = {}
    for inv in C.invs:
        for k, v in inv.items():
            held[k] = held.get(k, 0) + v
    C.held = held
    C.waiting = {a: C.shed.get(a, 0) + held.get(a, 0) for a in ANIMALS}
    # rival
    C.opp_plants = []
    C.opp_animals = []
    if C.ofarm is not None:
        ot = _g(C.ofarm, "tiles")
        for y in range(N):
            for x in range(N):
                t = ot[y][x]
                if isinstance(t, dict) or (t is not None and t != "LOCKED" and hasattr(t, "get")):
                    k = t.get("kind")
                    if k == "PLANT":
                        C.opp_plants.append(t)
                    elif t.get("animal"):
                        C.opp_animals.append(t)
    # animal slots for unlocked quadrants
    slots = []
    for q in ["NW", "NE", "SW", "SE"]:
        if q not in C.unlocked:
            continue
        if q == "NW":
            slots.extend(NW_ANIMALS)
        else:
            slots.extend(mirror(p, q) for p in RING_BASE[:C.P["slots_per_quad"]])
    C.slots = slots
    C.slot_set = set(slots)


# ------------------------------------------------------------------ economics / demand pools
def _shop_rates(shops):
    r = {p: 0.0 for p in PRODUCTS}
    for s in shops:
        ps = SHOPS.get(s, [])
        m = 12.0 if len(ps) == 1 else 6.0
        for p in ps:
            r[p] += m
    return r


def _demand_rem(C, product, from_day=None):
    d0 = C.day if from_day is None else from_day
    n_now = len(C.shops)
    rate = C.rates[product]
    tot = 0.0
    for k in range(d0, END_DAY + 1):
        nk = min(8, k // 3)
        extra = max(0, nk - n_now)
        tot += 1.0 + rate + extra * EXP_NEW[product] * C.P["future_w"]
    return tot


def _pipeline(tile_list, day, assume_full=True):
    out = {p: 0.0 for p in PRODUCTS}
    for t in tile_list:
        if t.get("kind") == "PLANT":
            crop = t["crop"]
            cd = CROPS[crop]
            if cd["ongoing"]:
                held = t.get("yield_units", 0)
                n = sum(1 for d in crop_prod_days(crop, t["planted_day"]) if day <= d <= LAST_PROD_DAY)
                out[crop] += held + n * (2 if assume_full else 1)
            else:
                age = day - t["planted_day"]
                if crop == "MELON":
                    out[crop] += 6 if age <= 10 else t.get("yield_units", 0)
                elif crop == "WHEAT":
                    out[crop] += 5
                else:
                    out[crop] += 4
        elif t.get("animal"):
            a = t["animal"]
            ad = ANIMALS[a]
            prod = ad["product"]
            held = t.get("yield_units", 0)
            placed = t["placed_day"]
            first = placed + ad["first_yield_day"] - 1
            tot = held
            d = first
            while d <= LAST_PROD_DAY:
                if d >= day:
                    if d == first:
                        tot += ad["max_held"] if assume_full else 1 + t.get("pending_care_bonus", 0)
                    else:
                        tot += (1 + ad["interval"]) if assume_full else 1
                d += ad["interval"]
            out[prod] += tot
    return out


def _new_animal_output(a, day):
    ad = ANIMALS[a]
    first = day + ad["first_yield_day"] - 1
    tot = 0
    d = first
    while d <= LAST_PROD_DAY:
        tot += ad["max_held"] if d == first else 1 + ad["interval"]
        d += ad["interval"]
    return tot


def _new_plant_output(crop, day):
    n = sum(1 for d in crop_prod_days(crop, day) if d <= LAST_PROD_DAY)
    return 2 * n


def _econ(C):
    """Daily economic plan: targets for crops and herd, species care modes."""
    P = C.P
    day = C.day
    C.rates = _shop_rates(C.shops)
    me_tiles = [t for _, t in C.plants] + [t for _, t in C.animals]
    C.pipe_me = _pipeline(me_tiles, day)
    C.pipe_opp = _pipeline(C.opp_plants + C.opp_animals, day)
    # a top rival keeps planting strawberries until ~day 13: assume at least `opp_straw_assume` plants
    if P["opp_straw_assume"] > 0 and day <= 13:
        n_opp = sum(1 for t in C.opp_plants if t.get("crop") == "STRAWBERRY")
        extra = max(0, P["opp_straw_assume"] - n_opp)
        C.pipe_opp["STRAWBERRY"] += extra * _new_plant_output("STRAWBERRY", min(13, day + 3))
    room = {}
    for p in PRODUCTS:
        if p == "FERTILIZER":
            continue
        deficit = I0 - C.minv.get(p, I0)
        room[p] = _demand_rem(C, p) + deficit - C.pipe_me[p] - C.pipe_opp[p] - C.shed.get(p, 0) - C.held.get(p, 0)
    C.room = room

    # strawberries
    st_out = _new_plant_output("STRAWBERRY", day)
    n_st = C.crop_count["STRAWBERRY"]
    if day <= P["straw_last_day"] or (day <= P["straw_late_day"] and st_out >= 6):
        add = max(0.0, (room["STRAWBERRY"] + P["straw_slack"]) * P["straw_share"] / max(1, st_out))
        tgt = n_st + int(add)
        if day >= 2:
            tgt = max(tgt, P["straw_min"])
        C.straw_target = min(P["straw_max"], tgt)
    else:
        C.straw_target = 0
    # tomatoes
    to_out = _new_plant_output("TOMATO", day)
    n_to = C.crop_count["TOMATO"]
    if P["tom_first_day"] <= day <= P["tom_last_day"] and to_out >= 6:
        add = max(0.0, (room["TOMATO"] + P["tom_slack"]) * P["tom_share"] / max(1, to_out))
        C.tom_target = min(P["tom_max"], max(P["tom_min"], n_to + int(add)))
    else:
        C.tom_target = 0
    # melons
    M = C.M
    planted = M.get("melons_planted", 0)
    if day <= 1:
        C.melon_target_total = P["melon_total"]
    elif day <= P["melon_last_day"] and C.prices["MELON"] >= P["melon2_price"] and room["MELON"] > 30:
        C.melon_target_total = P["melon_total"] + P["melon2_max"]
    else:
        C.melon_target_total = 0
    C.melons_planted = planted

    # species modes
    wheat_p = C.prices["WHEAT"]
    fert_p = C.prices["FERTILIZER"]
    modes = {}
    for a, ad in ANIMALS.items():
        prod = ad["product"]
        pr = C.prices[prod]
        base = MP[prod]["base"]
        full_ok = pr >= P["full_frac"] * base and pr >= wheat_p * 0.8
        if a == "GOOSE" and P["goose_full"] > 0:
            full_ok = full_ok and pr >= P["goose_full"]
        if full_ok:
            modes[a] = "FULL"
        elif pr >= P["maint_min"] or fert_p >= P["maint_min"] * 3:
            modes[a] = "MAINT"
        else:
            modes[a] = "STOP"
    C.modes = modes

    # herd targets (additional purchases allowed today, by species preference)
    C.animal_total = sum(C.animal_count.values()) + sum(C.waiting.values())
    buy_pref = []
    if P["animal_buy_start"] <= day <= P["animal_last_day"]:
        slack = {"WOOL": P["wool_slack"], "MILK": P["milk_slack"], "EGG": P["egg_slack"]}
        for a in ("SHEEP", "COW", "GOOSE"):
            prod = ANIMALS[a]["product"]
            out = _new_animal_output(a, day)
            if out <= 0:
                continue
            n_add = (room[prod] + slack[prod]) * P["animal_share"] / out
            if a == "GOOSE":
                n_add = min(n_add, P["goose_max"] - C.animal_count["GOOSE"] - C.waiting["GOOSE"])
            if n_add < 1:
                continue
            # value per coin of the animal (product at current price, fert value)
            v = out * min(C.prices[prod], MP[prod]["base"] * 1.2) + (LAST_PROD_DAY - day) * fert_p * 0.5 \
                - (LAST_PROD_DAY - day) * wheat_p - ad_cost(a)
            if v <= 0:
                continue
            buy_pref.append((v / ad_cost(a), a, int(n_add)))
    buy_pref.sort(reverse=True)
    C.buy_pref = buy_pref


def ad_cost(a):
    return ANIMALS[a]["cost"]


# ------------------------------------------------------------------ calendars -> tasks
def _care_plan(C, t):
    """Returns (feed_value, care_value, feed_needed, care_needed, crit) for an animal tile."""
    P = C.P
    day = C.day
    a = t["animal"]
    ad = ANIMALS[a]
    prod = ad["product"]
    price = C.prices[prod]
    mode = C.modes[a]
    placed = t["placed_day"]
    fyd, iv, cap = ad["first_yield_day"], ad["interval"], ad["max_held"]
    pend = t.get("pending_care_bonus", 0)
    cu = t.get("consecutive_unfed", 0)
    if day >= END_DAY:
        return 0.0, 0.0, False, False, False
    today_prod = prod_day(placed, fyd, iv, day)
    pstar = next_prod_after(placed, fyd, iv, day)
    future = pstar <= LAST_PROD_DAY or (today_prod and day <= LAST_PROD_DAY)
    care_v = 0.0
    care_needed = False
    if mode == "FULL" and not t.get("cared_today") and pstar <= LAST_PROD_DAY and pend + 1 <= cap - 1:
        first = placed + fyd - 1
        if pstar == first and day < first:
            # pre-first-production: only (cap-1) banked days count; spread the need over the days left
            need = cap - 1 - pend
            days_left = first - day  # days day..first-1 inclusive where care can still bank
            frac = min(1.0, need / max(1.0, days_left))
        else:
            frac = 1.0
        care_v = price * frac
        care_needed = True
    feed_v = 0.0
    feed_needed = False
    crit = False
    if not t.get("fed_today"):
        payout = today_prod and pend > 0 and day <= LAST_PROD_DAY
        if payout:
            feed_v += pend * price
            if pend >= 2:
                crit = True
        survive = cu >= 1 and mode != "STOP" and (future or C.prices["FERTILIZER"] >= 6) and day < END_DAY
        if survive:
            feed_v += 250.0
            crit = True
        if care_needed:
            feed_needed = True
        if payout or survive:
            feed_needed = True
        if mode == "MAINT" and not survive and not payout:
            feed_needed = False
        if mode == "STOP":
            feed_needed = False
            feed_v = 0.0
    if not feed_needed:
        # care without feed banks nothing
        if care_needed and not t.get("fed_today"):
            care_needed = False
            care_v = 0.0
    return feed_v, care_v, feed_needed, care_needed, crit


def _fert_value(C):
    return float(C.prices["FERTILIZER"])


def _animal_task(C, pos, t):
    P = C.P
    day = C.day
    a = t["animal"]
    ad = ANIMALS[a]
    prod = ad["product"]
    price = C.prices[prod]
    T = Task(pos, "A")
    feed_v, care_v, feed_n, care_n, crit = _care_plan(C, t)
    if feed_n:
        T.add(["FEED"], "W", feed_v)
    if care_n:
        T.add(["CARE"], "W" if not t.get("fed_today") else None, care_v)
    if t.get("fertilizer_available"):
        fv = C.fert_val
        if fv >= 2 and not (day >= END_DAY and C.step + SHED_D[pos] + 2 > LAST_STEP):
            T.add(["COLLECT_FERTILIZER"], None, fv)
    y = t.get("yield_units", 0)
    if y > 0:
        placed = t["placed_day"]
        fyd, iv, cap = ad["first_yield_day"], ad["interval"], ad["max_held"]
        today_prod = prod_day(placed, fyd, iv, day) and day <= LAST_PROD_DAY
        pend = t.get("pending_care_bonus", 0)
        exp = 1 + (pend if (t.get("fed_today") or feed_n) else 0)
        v = 0.0
        if day >= END_DAY:
            v = y * price
        elif today_prod and y + exp > cap:
            v = (y + exp - cap) * price
        elif day == LAST_PROD_DAY:
            v = y * price * 0.1
        thr = {"SHEEP": 4, "COW": 3, "GOOSE": 2}[a]
        if y >= thr and price >= 0.5 * MP[prod]["base"]:
            v = max(v, 0.04 * y * price + (0.12 * y * price if C.cash_starved else 0.0))
        elif y >= 1 and price >= MP[prod]["base"] * 0.9:
            v = max(v, 2.0)
        if v > 0:
            T.add(["HARVEST"], None, v)
    T.must = crit
    return T


def _plant_value(C, t):
    """Value at stake if the plant dies today: its remaining sellable output (min seed-ish floor)."""
    crop = t["crop"]
    p = C.prices[crop]
    cd = CROPS[crop]
    day = C.day
    if cd["ongoing"]:
        rem = sum(1 for d in crop_prod_days(crop, t["planted_day"]) if day <= d <= LAST_PROD_DAY)
        return 2.0 * rem * p + t.get("yield_units", 0) * p * 0.5
    if crop == "MELON":
        return 6.0 * p
    if crop == "WHEAT":
        return 5.0 * p
    return 4.0 * p


def _plant_task(C, pos, t):
    P = C.P
    day = C.day
    crop = t["crop"]
    cd = CROPS[crop]
    age = day - t["planted_day"]
    watered = t.get("watered_today", False)
    cu = t.get("consecutive_unwatered", 0)
    y = t.get("yield_units", 0)
    fu = t.get("fertilized_until_day", -1)
    price = C.prices[crop]
    T = Task(pos, "P")
    last = day >= END_DAY
    if last and C.step + SHED_D[pos] + 2 > LAST_STEP:
        return T
    if not cd["ongoing"]:
        myd = cd["max_yield_day"]
        ws = (myd + 1) // 2
        in_win = ws <= age <= myd
        # harvest policy
        if crop == "WHEAT":
            ready = age >= 2 and (y >= 5 or age >= 4 or (last and y >= 2) or
                                  (age >= 3 and fu < day and y >= 4))
        elif crop == "CARROT":
            ready = age >= 2 and (y >= 4 or age >= 3 or last)
        else:  # MELON
            ready = age >= 10 and (y >= 6 or age >= 12 or last or day >= LAST_PROD_DAY)
        will_water = False
        if not watered and not last:
            gain = 0
            if in_win and y < cd["max_yield"]:
                gain = 2 if fu >= day else 1
            # fertilize first (one-shot crops apply the bonus at WATER time)
            if in_win and age == ws and fu < day and C.fert_for_oneshot.get(crop):
                extra = 2 if crop == "WHEAT" else 1
                fv = extra * price - C.fert_val
                if fv > 0:
                    T.add(["FERTILIZE"], "F", fv)
                    gain = 2
            harvest_after = False
            if ready or (age == myd and in_win):
                harvest_after = True
            surv = (age == 0 or cu >= 1) and not ready
            wv = 0.0
            if gain > 0 and not (ready and y >= cd["max_yield"]):
                wv += gain * price
            if surv:
                wv += min(300.0, _plant_value(C, t))
                T.must = True
            if wv > 0:
                T.add(["WATER"], None, wv)
                will_water = True
        if crop == "MELON" and age >= 10 and not last:
            T.bonus = P["melon_bonus"]   # race the rival's melons to the market
        if ready and y > 0:
            v = y * price if (age >= myd or last) else 12.0 + 0.1 * y * price
            if crop == "MELON":
                v = max(v, 40.0 + 0.2 * y * price)
            T.add(["HARVEST"], None, v)
            # replant immediately
            nxt = _choose_crop(C, pos, freeing=True)
            if nxt:
                T.add(["PLANT", nxt], "S:" + nxt, C.tile_value.get(nxt, 30.0))
                T.add(["WATER"], None, 5.0)
        elif C.early_harvest_ok and crop == "WHEAT" and age >= 2 and y >= 2 and not last:
            nxt = _choose_crop(C, pos, freeing=True)
            if nxt in ("STRAWBERRY", "TOMATO"):
                T.add(["HARVEST"], None, 25.0 + y * price * 0.3)
                T.add(["PLANT", nxt], "S:" + nxt, C.tile_value.get(nxt, 30.0))
                T.add(["WATER"], None, 5.0)
                C.early_harvest_used += 1
        return T
    # ongoing crops: STRAWBERRY / TOMATO
    pdays = crop_prod_days(crop, t["planted_day"])
    remaining = [d for d in pdays if d >= day and d <= LAST_PROD_DAY]
    today_prod = day in pdays and day <= LAST_PROD_DAY
    if not watered and not last:
        if today_prod:
            v = (2 if fu >= day else 1) * price
            if cu >= 1:
                v += min(300.0, _plant_value(C, t))
                T.must = True
            T.add(["WATER"], None, v)
        elif (age == 0 or cu >= 1) and remaining:
            T.add(["WATER"], None, min(300.0, _plant_value(C, t)))
            T.must = True
    if today_prod and fu < day and not last:
        covered = sum(1 for d in remaining if day <= d <= day + 2)
        if covered > 0:
            T.add(["FERTILIZE"], "F", covered * price - C.fert_val * 0.3)
    cap = cd["max_yield"]
    if y > 0:
        v = 0.0
        if last:
            v = y * price
        elif today_prod and y + 2 > cap:
            v = (y + 2 - cap) * price
        elif not remaining:
            v = y * price * 0.5
        elif y >= cap:
            v = 8.0
        if y >= P["ongo_harv_min"] and (T.nops > 0 or watered):
            # harvest on the watering visit: sells earlier, no extra trip
            v = max(v, P["ongo_harv_frac"] * y * price)
        if v > 0:
            T.add(["HARVEST"], None, v)
    spent = (not remaining) and (y == 0 or any(o[0][0] == "HARVEST" for o in T.ops)) and age >= pdays[-1] - t["planted_day"] + 1
    if spent and not last:
        nxt = _choose_crop(C, pos, freeing=True)
        if nxt:
            T.add(["DIG"], None, 10.0)
            T.add(["PLANT", nxt], "S:" + nxt, C.tile_value.get(nxt, 30.0))
            T.add(["WATER"], None, 5.0)
    return T


def _tile_values(C):
    """Per-day value of a tile planted with each crop now (used for choices and task values)."""
    P = C.P
    day = C.day
    wp = C.prices["WHEAT"]
    fp = C.fert_val
    v = {}
    v["WHEAT"] = max(5.0, (5 * wp - 10 - 0.5 * fp) / 3.0) if day <= 26 else 0.0
    v["CARROT"] = max(0.0, (4 * C.prices["CARROT"] - 20 - 0.5 * fp) / 3.0) if day <= 27 else 0.0
    v["STRAWBERRY"] = 60.0
    v["TOMATO"] = 45.0
    v["MELON"] = 60.0
    C.tile_value = v


def _load_ok(C, crop):
    """Labor gate: would planting `crop` push the steady-state load over capacity?"""
    P = C.P
    if C.day < 2:
        return True
    add = P["load_crop"].get(crop, 1.0)
    lim = P["load_max_hi"] if crop in ("STRAWBERRY", "TOMATO", "MELON") else P["load_max_lo"]
    if C.load + C.tally_load + add > C.capacity * lim:
        return False
    return True


def _take_seed(C, crop):
    """Reserve a seed for a planned planting: use held seeds first, else budget cash."""
    if not _load_ok(C, crop):
        return False
    C.tally_load += C.P["load_crop"].get(crop, 1.0)
    used = C.tally.get(crop, 0)
    if C.seeds.get(crop, 0) > used:
        C.tally[crop] = used + 1
        return True
    cost = CROPS[crop]["seed"]
    if C.seed_budget >= cost:
        C.seed_budget -= cost
        C.tally[crop] = used + 1
        return True
    return False


def _choose_crop(C, pos, freeing=False):
    """Crop to plant on a free (or being-freed) tile; None = keep empty."""
    P = C.P
    day = C.day
    if day >= END_DAY - 1:
        return None
    tally = C.tally
    # opening layout
    if day <= 1 and quad_of(*pos) == "NW":
        if pos in NW_ANIMALS:
            return None
        if pos in NW_MELON0 or (day == 1 and pos in NW_MELON1):
            if C.melons_planted + tally.get("MELON", 0) < P["melon_total"]:
                if _take_seed(C, "MELON"):
                    return "MELON"
            return None
        if pos in NW_MELON1:
            return None
        if pos in NW_WHEAT0:
            if _take_seed(C, "WHEAT"):
                return "WHEAT"
            return None
    if pos in C.reserved_set and not freeing:
        return None
    if pos in C.slot_set and sum(C.waiting.values()) > len(C.empty_structs) and day >= 2:
        return None  # an animal is waiting for a structure: keep ring tiles for it
    # melons (second batch only when price is high)
    if day <= P["melon_last_day"] and C.melon_target_total > C.melons_planted + tally.get("MELON", 0) \
            and day + 10 <= LAST_PROD_DAY:
        if _take_seed(C, "MELON"):
            return "MELON"
    if C.crop_count["STRAWBERRY"] + tally.get("STRAWBERRY", 0) < C.straw_target:
        if _take_seed(C, "STRAWBERRY"):
            return "STRAWBERRY"
        if day <= P["straw_last_day"] and day < P["early_cash_day"] and P["keep_for_straw"]:
            return None  # keep the tile for a strawberry once cash arrives
    if C.crop_count["TOMATO"] + tally.get("TOMATO", 0) < C.tom_target:
        if _take_seed(C, "TOMATO"):
            return "TOMATO"
    if day < 2:
        return None
    wv, cv = C.tile_value["WHEAT"], C.tile_value["CARROT"]
    carrot_room = C.room.get("CARROT", 0) - 4 * tally.get("CARROT", 0)
    if cv > wv and carrot_room > 20 and day <= 27:
        if _take_seed(C, "CARROT"):
            return "CARROT"
    if day <= 26 and wv > 0:
        if _take_seed(C, "WHEAT"):
            return "WHEAT"
    if day == 27 and C.prices["CARROT"] >= 20:
        if _take_seed(C, "CARROT"):
            return "CARROT"
    return None


def _build_tasks(C):
    P = C.P
    day = C.day
    tasks = []
    # animals
    for pos, t in C.animals:
        T = _animal_task(C, pos, t)
        if T.nops:
            tasks.append(T)
    # plants (far tiles first so long-lived crops chosen for freed tiles land on the outer rings)
    plants_order = sorted(C.plants, key=lambda pt: (-SHED_D[pt[0]], pt[0][1], pt[0][0])) if P["far_first"] else C.plants
    for pos, t in plants_order:
        T = _plant_task(C, pos, t)
        if T.nops:
            tasks.append(T)
    # empty structures -> place waiting animals (or dig if not needed)
    wait_p = C.waiting["COW"] + C.waiting["SHEEP"]
    wait_c = C.waiting["GOOSE"]
    for pos, kind in C.empty_structs:
        T = Task(pos, "S")
        if kind == "PASTURE" and wait_p > 0:
            wait_p -= 1
            T.bonus = P["place_bonus"]
            T.add(["PLACE", "?P"], "P", 220.0)
            T.add(["FEED"], "W", 20.0)
            T.add(["CARE"], "W", 40.0)
        elif kind == "COOP" and wait_c > 0:
            wait_c -= 1
            T.bonus = P["place_bonus"]
            T.add(["PLACE", "GOOSE"], "C", 180.0)
            T.add(["FEED"], "W", 10.0)
            T.add(["CARE"], "W", 20.0)
        elif C.struct_need <= 0 and day >= 2 and day < END_DAY - 1:
            nxt = _choose_crop(C, pos, freeing=True)
            if nxt:
                T.add(["DIG"], None, 8.0)
                T.add(["PLANT", nxt], "S:" + nxt, C.tile_value.get(nxt, 30.0))
                T.add(["WATER"], None, 5.0)
        if T.nops:
            tasks.append(T)
    # free tiles: build for waiting animals on ring slots, else plant
    if P["far_first"]:
        free_sorted = sorted(C.free, key=lambda p: (0 if p in C.slot_set else 1, -SHED_D[p], p[1], p[0]))
    else:
        free_sorted = sorted(C.free, key=lambda p: (0 if p in C.slot_set else 1, SHED_D[p], p[1], p[0]))
    for pos in free_sorted:
        T = Task(pos, "F")
        if pos in C.slot_set and (wait_p > 0 or wait_c > 0) and day < END_DAY - 1:
            T.bonus = P["place_bonus"]
            if wait_p > 0:
                wait_p -= 1
                T.add(["BUILD_PASTURE"], None, 20.0)
                T.add(["PLACE", "?P"], "P", 220.0)
            else:
                wait_c -= 1
                T.add(["BUILD_COOP"], None, 20.0)
                T.add(["PLACE", "GOOSE"], "C", 180.0)
            T.add(["FEED"], "W", 20.0)
            T.add(["CARE"], "W", 40.0)
            tasks.append(T)
            continue
        crop = _choose_crop(C, pos)
        if crop:
            T.add(["PLANT", crop], "S:" + crop, C.tile_value.get(crop, 30.0))
            T.add(["WATER"], None, 5.0)
            tasks.append(T)
    for pos in C.weeds:
        if day >= END_DAY - 1:
            break
        crop = _choose_crop(C, pos, freeing=True)
        if crop:
            T = Task(pos, "W")
            T.add(["DIG"], None, 8.0)
            T.add(["PLANT", crop], "S:" + crop, C.tile_value.get(crop, 30.0))
            T.add(["WATER"], None, 5.0)
            tasks.append(T)
    return tasks


# ------------------------------------------------------------------ router
def _exec_op(C, i, T, inv, seed_left):
    """First executable op of task T for unit i standing on T.pos; returns action or None."""
    x, y = T.pos
    t = C.tiles[y][x]
    for (action, need, val) in T.ops:
        op = action[0]
        if op == "FEED":
            if isinstance(t, dict) or hasattr(t, "get"):
                if t is not None and t.get("animal") and not t.get("fed_today") and inv.get("WHEAT", 0) > 0:
                    return ["FEED"]
            continue
        if op == "CARE":
            if t is not None and t != "LOCKED" and t.get("animal") and not t.get("cared_today"):
                # care only counts if fed today; do it after feeding when possible
                if t.get("fed_today") or inv.get("WHEAT", 0) > 0:
                    return ["CARE"]
            continue
        if op == "COLLECT_FERTILIZER":
            if t is not None and t != "LOCKED" and t.get("animal") and t.get("fertilizer_available"):
                return ["COLLECT_FERTILIZER"]
            continue
        if op == "HARVEST":
            if t is not None and t != "LOCKED" and t.get("yield_units", 0) > 0:
                if t.get("kind") == "PLANT":
                    if C.day - t["planted_day"] < CROPS[t["crop"]]["first_yield_day"]:
                        continue
                return ["HARVEST"]
            continue
        if op == "WATER":
            if t is not None and t != "LOCKED" and t.get("kind") == "PLANT" and not t.get("watered_today"):
                return ["WATER"]
            continue
        if op == "FERTILIZE":
            if t is not None and t != "LOCKED" and t.get("kind") == "PLANT" and inv.get("FERTILIZER", 0) > 0:
                return ["FERTILIZE"]
            continue
        if op == "PLANT":
            if t is None and seed_left.get(action[1], 0) > 0:
                seed_left[action[1]] -= 1
                return ["PLANT", action[1]]
            if t is None:
                return "WAIT_SEED"
            continue
        if op == "DIG":
            if t is not None and t != "LOCKED" and not t.get("animal"):
                return ["DIG"]
            continue
        if op in ("BUILD_PASTURE", "BUILD_COOP"):
            if t is None:
                return [op]
            continue
        if op == "PLACE":
            if t is not None and t != "LOCKED" and t.get("kind") in ("PASTURE", "COOP") and not t.get("animal"):
                if t.get("kind") == "PASTURE":
                    if inv.get("COW", 0) > 0:
                        return ["PLACE", "COW"]
                    if inv.get("SHEEP", 0) > 0:
                        return ["PLACE", "SHEEP"]
                else:
                    if inv.get("GOOSE", 0) > 0:
                        return ["PLACE", "GOOSE"]
            continue
    return None


def _route(C, tasks):
    P = C.P
    M = C.M
    day, hour, step = C.day, C.hour, C.step
    units = C.units
    n = len(units)
    actions = [None] * n
    lam = P["lam"]
    invs = C.invs
    seed_left = dict(C.seeds)
    shed_left = dict(C.shed)
    tgt_prev = M.get("tgt", {})
    new_tgt = {}
    last = day >= END_DAY
    urg_mult = 1.0 + P["urgency"] * hour / 23.0

    feeds = sum(1 for T in tasks for o in T.ops if o[0][0] == "FEED")
    ferts = sum(1 for T in tasks for o in T.ops if o[1] == "F")
    carried_w = sum(inv.get("WHEAT", 0) for inv in invs)
    carried_f = sum(inv.get("FERTILIZER", 0) for inv in invs)
    unc = {"W": max(0, feeds - carried_w), "F": max(0, ferts - carried_f)}
    n_active = max(1, n)

    def carried_sellable(inv):
        return sum(q for k, q in inv.items() if k in SELLABLE)

    def nonfeed_items(inv):
        return sum(q for k, q in inv.items() if k in SELLABLE and k not in ("WHEAT", "FERTILIZER"))

    def mark_drop(inv):
        for k, q in inv.items():
            C.dropping[k] = C.dropping.get(k, 0) + q

    task_at = {}
    for ti, T in enumerate(tasks):
        task_at[T.pos] = ti

    # --- triage: if today's remaining work exceeds the remaining labor, drop the lowest value-per-op tasks
    deferred = set()
    if P["triage"] and not last:
        n_plan = max(n, M.get("hire_plan", (day, n - 1))[1] + 1) if hour <= 2 else n
        cap_left = n_plan * (TPD - hour) * P["triage_prod"]
        work = sum(T.nops for T in tasks)
        if work > cap_left:
            order = sorted(range(len(tasks)), key=lambda ti: tasks[ti].value_all() / max(1, tasks[ti].nops))
            for ti in order:
                if work <= cap_left:
                    break
                T = tasks[ti]
                if T.must or T.bonus > 0:
                    continue
                deferred.add(ti)
                work -= T.nops

    # --- last day: return to shed and drop everything before step 718
    if last:
        for i in range(n):
            u = units[i]
            inv = invs[i]
            if carried_sellable(inv) <= 0:
                continue
            ds = SHED_D[u]
            if step + ds + 1 >= LAST_STEP - 1 or step >= LAST_STEP - 1:
                if u in SHED_SET:
                    actions[i] = ["DROP"]
                    mark_drop(inv)
                else:
                    actions[i] = [step_toward(u, NEAR_SHED[u])]

    # --- drop pseudo-task values (sell goods now)
    up = P["urg_premium"]
    urg = {"MELON": 0.25, "WOOL": up, "MILK": up, "STRAWBERRY": up, "TOMATO": 0.02,
           "EGG": 0.01, "CARROT": 0.01, "FERTILIZER": 0.01, "WHEAT": 0.0}
    drop_val = [0.0] * n
    for i in range(n):
        inv = invs[i]
        v = 0.0
        for k, q in inv.items():
            if k in urg:
                pr = C.prices[k]
                v += q * pr * urg[k]
                if C.cash_starved and k != "WHEAT":
                    v += q * pr * P["starved_drop"]
        if C.cash_starved and C.money < P["starved_cash"] and any(k != "WHEAT" and k in urg for k in inv):
            v += P["starved_bonus"]
        if last:
            v += sum(q * C.prices.get(k, 0) for k, q in inv.items())
        tot = carried_sellable(inv)
        if tot >= P["carry_heavy"]:
            v += 4.0 * tot
        if C.overflow_risk > 0 and tot > 0:
            v += P["risk_item_val"] * min(tot, C.overflow_risk)
        drop_val[i] = v

    # --- burst rule: a unit standing on a task tile keeps working it
    taken_t = set()
    for i in range(n):
        if actions[i] is not None:
            continue
        u = units[i]
        ti = task_at.get(u)
        if ti is None or ti in taken_t:
            continue
        T = tasks[ti]
        inv = invs[i]
        doable = 0.0
        for (action, need, val) in T.ops:
            if has_need(inv, need):
                doable += val
        if doable < P["burst_min"]:
            continue
        a = _exec_op(C, i, T, inv, seed_left)
        if a is None:
            continue
        if a == "WAIT_SEED":
            continue
        actions[i] = a
        taken_t.add(ti)
        new_tgt[i] = T.pos
        _note_action(C, M, T, a)

    use_sec = P["sec_pen"] > 0 and n > 1
    if use_sec:
        bounds, usec = _sectors(C, tasks)
        tsec = [_sec_of(bounds, T.pos) for T in tasks]
        if P["proactive_pick"]:
            need_w = collections.Counter()
            need_f = collections.Counter()
            for ti, T in enumerate(tasks):
                if ti in taken_t:
                    continue
                for (action, need, val) in T.ops:
                    if action[0] == "FEED":
                        need_w[tsec[ti]] += 1
                    elif action[0] == "FERTILIZE":
                        need_f[tsec[ti]] += 1
            for i in range(n):
                if actions[i] is not None or units[i] not in SHED_SET:
                    continue
                inv = invs[i]
                sct = usec[i]
                wq = need_w[sct] - inv.get("WHEAT", 0)
                if wq > 0 and shed_left.get("WHEAT", 0) > 0:
                    q = min(shed_left["WHEAT"], wq + 1, P["pick_cap"])
                    actions[i] = ["PICKUP", "WHEAT", q]
                    shed_left["WHEAT"] -= q
                    need_w[sct] -= q
                    unc["W"] -= q
                    continue
                fq = need_f[sct] - inv.get("FERTILIZER", 0)
                if fq > 0 and shed_left.get("FERTILIZER", 0) > 0:
                    q = min(shed_left["FERTILIZER"], fq + 1, P["pick_cap"])
                    actions[i] = ["PICKUP", "FERTILIZER", q]
                    shed_left["FERTILIZER"] -= q
                    need_f[sct] -= q
                    unc["F"] -= q
                    continue

    # --- morning: units leaving the shed take a share of today's fertilizer (production-day FERTILIZE)
    if P["morning_fert"] and hour <= P["morning_fert_hour"] and ferts > 0:
        f_unc = ferts - carried_f
        share = int(math.ceil(ferts / float(max(1, n)))) + 1
        for i in range(n):
            if f_unc <= 0:
                break
            if actions[i] is not None or units[i] not in SHED_SET:
                continue
            if invs[i].get("FERTILIZER", 0) > 0 or shed_left.get("FERTILIZER", 0) <= 0:
                continue
            q = min(shed_left["FERTILIZER"], share, f_unc + 1)
            actions[i] = ["PICKUP", "FERTILIZER", q]
            shed_left["FERTILIZER"] -= q
            f_unc -= q
            unc["F"] -= q

    # --- morning: units leaving the shed take a share of today's feed wheat (full FEED+CARE bursts)
    if P["morning_wheat"] and hour <= P["morning_fert_hour"] and feeds > 0:
        w_unc = feeds - carried_w
        share = max(2, int(math.ceil(feeds / float(max(1, n)))) + 1)
        for i in range(n):
            if w_unc <= 0:
                break
            if actions[i] is not None or units[i] not in SHED_SET:
                continue
            if invs[i].get("WHEAT", 0) > 0 or shed_left.get("WHEAT", 0) <= 0:
                continue
            q = min(shed_left["WHEAT"], share, w_unc + 1)
            actions[i] = ["PICKUP", "WHEAT", q]
            shed_left["WHEAT"] -= q
            w_unc -= q
            unc["W"] -= q

    # --- units standing on a shed tile: drop if worthwhile (1 action, no detour)
    for i in range(n):
        if actions[i] is not None:
            continue
        u = units[i]
        if u not in SHED_SET:
            continue
        inv = invs[i]
        items = carried_sellable(inv)
        if items <= 0:
            continue
        nf = nonfeed_items(inv)
        # shed off surplus wheat (harvested / over-picked) so carried stock never overflows the shed
        wkeep = 0 if last else min(inv.get("WHEAT", 0), max(2, int(math.ceil(feeds / float(max(1, n)))) + 2))
        if inv.get("WHEAT", 0) - wkeep >= P["wheat_drop_min"] and not last:
            q = inv["WHEAT"] - wkeep
            actions[i] = ["PLACE", "WHEAT", q]
            C.dropping["WHEAT"] = C.dropping.get("WHEAT", 0) + q
            continue
        if drop_val[i] >= P["shed_drop_val"] or nf >= P["shed_drop_items"] or (last and items > 0):
            keep_w = inv.get("WHEAT", 0) > 0 and feeds > 0 and not last
            keep_f = inv.get("FERTILIZER", 0) > 0 and ferts > 0 and not last
            if (keep_w or keep_f) and nf > 0:
                best = max((k for k in inv if k in SELLABLE and k not in ("WHEAT", "FERTILIZER")),
                           key=lambda k: inv[k] * C.prices.get(k, 0))
                actions[i] = ["PLACE", best, inv[best]]
                C.dropping[best] = C.dropping.get(best, 0) + inv[best]
            elif not keep_w and not keep_f:
                actions[i] = ["DROP"]
                mark_drop(inv)

    # --- scoring (compressed values: among tasks due today, distance dominates)
    CAP = P["vcap"] + P["vcap_grow"] * hour

    def cv(v):
        if CAP <= 0 or v <= 0:
            return v
        return CAP * (1.0 - math.exp(-v / CAP))
    nbonus = [0.0] * len(tasks)
    if P["nb_w"] > 0:
        vpos = {}
        for T in tasks:
            vpos[T.pos] = cv(T.value_all())
        for a_i, Ta in enumerate(tasks):
            ax, ay = Ta.pos
            tot = vpos.get((ax + 1, ay), 0.0) + vpos.get((ax - 1, ay), 0.0) +                 vpos.get((ax, ay + 1), 0.0) + vpos.get((ax, ay - 1), 0.0)
            nbonus[a_i] = P["nb_w"] * tot
    if P["look_w"] > 0 and tasks:
        # 2-step look-ahead: value of the best follow-up task near each candidate target
        vals2 = [cv(T.value_all()) for T in tasks]
        poss = [T.pos for T in tasks]
        for a_i in range(len(tasks)):
            ax, ay = poss[a_i]
            best = 0.0
            for b_i in range(len(tasks)):
                if b_i == a_i:
                    continue
                dd_ = abs(poss[b_i][0] - ax) + abs(poss[b_i][1] - ay)
                if dd_ > 3:
                    continue
                sc_ = vals2[b_i] - lam * dd_
                if sc_ > best:
                    best = sc_
            nbonus[a_i] += P["look_w"] * best
    pairs = []
    for i in range(n):
        if actions[i] is not None:
            continue
        u = units[i]
        inv = invs[i]
        at_shed = u in SHED_SET
        for ti, T in enumerate(tasks):
            if ti in taken_t or ti in deferred:
                continue
            d = dist(u, T.pos)
            spen = 0.0
            if use_sec:
                ds_ = abs(tsec[ti] - usec[i])
                ds_ = min(ds_, n - ds_)
                if ds_ > 0:
                    spen = P["sec_pen"] * (1.0 if ds_ == 1 else 2.0)
            if last:
                if step + d + T.nops + SHED_D[T.pos] + 1 > LAST_STEP:
                    continue
            elif hour + d >= TPD:
                continue
            vd = 0.0
            miss = []
            for (action, need, val) in T.ops:
                if has_need(inv, need):
                    vd += val
                elif need not in miss:
                    miss.append(need)
            dens = P["score_mode"] == "density"
            nd = sum(1 for o in T.ops if has_need(inv, o[1]))
            # doing only part of a tile's burst (missing wheat/fertilizer/animal) forces a second visit later
            rpen = P["revisit_pen"] if (miss and vd > 0) else 0.0
            if dens:
                vv = vd + (nbonus[ti] if vd > 0 else 0.0) + (T.bonus if not miss else 0.0)
                if T.must:
                    vv *= urg_mult
                sc = vv / (d + nd + P["dens_k"]) - spen * P["dens_spen"] if vd > 0 else -1.0
            else:
                vd = cv(vd) + (nbonus[ti] if vd > 0 else 0.0) + (T.bonus if not miss else 0.0)
                if T.must:
                    vd *= urg_mult
                sc = vd - lam * d - spen - rpen
            best = (sc, 0, None)
            if miss:
                ok = True
                for m in miss:
                    if m == "W" and shed_left.get("WHEAT", 0) <= 0:
                        ok = False
                    elif m == "F" and shed_left.get("FERTILIZER", 0) <= 0:
                        ok = False
                    elif m == "P" and shed_left.get("COW", 0) + shed_left.get("SHEEP", 0) <= 0:
                        ok = False
                    elif m == "C" and shed_left.get("GOOSE", 0) <= 0:
                        ok = False
                if ok:
                    if at_shed:
                        s = u
                    else:
                        s = min(SHED_TILES, key=lambda s: (dist(u, s) + dist(s, T.pos), dist(u, s)))
                    dd = dist(u, s) + len(miss) + dist(s, T.pos)
                    if not (last and step + dd + T.nops + SHED_D[T.pos] > LAST_STEP) and hour + dd < TPD:
                        if dens:
                            va = (T.value_all() + nbonus[ti]) * (urg_mult if T.must else 1.0) + T.bonus
                            sc2 = va / (dd + T.nops + P["dens_k"]) - spen * P["dens_spen"]
                        else:
                            va = (cv(T.value_all()) + nbonus[ti]) * (urg_mult if T.must else 1.0) + T.bonus
                            sc2 = va - lam * dd - spen
                        if sc2 > sc:
                            best = (sc2, 1, s)
            if tgt_prev.get(i) == T.pos:
                if dens:
                    best = (best[0] * (1.0 + P["stick_frac"]), best[1], best[2])
                else:
                    best = (best[0] + P["stick"], best[1], best[2])
            if dens:
                okp = best[0] > 0 and (vd >= P["min_task_val"] or (best[1] == 1 and T.value_all() >= P["min_task_val"]))
            else:
                okp = best[0] > 0 or (vd >= P["min_task_val"] and best[1] == 0) or                     (best[1] == 1 and T.value_all() >= P["min_task_val"])
            if okp:
                pairs.append((best[0], -d, i, ti, best[1], best[2]))
        if drop_val[i] > 0 and not last:
            ds = SHED_D[u]
            if P["score_mode"] == "density":
                sc = drop_val[i] / (ds + 1 + P["dens_k"])
            else:
                sc = drop_val[i] - lam * (ds + 1)
            if sc > 0 and hour + ds < TPD:
                pairs.append((sc, -ds, i, -1, 2, NEAR_SHED[u]))
    pairs.sort(key=lambda z: (-z[0], -z[1], z[2], z[3]))
    if P["commit"]:
        # committed targets first: a unit keeps the tile it is walking to (no reassignment thrash)
        committed = []
        rest_pairs = []
        for z in pairs:
            i, ti = z[2], z[3]
            if ti >= 0 and tgt_prev.get(i) == tasks[ti].pos:
                committed.append(z)
            else:
                rest_pairs.append(z)
        pairs = committed + rest_pairs
    taken_u = set(i for i in range(n) if actions[i] is not None)
    for sc, negd, i, ti, mode, shed_t in pairs:
        if i in taken_u or (ti >= 0 and ti in taken_t):
            continue
        u = units[i]
        inv = invs[i]
        if ti == -1:
            taken_u.add(i)
            if u in SHED_SET:
                actions[i] = ["DROP"]
                mark_drop(inv)
            else:
                actions[i] = [step_toward(u, shed_t)]
            continue
        T = tasks[ti]
        if mode == 1:
            if u in SHED_SET:
                miss = [m for m in T.needs() if not has_need(inv, m)]
                act = None
                for m in miss:
                    if m == "W" and shed_left.get("WHEAT", 0) > 0:
                        share = max(P["wheat_share_min"], int(math.ceil(feeds / float(n_active))) + 1)
                        q = min(shed_left["WHEAT"], max(1, min(P["wheat_pick"], max(unc["W"], 1), share)))
                        unc["W"] -= q
                        shed_left["WHEAT"] -= q
                        act = ["PICKUP", "WHEAT", q]
                        break
                    if m == "F" and shed_left.get("FERTILIZER", 0) > 0:
                        share = int(math.ceil(ferts / float(n_active))) + 1
                        q = min(shed_left["FERTILIZER"], max(1, min(P["fert_pick"], max(unc["F"], 1), share)))
                        unc["F"] -= q
                        shed_left["FERTILIZER"] -= q
                        act = ["PICKUP", "FERTILIZER", q]
                        break
                    if m == "P":
                        for a in ("SHEEP", "COW"):
                            if shed_left.get(a, 0) > 0:
                                shed_left[a] -= 1
                                act = ["PICKUP", a, 1]
                                break
                        if act:
                            break
                    if m == "C" and shed_left.get("GOOSE", 0) > 0:
                        shed_left["GOOSE"] -= 1
                        act = ["PICKUP", "GOOSE", 1]
                        break
                if act is None:
                    continue
                actions[i] = act
            else:
                actions[i] = [step_toward(u, shed_t)]
            taken_u.add(i)
            taken_t.add(ti)
            new_tgt[i] = T.pos
            continue
        d = -negd
        if d == 0:
            a = _exec_op(C, i, T, inv, seed_left)
            if a is None:
                continue
            if a == "WAIT_SEED":
                for (action, need, val) in T.ops:
                    if action[0] == "PLANT":
                        C.plant_soon[action[1]] = C.plant_soon.get(action[1], 0) + 1
                        break
                a = ["PASS"]
            actions[i] = a
            _note_action(C, M, T, a)
        else:
            actions[i] = [step_toward(u, T.pos)]
            if d <= 1 and T.ops and T.ops[0][0][0] == "PLANT":
                crop = T.ops[0][0][1]
                C.plant_soon[crop] = C.plant_soon.get(crop, 0) + 1
        taken_u.add(i)
        taken_t.add(ti)
        new_tgt[i] = T.pos
    for i in range(n):
        if actions[i] is None:
            u = units[i]
            inv = invs[i]
            if last and carried_sellable(inv) > 0:
                if u in SHED_SET:
                    actions[i] = ["DROP"]
                    mark_drop(inv)
                else:
                    actions[i] = [step_toward(u, NEAR_SHED[u])]
            elif (C.cash_starved or hour >= 20 or C.overflow_risk > 0 or nonfeed_items(inv) >= 3) \
                    and (nonfeed_items(inv) > 0 or (inv.get("FERTILIZER", 0) > 0 and (C.cash_starved or not ferts))):
                if u in SHED_SET:
                    if inv.get("WHEAT", 0) and feeds and not last:
                        best = max((k for k in inv if k in SELLABLE and k != "WHEAT"),
                                   key=lambda k: inv[k] * C.prices.get(k, 0))
                        actions[i] = ["PLACE", best, inv[best]]
                        C.dropping[best] = C.dropping.get(best, 0) + inv[best]
                    else:
                        actions[i] = ["DROP"]
                        mark_drop(inv)
                else:
                    actions[i] = [step_toward(u, NEAR_SHED[u])]
            else:
                actions[i] = ["PASS"]
    # plant validation: never exceed seeds per crop (atomic PLANT rule)
    for crop in CROPS:
        cnt = sum(1 for a in actions if a and a[0] == "PLANT" and a[1] == crop)
        if cnt > C.seeds.get(crop, 0):
            k = C.seeds.get(crop, 0)
            for i, a in enumerate(actions):
                if a and a[0] == "PLANT" and a[1] == crop:
                    if k > 0:
                        k -= 1
                    else:
                        actions[i] = ["PASS"]
    M["tgt"] = new_tgt
    C.idle = sum(1 for a in actions if a == ["PASS"])
    return actions


def _note_action(C, M, T, a):
    """Bookkeeping after choosing an on-tile op (seed pre-buy for follow-up plantings, melon count)."""
    if a[0] in ("HARVEST", "DIG"):
        for (action, need, val) in T.ops:
            if action[0] == "PLANT":
                C.plant_soon[action[1]] = C.plant_soon.get(action[1], 0) + 1
                break
    if a[0] == "PLANT" and a[1] == "MELON":
        M["melons_planted"] = M.get("melons_planted", 0) + 1


# ------------------------------------------------------------------ labor
def _plan_hires(C, tasks):
    P = C.P
    day = C.day
    if day >= END_DAY and C.hour > 0:
        return 0
    ops = 0.0
    visits = 0
    for T in tasks:
        ops += T.nops
        visits += 1
    # after-harvest replant/dig follow-ups are included in task ops; add pickups
    ops += 0.15 * visits
    walk = P["hire_walk"] * visits
    need_turns = (ops + walk) / P["hire_eff"]
    units = int(math.ceil(need_turns / 23.0))
    fb = C.M.get("hire_fb", 0)
    units += fb
    hires = max(0, units - 1)
    fl = P["hire_floor"]
    floor_h = fl[min(day, len(fl) - 1)]
    if day >= 27:
        floor_h = P["hire_end"][min(day - 27, 2)]
    hires = max(hires, floor_h)
    if day == 0:
        hires = max(hires, P["min_hires_d0"])
    cap_h = P["max_hires"]
    if P["peak_days"][0] <= day <= P["peak_days"][1] and hires > cap_h:
        cap_h = P["max_hires_peak"]   # land-purchase days: extra hands to plant the new quadrant
    hires = min(hires, cap_h)
    # marginal cost cap
    cap_n = 0
    for k in range(hires):
        if FIB[k] <= P["hire_value"] * 23 * (0.6 if day < 3 else 1.0) or k < 4:
            cap_n = k + 1
        else:
            break
    return cap_n


# ------------------------------------------------------------------ market
def _sell_qty(item, inv, have, floor):
    n = 0
    proceeds = 0.0
    while n < have:
        pr = mprice(item, inv)
        if pr < floor:
            break
        proceeds += pr
        if pr > 1:
            inv += 1
        n += 1
    return n, proceeds


def _market(C, actions, tasks):
    P = C.P
    M = C.M
    day, hour, step = C.day, C.hour, C.step
    last = day >= END_DAY
    orders = []
    shed_after = dict(C.shed)
    for i, a in enumerate(actions):
        if not a:
            continue
        if a[0] == "DROP":
            for k, q in C.invs[i].items():
                shed_after[k] = shed_after.get(k, 0) + q
        elif a[0] == "PLACE" and a[1] in PRODUCTS and C.units[i] in SHED_SET:
            q = min(int(a[2]) if len(a) > 2 else 1, C.invs[i].get(a[1], 0))
            shed_after[a[1]] = shed_after.get(a[1], 0) + q
        elif a[0] == "PICKUP":
            shed_after[a[1]] = shed_after.get(a[1], 0) - int(a[2])

    # --- feed / fertilizer reserves (post-action accounting)
    carried_after = []
    n_feed_now = 0
    n_fert_now = 0
    for i, a in enumerate(actions):
        inv = dict(C.invs[i])
        if a:
            if a[0] == "DROP" and C.units[i] in SHED_SET:
                inv = {}
            elif a[0] == "PLACE" and a[1] in PRODUCTS and C.units[i] in SHED_SET:
                inv[a[1]] = max(0, inv.get(a[1], 0) - int(a[2]))
            elif a[0] == "PICKUP":
                inv[a[1]] = inv.get(a[1], 0) + int(a[2])
            elif a[0] == "FEED":
                inv["WHEAT"] = max(0, inv.get("WHEAT", 0) - 1)
                n_feed_now += 1
            elif a[0] == "FERTILIZE":
                inv["FERTILIZER"] = max(0, inv.get("FERTILIZER", 0) - 1)
                n_fert_now += 1
            elif a[0] == "COLLECT_FERTILIZER":
                inv["FERTILIZER"] = inv.get("FERTILIZER", 0) + 1
        carried_after.append(inv)
    carried_w = sum(inv.get("WHEAT", 0) for inv in carried_after)
    carried_f = sum(inv.get("FERTILIZER", 0) for inv in carried_after)
    feeds_today = sum(1 for T in tasks for o in T.ops if o[0][0] == "FEED")
    feeds_rem = max(0, feeds_today - n_feed_now)
    feed_per_day = 0.0
    for pos, t in C.animals:
        md = C.modes.get(t["animal"], "FULL")
        feed_per_day += 1.0 if md == "FULL" else (0.5 if md == "MAINT" else 0.0)
    feed_per_day += sum(C.waiting.values())
    tomorrow_feed = feed_per_day if day + 1 < END_DAY - 1 else 0.0
    wheat_stock = shed_after.get("WHEAT", 0) + carried_w
    if last:
        wheat_keep = 0
    else:
        # keep today's remaining feeds + tomorrow's + a buffer (in the shed; carried wheat counts)
        wheat_keep = max(0, int(math.ceil(feeds_rem + tomorrow_feed * P["wheat_reserve_days"] + 3)) - carried_w)
    fert_stock = shed_after.get("FERTILIZER", 0) + carried_f
    fert_keep = 0 if last else max(0, C.fert_need_soon - n_fert_now - carried_f)

    # --- sell orders
    sells = []
    est_cash = 0.0
    floors = P["sell_floor"]
    for item in STEEP_ORDER:
        have = shed_after.get(item, 0)
        if item == "WHEAT":
            have -= wheat_keep
        if item == "FERTILIZER":
            have -= fert_keep
        have = min(have, shed_after.get(item, 0))
        if have <= 0:
            continue
        base = MP[item]["base"]
        if last or day >= END_DAY - 1:
            floor = 1
        elif day >= END_DAY - 2 and item != "WHEAT":
            floor = max(1, int(base * floors.get(item, 0.2) * 0.4))
        else:
            floor = max(1, int(base * floors.get(item, 0.2)))
            if P["proj_floor"] and item not in ("WHEAT", "FERTILIZER") and item in C.room:
                # reservation price from the projected end-of-season market (demand pool vs pipelines)
                proj = mprice(item, I0 - C.room[item])
                floor = max(1, min(int(base * P["proj_cap"]), int(proj * P["proj_frac"])))
        if item == "FERTILIZER" and not last:
            floor = 2
            # cheap fertilizer is worth more on our wheat (+2 wheat) than on the market: keep a buffer
            if C.fert_for_oneshot.get("WHEAT") and day < END_DAY - 2 and C.crop_count["WHEAT"] > 0:
                buf = int(P["fert_wheat_buf"] * C.crop_count["WHEAT"])
                have = min(have, max(0, shed_after.get(item, 0) - fert_keep - buf))
        n, proceeds = _sell_qty(item, C.minv[item], have, floor)
        if n > 0:
            sells.append(["SELL", item, n])
            est_cash += proceeds * 0.97
    # overflow guard: at the end-of-day drop, shed + carried must fit in 100 (excess is destroyed)
    if hour >= P["guard_hour"] and not last:
        carried = sum(sum(max(0, q) for q in inv.values()) for inv in carried_after)
        for i, a in enumerate(actions):
            if a and a[0] == "HARVEST":
                x, y = C.units[i]
                tt = C.tiles[y][x]
                if isinstance(tt, dict) or hasattr(tt, "get"):
                    carried += int(tt.get("yield_units", 0) or 0)
        sold = {sl[1]: sl[2] for sl in sells}
        total = sum(max(0, v) for v in shed_after.values()) - sum(sold.values()) + carried
        if hour == TPD - 1:
            target = 100
            order = ["FERTILIZER", "EGG", "CARROT", "TOMATO", "WHEAT", "MELON", "STRAWBERRY", "MILK", "WOOL"]
        else:
            # leave room for what units will still pick up before midnight
            target = 100 - int(P["guard_room"] * len(C.units) * (TPD - 1 - hour))
            order = ["EGG", "CARROT", "TOMATO", "MELON", "STRAWBERRY", "MILK", "WOOL"]
        over = total - target
        if over > 0:
            for item in order:
                if over <= 0:
                    break
                avail = shed_after.get(item, 0) - sold.get(item, 0)
                if item == "WHEAT" and hour < TPD - 1:
                    avail = min(avail, max(0, shed_after.get(item, 0) - wheat_keep) - sold.get(item, 0))
                if avail <= 0:
                    continue
                k = min(avail, over)
                sold[item] = sold.get(item, 0) + k
                over -= k
            new_sells = []
            for item in STEEP_ORDER:
                if sold.get(item, 0) > 0:
                    new_sells.append(["SELL", item, sold[item]])
            sells = new_sells
        C.overflow_left = max(0, over)
    cash = C.money + est_cash - P["cash_reserve"]

    # --- hires
    hires = []
    if not last or hour == 0:
        plan = M.get("hire_plan", (-1, 0))
        if plan[0] == day and hour <= 2:
            want = plan[1] - C.hires_today
            k = 0
            while k < want:
                cost = FIB[C.hires_today + k]
                if cost > cash:
                    break
                cash -= cost
                k += 1
            hires = [["HIRE"]] * k

    # --- feed wheat: buy only real deficits (now, or tomorrow's at the end of the day)
    need_w = 0
    if not last:
        need_w = feeds_rem - wheat_stock
        if hour >= 21:
            need_w = int(math.ceil(feeds_rem + tomorrow_feed)) - wheat_stock
    wheat_orders = []
    if need_w > 0 and C.prices["WHEAT"] <= 90:
        q = 0
        inv = C.minv["WHEAT"]
        while q < need_w:
            pr = mprice("WHEAT", inv - 1)
            if pr > cash:
                break
            cash -= pr
            inv -= 1
            q += 1
        if q > 0:
            wheat_orders.append(["BUY_PRODUCT", "WHEAT", q])
    cash -= C.hire_reserve
    buys = []
    # --- land
    n_extra = len(C.unlocked) - 1
    if n_extra < 3 and P["land_first_day"] <= day <= P["land_last_day"]:
        price = LAND_PRICES[n_extra]
        if cash >= price + P["land_fill"][n_extra]:
            buys.append(["BUY_LAND"])
            cash -= price
    # --- animals: buy for free ring slots (or empty structures)
    animal_orders = []
    if P["animal_buy_start"] <= day <= P["animal_last_day"] and C.buy_pref:
        free_slots = sum(1 for p in C.slots if C.tiles[p[1]][p[0]] is None) + len(C.empty_structs)
        free_slots -= sum(C.waiting.values())
        cap_total = P["animal_max"] - C.animal_total
        n_can = min(free_slots, cap_total)
        bought = {}
        prefs = [list(x) for x in C.buy_pref]
        while n_can > 0 and prefs:
            prefs.sort(key=lambda z: -z[0])
            v, a, lim = prefs[0]
            if bought.get(a, 0) >= lim:
                prefs.pop(0)
                continue
            if cash < ANIMALS[a]["cost"]:
                break
            cash -= ANIMALS[a]["cost"]
            bought[a] = bought.get(a, 0) + 1
            prefs[0][0] = v * 0.93
            n_can -= 1
        for a, q in bought.items():
            animal_orders.append(["BUY_ANIMAL", a, q])
    # --- seeds (just in time)
    seed_orders = []
    for crop, q in C.plant_soon.items():
        have = C.seeds.get(crop, 0) - sum(1 for a in actions if a and a[0] == "PLANT" and a[1] == crop)
        buy = q - max(0, have)
        if buy > 0:
            cost = CROPS[crop]["seed"]
            k = min(buy, int(cash // cost))
            if k > 0:
                seed_orders.append(["BUY_SEED", crop, k])
                cash -= k * cost
    # --- fertilizer buy-back only when today's fertilizing is blocked and it is cheap
    fert_orders = []
    ferts_today = sum(1 for T in tasks for o in T.ops if o[0][0] == "FERTILIZE")
    fneed = ferts_today - n_fert_now - fert_stock
    if not last and fneed > 0 and C.prices["FERTILIZER"] <= P["fert_buy_max"] and hour <= 18:
        q = min(fneed, int(cash // max(1, C.prices["FERTILIZER"] + 1)))
        if q > 0:
            fert_orders.append(["BUY_PRODUCT", "FERTILIZER", q])

    steep = [s for s in sells if s[1] in ("WOOL", "MILK", "STRAWBERRY", "MELON")]
    rest = [s for s in sells if s[1] not in ("WOOL", "MILK", "STRAWBERRY", "MELON")]
    rest.sort(key=lambda s: -s[2] * C.prices.get(s[1], 1))
    hire_cost = sum(FIB[C.hires_today + k] for k in range(len(hires)))
    if C.money < hire_cost + 30:
        # hires need this step's sale proceeds: all sells first (engine runs orders in list order)
        head = steep + rest
        rest_after = []
    else:
        head = steep
        rest_after = rest
    buys_all = wheat_orders + buys + animal_orders + seed_orders + fert_orders
    orders = head + hires + rest_after + buys_all
    if len(orders) > 10:
        orders = (head + hires)[:10]
        for o in rest_after + buys_all:
            if len(orders) >= 10:
                break
            orders.append(o)
    return orders


# ------------------------------------------------------------------ main
def _day0_orders(P):
    if P["opening"] == "tfc":
        # 3 cows + 2 sheep, 7 melons, 13 wheat, 5 hands (THIRD FARM CLUB)
        return [["BUY_PRODUCT", "WHEAT", 3], ["HIRE"], ["HIRE"], ["HIRE"], ["HIRE"], ["HIRE"],
                ["BUY_ANIMAL", "SHEEP", 2], ["BUY_ANIMAL", "COW", 3], ["BUY_SEED", "MELON", 7], ["BUY_SEED", "WHEAT", 13]]
    return [["HIRE"], ["HIRE"], ["HIRE"], ["HIRE"], ["BUY_PRODUCT", "WHEAT", 4], ["BUY_ANIMAL", "COW", 2],
            ["BUY_SEED", "MELON", 6], ["BUY_ANIMAL", "SHEEP", 3], ["BUY_SEED", "WHEAT", 9]]


def _act(obs, P, MEM):
    C = _parse(obs, P, MEM)
    M = C.M
    if C.step == 0 and C.money >= 2990 and len(C.unlocked) == 1:
        M["melons_planted"] = 0
        M["hire_plan"] = (0, 5 if P["opening"] == "tfc" else 4)
        return {"farmer": ["BUILD_PASTURE"], "hands": [], "market": _day0_orders(P)}
    _survey(C)
    _econ(C)
    day, hour = C.day, C.hour
    C.fert_val = _fert_value(C)
    fp, wp = C.prices["FERTILIZER"], C.prices["WHEAT"]
    C.fert_for_oneshot = {"WHEAT": fp < P["wheat_fert_ratio"] * wp, "CARROT": fp < P["wheat_fert_ratio"] * 1.3 * C.prices["CARROT"]}
    C.cash_starved = day < P["early_cash_day"] and C.money < 300
    C.dropping = {}
    C.tally = {}
    C.tally_load = 0.0
    C.plant_soon = {}
    # seed budget for crop choices this step (money minus planned land purchase)
    sb = C.money + 0.0
    # value of goods already in the shed that will be sold this step (feed wheat excluded)
    for k, q in C.shed.items():
        if k in SELLABLE and k != "WHEAT" and q > 0:
            sb += 0.85 * q * C.prices[k]
    n_extra = len(C.unlocked) - 1
    if n_extra < 3 and P["land_first_day"] <= day <= P["land_last_day"] and             sb >= LAND_PRICES[n_extra] + P["land_fill"][n_extra]:
        sb -= LAND_PRICES[n_extra]
    # keep tomorrow morning's hires affordable
    fl = P["hire_floor"]
    C.hire_reserve = sum(FIB[:fl[min(day + 1, len(fl) - 1)]]) if hour >= 12 and day < 12 else 0
    sb -= C.hire_reserve
    C.seed_budget = sb
    # reserve the nearest free ring slots for animals waiting or about to be bought
    n_plan = 0
    if P["animal_buy_start"] <= day <= P["animal_last_day"] and C.buy_pref:
        n_plan = min(sum(x[2] for x in C.buy_pref), max(0, P["animal_max"] - C.animal_total))
    n_need = sum(C.waiting.values()) + n_plan
    C.struct_need = n_need
    n_free_need = max(0, n_need - len(C.empty_structs))
    free_slots = sorted([p for p in C.free if p in C.slot_set], key=lambda p: (SHED_D[p], p))
    C.reserved_set = set(free_slots[:n_free_need])
    C.reserve_slots = len(C.reserved_set)
    _tile_values(C)
    # labor load (steady-state ops/day) vs capacity: gate low-value plantings
    ld = 0.0
    for pos, t in C.animals:
        ld += P["load_animal"] if C.modes.get(t["animal"]) == "FULL" else P["load_animal_maint"]
    ld += P["load_animal"] * sum(C.waiting.values())
    for pos, t in C.plants:
        ld += P["load_crop"].get(t["crop"], 1.0)
    C.load = ld
    plan_units = min(P["max_hires"], max(M.get("hire_plan", (0, 12))[1], 1)) + 1
    if day >= 8:
        plan_units = P["max_hires"] + 1
    if M.get("cap_day") != day:
        # adapt the labor-capacity estimate to yesterday's outcome (idle turns vs unfinished must-tasks)
        M["cap_day"] = day
        cm = M.get("cap_mult", 1.0)
        if day >= 9 and P["cap_adapt"]:
            idle = M.get("idle_sum", 0) / max(1.0, float(M.get("uturns", 1)))
            lm = M.get("left_must", 0)
            if lm > P["cap_lm_hi"]:
                cm *= 1.0 - P["cap_step"]
            elif idle > P["cap_idle_hi"] and lm <= P["cap_lm_lo"]:
                cm *= 1.0 + P["cap_step"]
            cm = max(P["cap_min"], min(P["cap_max"], cm))
        M["cap_mult"] = cm
    C.capacity = plan_units * 23.0 * P["prod_frac"] * M.get("cap_mult", 1.0)
    # fertilizer needs in the next few days (strawberry / tomato production days)
    need = 0
    for pos, t in C.plants:
        crop = t["crop"]
        if CROPS[crop]["ongoing"]:
            pd = crop_prod_days(crop, t["planted_day"])
            fu = t.get("fertilized_until_day", -1)
            for d in pd:
                if day <= d <= day + P["fert_keep_days"] and d > fu and d <= LAST_PROD_DAY:
                    need += 1
                    fu = d + 2
        elif crop in ("WHEAT", "CARROT") and C.fert_for_oneshot.get(crop):
            if t["planted_day"] + 2 >= day and t.get("fertilized_until_day", -1) < t["planted_day"] + 2:
                need += 1
    C.fert_need_soon = need
    # early harvest of placeholder wheat when strawberries are wanted and affordable
    C.early_harvest_used = 0
    C.early_harvest_ok = False
    if P["early_wheat_harvest"] and 2 <= day <= P["straw_last_day"]:
        gap = C.straw_target - C.crop_count["STRAWBERRY"]
        if gap > 0 and not [p for p in C.free if p not in C.slot_set] and C.money >= 100:
            C.early_harvest_ok = True
    # overflow risk (units carrying lots of goods late in the day)
    carried_total = sum(sum(inv.values()) for inv in C.invs)
    shed_total = sum(C.shed.values())
    C.overflow_risk = 0
    if hour >= P["risk_hour"] and day < END_DAY:
        proj = carried_total + shed_total + P["risk_rate"] * len(C.units) * (TPD - 1 - hour)
        C.overflow_risk = max(0, int(proj - 96))

    tasks = _build_tasks(C)
    if hour == 0 or M.get("hire_plan", (-1, 0))[0] != day:
        # feedback from yesterday: unfinished must-tasks -> more hands; idle -> fewer
        fb = 0
        lm = M.get("left_must", 0)
        idle_frac = M.get("idle_sum", 0) / max(1, M.get("uturns", 1))
        prev_fb = M.get("hire_fb", 0)
        if lm >= 3:
            fb = prev_fb + 1
        elif idle_frac > 0.22:
            fb = prev_fb - 1
        else:
            fb = prev_fb
        M["hire_fb"] = max(-3, min(3, fb))
        M["idle_sum"] = 0
        M["uturns"] = 0
        M["hire_plan"] = (day, _plan_hires(C, tasks))
    actions = _route(C, tasks)
    if hour >= 2:
        M["idle_sum"] = M.get("idle_sum", 0) + C.idle
        M["uturns"] = M.get("uturns", 0) + len(C.units)
    if hour == TPD - 1:
        M["left_must"] = sum(1 for T in tasks if T.must)
    orders = _market(C, actions, tasks)
    return {"farmer": actions[0], "hands": actions[1:], "market": orders}


_AGENT = make_agent()


def agent(obs, config=None):
    return _AGENT(obs, config)
