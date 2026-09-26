"""Kaggriculture agent.

Two farms share one market and the richer farm after 720 turns (30 days of 24 hours) wins. Each turn the
agent surveys both farms and the market, plans purchases and tile use, turns the plan into tile jobs,
assigns the farmer and hands to jobs, and places market orders.

Strategy
  Opening    Day 0 buys a small herd (2 cows, 3 sheep) penned at the shed door, as many of 12 melons as the
             cash allows in the ring behind the pens, and wheat on the rim. The melons ripen together on day 10
             and race to market ahead of the rival's. If the rival sows almost no melons, the far rim gets
             four more on day 1.
  Books      For every product a market book forecasts the market inventory day by day from town demand
             (known shops plus expected unlocks) and both farms' visible pipelines. A candidate plant or animal
             is worth the forecast prices of its own sale days, net of the price it knocks off our other sales.
             Books size strawberry plantings, a second melon crop on days 12-19, and herd purchases by species;
             an animal also counts half the revenue it takes from the rival, who sells to the same buyers.
             Tomatoes and carrots are sized by the room left in their markets; wheat fills the remaining tiles
             and feeds the herd.
  Labour     Hands are hired on a fixed schedule (12 on days 10-27). Every tile with work becomes a job with a
             priority; units take jobs greedily by priority minus walking distance, with bonuses for jobs that
             chain several actions and for keeping yesterday's target. Units at the shed pick up feed,
             fertilizer and animals, and drop goods for sale.
  Selling    Steep price curves sell first. Part of a batch waits in the shed when the town's draws before a
             later sale window are forecast to lift the price by more than the wait risks. At hour 0 steep
             sells are ordered to list ahead of the rival's tracked stock.
  Last day   Units take only harvests they can carry back to the shed by the final step, ranked by coins.
             Premium goods wait in the shed until late afternoon and are sold together.

Standard library only. State is kept per player id.
"""
import itertools
import math

# ============================================================================ game constants

N = 10
HALF = 5
HOURS = 24
DAYS = 30
LAST_STEP = 718
SHED_CAP = 100
MAX_ORDERS = 10

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
STEADY_YIELD = {"SHEEP": 4, "COW": 3, "GOOSE": 2}  # units per production with daily care
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]

# price curve per product: (base price, scale, shape below / above neutral, amplitude below / above)
PRICE_CURVE = {
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
BASE_PRICE = {k: v[0] for k, v in PRICE_CURVE.items()}
NEUTRAL_INV = 10000

SHOPS = {
    "BAKERY": ["EGG", "WHEAT"], "PIZZA_SHOP": ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT": ["EGG", "WHEAT", "STRAWBERRY"], "YARN_STORE": ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"], "PET_CAFE": ["CARROT"],
    "SMOOTHIE_SHOP": ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
LAND_PRICES = [1000, 2000, 4000]

# the order book runs slot by slot, so the steepest price curves are listed first
SELL_ORDER = ["WOOL", "MILK", "STRAWBERRY", "MELON", "TOMATO", "CARROT", "EGG", "WHEAT", "FERTILIZER"]
STEEP = ("WOOL", "MILK", "STRAWBERRY", "MELON", "TOMATO")
RACE_GOODS = ("MILK", "WOOL", "STRAWBERRY", "TOMATO")
RIVAL_TRACKED = ("WOOL", "MILK", "STRAWBERRY", "MELON", "TOMATO", "EGG", "CARROT")
# forced sales when the midnight drop would overflow the shed: cheapest goods go first
DUMP_ORDER = ["FERTILIZER", "WHEAT", "EGG", "CARROT", "TOMATO", "STRAWBERRY", "MILK", "WOOL", "MELON"]
LAST_DAY_HOLD = ("WOOL", "MILK", "STRAWBERRY", "TOMATO")

# ============================================================================ market model


def _shape(func, x, scale):
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
        u = x / scale
        return u + 8.0 * max(0.0, u - 1.0) ** 2
    return x


_AMPLITUDE = {}
for _k, (_b, _s, _bf, _bt, _af, _at) in PRICE_CURVE.items():
    _AMPLITUDE[_k] = (_bt * _b / _shape(_bf, _s, _s), _at * _b / _shape(_af, _s, _s))


def market_price(item, inv):
    base, scale, below_f, _, above_f, _ = PRICE_CURVE[item]
    amp_below, amp_above = _AMPLITUDE[item]
    if inv < NEUTRAL_INV:
        p = base + amp_below * _shape(below_f, NEUTRAL_INV - inv, scale)
    else:
        p = base - amp_above * _shape(above_f, inv - NEUTRAL_INV, scale)
    return max(1, int(round(p)))


def sell_revenue(item, inv, n):
    total = 0
    for _ in range(n):
        p = market_price(item, inv)
        total += p
        if p > 1:
            inv += 1
    return total


def _shop_draw(item, name):
    """units a shop takes of `item` at each of its draws: single-product shops take two."""
    prods = SHOPS.get(name, ())
    if item not in prods:
        return 0
    return 2 if len(prods) == 1 else 1


# expected extra demand (units/day) added by one future shop unlock, per product
UNLOCK_DEMAND = {}
for _p in PRODUCTS:
    _s = 0.0
    for _name, _prods in SHOPS.items():
        if _p in _prods:
            _s += 12.0 if len(_prods) == 1 else 6.0
    UNLOCK_DEMAND[_p] = _s / len(SHOPS)


def daily_demand(item, shops):
    if item == "FERTILIZER":
        return 0.0
    r = 1.0
    for s in shops:
        prods = SHOPS.get(s, ())
        if item in prods:
            r += 12.0 if len(prods) == 1 else 6.0
    return r


def town_demand(item, day, hour, shops, unlock_weight):
    """forecast town consumption of `item` for each day from today to the end ({day: units})."""
    known = daily_demand(item, shops)
    per_unlock = UNLOCK_DEMAND[item] * unlock_weight
    pending = [u for u in range(3, 25, 3) if u > day][:max(0, 8 - len(shops))]
    dem = {}
    for t in range(day, DAYS):
        k = sum(1 for u in pending if u <= t)
        d = known + per_unlock * k
        if t == day:
            d *= (HOURS - hour) / float(HOURS)
        dem[t] = d
    return dem


def town_draw(item, step, shops):
    """units the town takes of `item` right after the market orders of `step`."""
    d = 0
    if step % 4 == 0:
        for name in shops:
            d += _shop_draw(item, name)
    if step % 24 == 0 and item != "FERTILIZER":
        d += 1
    return d


# Market book inputs. Sale dates of what grows or grazes on a farm, as {day: units}.
PROD_AGES = {"STRAWBERRY": (9, 11, 13, 15), "TOMATO": (7, 8, 9, 10)}
BOOK_YIELD = 1.85  # units per production actually sold (2 when fertilized; misses and losses included)
ONE_SHOT = {"MELON": (10, 6.0), "CARROT": (3, 4.0)}  # harvest age, units sold
# per plant: fertilizer applications, labour relative to a strawberry, tile-days occupied
BOOK_UPKEEP = {"STRAWBERRY": (2, 1.0, 17), "MELON": (0, 0.7, 11)}


def crop_sales(out, crop, sow_day, day, n=1.0):
    """add the sale dates of n plants of `crop` sown on sow_day to out ({day: units}).
    Ongoing crops: each production reaches the market spread over the two following days, the way
    harvest rounds and sell orders actually trickle out. One-shot crops sell the day after harvest."""
    if crop in PROD_AGES:
        half = 0.5 * BOOK_YIELD * n
        for a in PROD_AGES[crop]:
            prod_day = sow_day + a
            if day <= prod_day <= DAYS - 2:
                for t in (prod_day + 1, prod_day + 2):
                    if t < DAYS:
                        out[t] = out.get(t, 0) + half
    else:
        age, units = ONE_SHOT[crop]
        if sow_day + age <= DAYS - 1:
            t = max(day, min(DAYS - 1, sow_day + age + 1))
            out[t] = out.get(t, 0) + units * n
    return out


def animal_sales(out, animal, placed_day, day, n=1.0, held=0):
    """add the sale dates of n cared-for animals placed on placed_day: the first production is the banked
    cap, later ones the steady amount; a production at the end of day p sells on day p + 1."""
    ad = ANIMALS[animal]
    first = placed_day + ad["fyd"] - 1
    p = first
    while p <= DAYS - 2:
        if p + 1 >= day:
            out[p + 1] = out.get(p + 1, 0) + n * (ad["cap"] if p == first else STEADY_YIELD[animal])
        p += ad["interval"]
    if held:
        out[day] = out.get(day, 0) + held
    return out


def farm_sales(tiles, item, day):
    """{day: units} a farm's growing plants or animals should bring to market of `item`."""
    out = {}
    for row in tiles:
        for t in row:
            if not isinstance(t, dict):
                continue
            if t.get("kind") == "PLANT":
                if t.get("crop") != item:
                    continue
                held = int(t.get("yield_units", 0) or 0)
                if held > 0 and item in PROD_AGES:
                    out[day] = out.get(day, 0) + held
                crop_sales(out, item, t["planted_day"], day)
            elif t.get("animal") and ANIMALS[t["animal"]]["product"] == item:
                animal_sales(out, t["animal"], t["placed_day"], day, held=int(t.get("yield_units", 0) or 0))
    return out


def remaining_supply(tiles, crop, day):
    """units of TOMATO or CARROT a farm's current plants will still yield, assuming fertilizer."""
    total = 0.0
    for row in tiles:
        for t in row:
            if not isinstance(t, dict) or t.get("kind") != "PLANT" or t["crop"] != crop:
                continue
            if crop == "TOMATO":
                n = sum(1 for a in PROD_AGES["TOMATO"] if day <= t["planted_day"] + a <= DAYS - 2)
                total += 2 * n + int(t.get("yield_units", 0))
            else:
                total += 4
    return total


class MarketBook:
    """Forecast of one product's market inventory to the end of the game.

    Inputs are town consumption (known shops plus the expected demand of shops still to unlock), the sale
    dates of everything already growing or grazing on both farms, and the rival's likely further plantings.
    A candidate plant or animal is valued at the prices its own sale days are forecast to fetch, net of the
    price it knocks off our other sales, which favours early, uncontested windows."""

    def __init__(self, item, day, inv_now, demand, ours, theirs):
        self.item = item
        self.day = day
        self.inv_now = inv_now
        self.demand = demand
        self.ours = dict(ours)
        self.theirs = dict(theirs)

    def revenues(self, extra=None):
        """(our revenue, rival revenue) over the rest of the game, optionally with extra own units."""
        x = self.inv_now
        mine = theirs = 0.0
        for t in range(self.day, DAYS):
            s_me = self.ours.get(t, 0) + (extra.get(t, 0) if extra else 0)
            s_op = self.theirs.get(t, 0)
            dem = self.demand.get(t, 0.0)
            price = market_price(self.item, x + 0.5 * (s_me + s_op - dem))
            mine += s_me * price
            theirs += s_op * price
            x += s_me + s_op - dem
        return mine, theirs

    def gain(self, extra, rival_weight=0.0):
        """change of (our revenue - rival_weight * rival revenue) from extra own sales {day: units}."""
        if not extra:
            return 0.0
        m0, r0 = self.revenues()
        m1, r1 = self.revenues(extra)
        return (m1 - m0) - rival_weight * (r1 - r0)

    def commit(self, extra):
        for t, n in extra.items():
            self.ours[t] = self.ours.get(t, 0) + n


def sale_split(item, n, inv, step, last_step, shops, rival_now, soon, arrivals, risk, max_windows):
    """how many of our n units to sell now. The rest wait for a later window when the town's draws in
    between are forecast to lift the price by more than the risk discount per step waited. Window j opens
    the step after the j-th town draw. Supply we do not control reaches the market ahead of our held units:
    the rival's harvested stock now, ripe and carried goods by the first window, and each later day's
    scheduled output of both farms ({day: units}) by that day's first window, so we never hold into a glut."""
    bases = [inv + rival_now]
    discs = [1.0]
    supply = rival_now + soon
    drawn = 0
    s = step
    while len(bases) <= max_windows and s < last_step:
        d = town_draw(item, s, shops)
        s += 1
        if s % HOURS == 0:
            supply += arrivals.get(s // HOURS, 0)
        if d:
            drawn += d
            bases.append(inv + supply - drawn)
            discs.append(1.0 - risk * (s - step))
    if len(bases) == 1:
        return n
    w = len(bases)
    alloc = [0] * w
    for _ in range(n):
        starts = []
        ahead = 0
        for j in range(w):
            starts.append(bases[j] + ahead)
            ahead += alloc[j]
        # one more unit at window j pushes every later window one unit up the curve
        later = 0.0
        best_j, best_v = 0, None
        for j in range(w - 1, -1, -1):
            v = discs[j] * market_price(item, starts[j] + alloc[j]) + later
            if best_v is None or v >= best_v:
                best_j, best_v = j, v
            later += discs[j] * (market_price(item, starts[j] + alloc[j]) - market_price(item, starts[j]))
        alloc[best_j] += 1
    return alloc[0]


# ============================================================================ farm geometry


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


SHED_DIST = {}
NEAR_SHED = {}
for _x in range(N):
    for _y in range(N):
        _best = min(SHED_TILES, key=lambda s: (dist((_x, _y), s), SHED_TILES.index(s)))
        SHED_DIST[(_x, _y)] = dist((_x, _y), _best)
        NEAR_SHED[(_x, _y)] = _best


def _on_cross(p):
    return p[0] in (4, 5) or p[1] in (4, 5)


# tiles within two steps of the shed are kept for pens while the herd is still growing
ZONE = set(p for p in SHED_DIST if SHED_DIST[p] <= 2)
STRUCT_ORDER = sorted(SHED_DIST, key=lambda p: (SHED_DIST[p], 0 if _on_cross(p) else 1, p[1], p[0]))
CROP_RANK = {p: i for i, p in enumerate(sorted(SHED_DIST, key=lambda p: (SHED_DIST[p], p[1], p[0])))}

HOME_DOOR = (HALF - 1, HALF - 1)
HOME_TILES = [(x, y) for y in range(HALF) for x in range(HALF)]


def home_layout(groups):
    """Lay out the 25 starting tiles as rings around the shed door (4,4).

    `groups` lists (name, count) from the door outwards; each group is grown as a compact block
    (nearest ring first, then tiles touching the block, then tiles near the diagonal so the block
    stays symmetric around the door). Leftover tiles are returned under "rim".
    The opening uses pens -> melons -> spare pens -> rim (wheat). Animals get the door because they are
    visited every day (feed, care, fertilizer, harvest) for the whole game; melons come next because they
    race to the shed on day 10 and afterwards hand their tiles to the growing herd; wheat is filler on the
    far corner until strawberries can be afforded. A melon block on the door wins the day-10 race, but the
    longer daily walks to the herd cost more than the race is worth."""
    pool = list(HOME_TILES)
    out = {}
    for name, n in groups:
        block = []
        for _ in range(max(0, min(n, len(pool)))):
            def key(p):
                touch = sum(1 for q in block if dist(p, q) == 1)
                return (dist(p, HOME_DOOR), -touch, abs(p[0] - p[1]), p)
            best = min(pool, key=key)
            block.append(best)
            pool.remove(best)
        out[name] = block
    out["rim"] = pool
    return out


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


def fib_sum(a, b):
    """cost of hires number a..b-1 of the day (0-indexed)."""
    f = [1, 1]
    while len(f) < b + 2:
        f.append(f[-1] + f[-2])
    return sum(f[i] for i in range(a, b))


# ============================================================================ parameters

DEFAULT_PARAMS = {
    # unit assignment: coins per step walked, bonus per extra chained action, bonus for yesterday's target
    "w_dist": 20.0,
    "burst": 6.0,
    "stick": 8.0,
    # opening
    "melon_n": 12,            # melons sown on day 0 as cash allows
    "open_cows": 2,
    "open_sheep": 3,
    "open_hires": 4,
    "open_spare": 2,          # home pens left open for the herd growth of days 1-5
    "open_spare_until": 6,
    "early_cows": 1,          # cows added on days 1-5 once fertilizer money flows
    # The far rim tiles wait one day; on day 1, once the rival's day-0 field is visible, they get melons only
    # if the rival grows almost none. The day-10 melon market is shallow: against a real melon grower the
    # seed money is worth more in the early herd and berries, against a non-grower melons pay well.
    "melon_topup": 4,
    "topup_rival_max": 3,
    # crops
    "straw_first": 2,
    "straw_last": 16,
    "straw_cap": 42,
    "tom_first": 8,
    "tom_last": 18,
    "tom_cap": 20,
    "tom_min_price": 80,
    "wheat_last": 27,
    "carrot_last": 27,
    "fert_wheat_ratio": 1.6,  # fertilize wheat and carrots while fertilizer costs less than this many wheat
    "zone_release_day": 13,
    "zone_margin": 4,
    "w_future": 0.3,          # weight on shops still to unlock in the tomato / carrot room estimate
    "room_mult": 1.3,
    "rival_straw_final": 30,  # strawberries the rival is assumed to reach by rival_straw_day
    "rival_straw_day": 11,
    # second melon crop, sized by the melon book once the opening melons have sold
    "wave_first": 12,
    "wave_last": 19,
    "wave_cap": 12,
    # market book valuation of a plant or animal
    "book_unlock_w": 1.0,     # weight on expected demand from shops not yet unlocked
    "book_alt": 25.0,         # coins per tile-day the tile would earn as wheat / carrots instead
    "book_fert_cap": 60.0,
    "book_labor": 60.0,
    # herd
    "herd_day": 6,            # herd sized by the market books from this day on
    "herd_place_hour": 16,
    "herd_labor": 12.0,       # coins per animal-day of feed / care / collect walks
    "herd_rival_weight": 0.5,  # weight on the rival's lost revenue: our herd also competes for its buyers
    "fert_sell_share": 0.6,   # share of our fertilizer assumed sold (the rest goes on our crops)
    "sheep_cap": 16,
    "cow_cap": 12,
    "goose_cap": 4,
    "animal_cap": 24,
    "cow_last": 17,
    "sheep_last": 20,
    "goose_last": 15,
    "maint_frac": 0.30,       # below this share of base price an animal only gets maintenance feed
    # land
    "land_first": [4, 8, 10],
    "land_last": [14, 14, 0],
    # Hands per day, followed as is. Trimming days 10+ to a workload estimate (10-11 hands) saves about $200 a
    # day, but the 12th hand gets berries, milk and wool harvested and sold sooner, which costs the rival more
    # on the shared premium markets than the hire costs us. A 13th hand no longer pays.
    "hires": [4, 5, 6, 7, 7, 7, 9, 10, 10, 11, 12] + [12] * 17 + [11, 10],
    "night_hour": 17,         # from this hour, cash for tomorrow's hires and morning feed is kept back
    "wheat_keep_hour": 12,    # from this hour, tomorrow's feed is kept instead of sold
    # job priorities
    "fert_prio": 105.0,
    "final_harv_prio": 115.0,
    "collect_base": 55.0,
    "collect_mult": 0.5,
    # early game: goods reach the shed quickly while prices are high
    "early_drop_day": 11,
    "prem_rush_day": 11,
    "prem_harv": 150.0,
    "prem_drop": 200.0,
    # melon race: ripe melons are harvested first and carried straight to market
    "melon_harv_prio": 220.0,
    "melon_rebate": 20.0,     # ripe-melon jobs ignore this much of the walk penalty per step
    "melon_rush": 300.0,
    "rush_day": 13,
    # courier value per coin of carried steep goods the rival also holds or can harvest
    "race_drop": 0.1,
    "race_cap": 200.0,
    # late-day couriers when the midnight drop would overflow the shed
    "overflow_hour": 16,
    "overflow_margin": 15,
    # sale timing: part of a batch waits for a later sale window
    "hold_items": ["MILK", "WOOL", "STRAWBERRY", "TOMATO", "EGG", "CARROT"],
    "hold_risk": 0.0025,      # price discount per step waited
    "hold_windows": 24,
    "hold_room": 20,          # shed slots kept free for drops while goods wait
    "hold_cash": 300.0,
    # last day
    "sweep_step_coins": 10.0,  # coins a unit-step is worth when ranking harvest trips
    "sweep_stagger": 2,        # unit deadlines spread over this many final steps
    # Premium goods are held in the shed until this hour. Town shops draw at hours 16 and 20, so hours 17-20
    # see the same drained price; releasing at 17 sells ahead of rival dumps later in that window.
    "final_hold_hour": 17,
    "final_hold_room": 20,     # shed space kept free for other drops while holding
}


# ============================================================================ turn state


def g(o, k, d=None):
    """field k of an observation node, whether it is a dict or an attribute object."""
    if isinstance(o, dict):
        return o.get(k, d)
    try:
        return o[k]
    except Exception:
        return getattr(o, k, d)


class Turn:
    """What one player sees at the start of a turn, plus facts derived from it during the turn."""

    def __init__(self, obs, me_id, step):
        self.step = step
        self.day, self.hour = divmod(step, HOURS)
        self.last_day = self.day == DAYS - 1

        farms = g(obs, "farms")
        me = farms[me_id]
        opp = farms[1 - me_id] if len(farms) > 1 else None
        priv = g(obs, "private")
        market = g(obs, "market")
        town = g(obs, "town") or {}
        self.tiles = me["tiles"]
        self.rival_tiles = opp["tiles"] if opp is not None else None
        self.money = float(me["money"])
        self.shed = {k: int(v) for k, v in dict(priv["shed"]).items()}
        self.seeds = {k: int(v) for k, v in dict(priv["seeds"]).items()}
        self.units = [tuple(me["farmer"])] + [tuple(h) for h in me["hands"]]
        raw_invs = list(priv["inventories"])
        self.uitems = []
        for i in range(len(self.units)):
            inv = dict(raw_invs[i]) if i < len(raw_invs) else {}
            self.uitems.append({k: int(v) for k, v in inv.items() if int(v) > 0})
        self.minv = {k: int(v) for k, v in dict(market["inventory"]).items()}
        self.prices = {k: int(v) for k, v in dict(market["prices"]).items()}
        self.shops = list(g(town, "unlocked_shops", []) or [])
        self.n_quads = len(me["unlocked_quadrants"])
        self.hires_today = int(g(me, "hires_today", 0))

        self.animals = []     # (pos, tile)
        self.plants = []      # (pos, tile)
        self.structs = {"COOP": [], "PASTURE": []}  # empty pens
        self.weeds = []
        self.empties = []
        self.n_animal = {a: 0 for a in ANIMALS}
        self.n_crop = {c: 0 for c in CROPS}
        for y in range(N):
            row = self.tiles[y]
            for x in range(N):
                t = row[x]
                p = (x, y)
                if t is None:
                    self.empties.append(p)
                elif t == "LOCKED":
                    continue
                elif isinstance(t, dict):
                    k = t.get("kind")
                    if k == "PLANT":
                        self.plants.append((p, t))
                        self.n_crop[t["crop"]] += 1
                    elif k == "WEED":
                        self.weeds.append(p)
                    elif t.get("animal"):
                        self.animals.append((p, t))
                        self.n_animal[t["animal"]] += 1
                    elif k in self.structs:
                        self.structs[k].append(p)

        # rival farm: head counts and the yield waiting on each tile, {pos: (item, units, is_animal)}
        self.rival_animal = {a: 0 for a in ANIMALS}
        self.rival_crop = {c: 0 for c in CROPS}
        self.rival_goods = None
        if opp is not None:
            self.rival_goods = {}
            for y in range(N):
                row = self.rival_tiles[y]
                for x in range(N):
                    t = row[x]
                    if not isinstance(t, dict):
                        continue
                    if t.get("animal"):
                        self.rival_animal[t["animal"]] += 1
                        product = ANIMALS[t["animal"]]["product"]
                        self.rival_goods[(x, y)] = (product, int(t.get("yield_units", 0)), True)
                    elif t.get("kind") == "PLANT":
                        self.rival_crop[t["crop"]] += 1
                        self.rival_goods[(x, y)] = (t["crop"], int(t.get("yield_units", 0)), False)

        self.carried = {}
        for it in self.uitems:
            for k, v in it.items():
                self.carried[k] = self.carried.get(k, 0) + v
        self.stock = {a: self.shed.get(a, 0) + self.carried.get(a, 0) for a in ANIMALS}  # bought, not placed
        self.have = {a: self.n_animal[a] + self.stock[a] for a in ANIMALS}
        self.fert_price = self.prices["FERTILIZER"]
        self.wheat_price = self.prices["WHEAT"]
        self.rival_hold = {}
        self.rival_ripe = {}

    def held(self, item):
        return self.shed.get(item, 0) + self.carried.get(item, 0)


def track_rival(rv, goods, step, minv, shops):
    """Update the rival's harvested-but-unsold stock and return (hold, ripe) as {item: units}.

    A drop of visible yield on a rival tile is a harvest; units the market gained beyond our own sales and
    the town's draws were sold by the rival. Holdings that stay unchanged for 30 steps are dropped, since
    tracking drift and destroyed goods would otherwise linger."""
    hold = rv["hold"]
    if goods is not None:
        prev = rv.get("tiles")
        if prev is not None and rv.get("step") == step - 1:
            for pos, (item, units, is_animal) in prev.items():
                if units <= 0:
                    continue
                cur = goods.get(pos)
                if cur is None or cur[0] != item:
                    if not is_animal:
                        hold[item] = hold.get(item, 0) + units
                elif cur[1] < units:
                    hold[item] = hold.get(item, 0) + (units - cur[1])
            prev_step = rv["step"]
            prev_shops = rv.get("shops", [])
            prev_inv = rv.get("inv", {})
            my_sold = rv.get("my_sold", {})
            for item in RIVAL_TRACKED:
                sold = minv.get(item, 0) - prev_inv.get(item, 0) + town_draw(item, prev_step, prev_shops) \
                    - my_sold.get(item, 0)
                if sold > 0:
                    hold[item] = max(0, hold.get(item, 0) - sold)
        rv["tiles"] = goods
        changed = rv.setdefault("changed", {})
        seen = rv.setdefault("seen", {})
        for item, v in list(hold.items()):
            if v != seen.get(item):
                seen[item] = v
                changed[item] = step
            elif v > 0 and step - changed.get(item, step) > 30:
                hold[item] = 0
                seen[item] = 0
    rv["step"] = step
    rv["inv"] = dict(minv)
    rv["shops"] = list(shops)
    ripe = {}
    if goods is not None:
        for (item, units, _) in goods.values():
            if units > 0:
                ripe[item] = ripe.get(item, 0) + units
    return hold, ripe


def own_market_sales(orders, shed_after, prices):
    """units our sell orders add to market inventory (sales at the $1 floor add none)."""
    sold = {}
    for o in orders:
        if o[0] == "SELL":
            item = o[1]
            n = min(int(o[2]), shed_after.get(item, 0) - sold.get(item, 0))
            if prices.get(item, 0) <= 1:
                n = 0
            sold[item] = sold.get(item, 0) + max(0, n)
    return sold


# ============================================================================ opening


def opening_plan(P, money, wheat_price):
    """Split the starting cash into the day-0 purchases.

    Fixed commitments come first: the day-0 hands, the opening herd, and today's ration for the sheep,
    whose first wool is capped by five care days with none to spare (cows skip their first feed, see
    animal_needs). Tomorrow's hires are kept in cash. Melon seeds get what is left, up to melon_n;
    opening_orders() spends the rest on wheat seed."""
    feed = P["open_sheep"]
    cash = money - fib_sum(0, P["open_hires"]) - fib_sum(0, P["hires"][1])
    cash -= P["open_cows"] * ANIMALS["COW"]["cost"] + P["open_sheep"] * ANIMALS["SHEEP"]["cost"]
    cash -= feed * (wheat_price + 1)
    melons = int(max(0, min(P["melon_n"], cash // CROPS["MELON"]["seed"])))
    cash -= melons * CROPS["MELON"]["seed"]
    return {"melons": melons, "feed": feed, "cash": cash}


def opening_orders(P, plan, n_rim):
    """step-0 market orders; leftover cash buys wheat seed for the outer rim."""
    n_wheat = int(max(0, min(n_rim, (plan["cash"] - 3) // CROPS["WHEAT"]["seed"])))
    out = [["HIRE"]] * P["open_hires"]
    if P["open_cows"] > 0:
        out.append(["BUY_ANIMAL", "COW", P["open_cows"]])
    if P["open_sheep"] > 0:
        out.append(["BUY_ANIMAL", "SHEEP", P["open_sheep"]])
    if plan["melons"] > 0:
        out.append(["BUY_SEED", "MELON", plan["melons"]])
    out.append(["BUY_PRODUCT", "WHEAT", plan["feed"]])
    if n_wheat > 0:
        out.append(["BUY_SEED", "WHEAT", n_wheat])
    return out


def setup_home(t, P, mem):
    """The day-0 layout of the home quadrant (computed once per game) and today's melon tiles."""
    home = mem.get("home")
    if home is None:
        if t.step == 0:
            plan0 = opening_plan(P, t.money, t.wheat_price)
        else:
            plan0 = {"melons": P["melon_n"], "feed": 0, "cash": 0}
        # the pens bought on days 1-5 sit outside the melon ring: melons keep the closer tiles for the race
        home = home_layout([("pens", P["open_cows"] + P["open_sheep"]), ("melons", plan0["melons"]),
                            ("spare", P["open_spare"])])
        # the top-up tiles are the far corner of the rim, which day-0 cash never reaches with wheat
        far = sorted(home["rim"], key=lambda q: (-dist(q, HOME_DOOR), q))[:max(0, P["melon_topup"])]
        home["topup"] = far
        home["rim"] = [q for q in home["rim"] if q not in far]
        mem["home"] = home
        mem["open_plan"] = plan0
    melon_tiles = set(home["melons"])
    if t.day >= 1 and "topup_on" not in mem:
        mem["topup_on"] = t.rival_tiles is not None and t.rival_crop["MELON"] <= P["topup_rival_max"]
    if mem.get("topup_on"):
        melon_tiles |= set(home["topup"])
    t.home = home
    t.melon_tiles = melon_tiles


# ============================================================================ planning


def animal_needs(t, P):
    """Today's work per animal as {pos: (animal, need_feed, need_care, collect, must_harvest, want_harvest,
    days_unfed, produces_today, banked_care, fed)} and the number of animals still to feed."""
    day = t.day
    needs = {}
    feed_jobs = 0
    for (p, tile) in t.animals:
        a = tile["animal"]
        ad = ANIMALS[a]
        product = ad["product"]
        maint = day >= 8 and t.prices[product] < P["maint_frac"] * BASE_PRICE[product]
        first = tile["placed_day"] + ad["fyd"] - 1
        iv = ad["interval"]
        prod_today = day >= first and (day - first) % iv == 0
        last_prod = None if first > DAYS - 2 else first + ((DAYS - 2 - first) // iv) * iv
        pend = int(tile.get("pending_care_bonus", 0) or 0)
        unfed = int(tile.get("consecutive_unfed", 0))
        fed = bool(tile.get("fed_today"))
        cared = bool(tile.get("cared_today"))
        yu = int(tile.get("yield_units", 0))
        future = last_prod is not None and day <= last_prod
        bank_after = 0 if prod_today else pend
        care_useful = (not maint and last_prod is not None and day < last_prod and (1 + bank_after) < ad["cap"])
        need_feed = not fed and future and (care_useful or (prod_today and pend > 0) or unfed >= 1)
        need_care = care_useful and not cared
        # a cow's first yield is capped at 1 + 5 banked care days, and 7 days precede it, so its placement
        # day can go unfed and uncared (it cannot starve on day one): saves a ration and two actions
        if a == "COW" and day == tile["placed_day"] and unfed == 0 and not fed:
            need_feed = False
            need_care = False
        exp_prod = (1 + (pend if (fed or need_feed) else 0)) if prod_today else 0
        must_harv = yu > 0 and prod_today and yu + exp_prod > ad["cap"]
        if yu > 0 and unfed >= 1 and not fed and not need_feed:
            must_harv = True  # left unfed it escapes tonight and its held yield is lost with it
        want_harv = False
        if yu > 0:
            thr = 1 if day <= P["early_drop_day"] else {"SHEEP": 4, "COW": 4, "GOOSE": 3}[a]
            if yu >= thr or (last_prod is not None and day > last_prod) or day >= DAYS - 2:
                want_harv = True
            if maint and not must_harv and day < DAYS - 2:
                want_harv = yu >= ad["cap"] - 1
        collect = bool(tile.get("fertilizer_available"))
        if need_feed:
            feed_jobs += 1
        needs[p] = (a, need_feed, need_care, collect, must_harv, want_harv, unfed, prod_today, pend, fed)
    return needs, feed_jobs


def herd_book_targets(t, P):
    """Species counts worth owning. Animals are added one at a time, best species first, while the forecast
    revenue of the product (net of its own price impact) plus the fertilizer stream pays for the animal,
    its feed and its upkeep."""
    day = t.day
    placed = day if t.hour <= P["herd_place_hour"] else day + 1
    upkeep_days = max(0, DAYS - 2 - placed)
    # fertilizer has no town demand: its price only falls, by 0.2 per unit either farm sells
    drop = 0.2 * (P["fert_sell_share"] * (len(t.animals) + sum(t.stock.values())) + sum(t.rival_animal.values()))
    fert_income = sum(max(1.0, t.fert_price - drop * (d - day)) for d in range(placed + 1, DAYS - 1))
    books = {}
    for a, ad in ANIMALS.items():
        prod = ad["product"]
        ours = farm_sales(t.tiles, prod, day)
        if t.stock[a]:
            animal_sales(ours, a, placed, day, n=t.stock[a])
        theirs = farm_sales(t.rival_tiles, prod, day) if t.rival_tiles is not None else {}
        ours[day] = ours.get(day, 0) + t.held(prod)
        theirs[day] = theirs.get(day, 0) + t.rival_hold.get(prod, 0)
        demand = town_demand(prod, day, t.hour, t.shops, P["book_unlock_w"])
        books[a] = MarketBook(prod, day, t.minv[prod], demand, ours, theirs)
    caps = {"SHEEP": P["sheep_cap"], "COW": P["cow_cap"], "GOOSE": P["goose_cap"]}
    out = dict(t.have)
    while sum(out.values()) < P["animal_cap"]:
        best = None
        for a, ad in ANIMALS.items():
            if out[a] >= caps[a]:
                continue
            extra = animal_sales({}, a, placed, day)
            v = (books[a].gain(extra, P["herd_rival_weight"]) + fert_income - ad["cost"]
                 - upkeep_days * (t.wheat_price + P["herd_labor"]))
            if v > 0 and (best is None or v > best[0]):
                best = (v, a, extra)
        if best is None:
            break
        books[best[1]].commit(best[2])
        out[best[1]] += 1
    return out


def herd_targets(t, P):
    day = t.day
    if day < P["herd_day"]:
        tgt = {"COW": P["open_cows"], "SHEEP": P["open_sheep"], "GOOSE": 0}
        if day >= 1:
            tgt["COW"] += P["early_cows"]
    else:
        tgt = herd_book_targets(t, P)
    last_buy = {"COW": P["cow_last"], "SHEEP": P["sheep_last"], "GOOSE": P["goose_last"]}
    for a, ad in ANIMALS.items():
        product = ad["product"]
        if day > last_buy[a] or (day >= P["herd_day"] and t.prices[product] < 0.75 * BASE_PRICE[product]):
            tgt[a] = min(tgt[a], t.have[a])
    if sum(tgt.values()) > P["animal_cap"]:
        for a in ("GOOSE", "COW", "SHEEP"):  # lowest-value species first
            excess = sum(tgt.values()) - P["animal_cap"]
            if excess <= 0:
                break
            tgt[a] -= min(excess, max(0, tgt[a] - t.have[a]))
    return tgt


def book_additions(t, P, crop, cap):
    """how many more plants of `crop` are worth sowing today, one at a time, each valued at the forecast
    prices of its own sale days and charged seed, fertilizer, labour and the tile's wheat value."""
    day = t.day
    ours = farm_sales(t.tiles, crop, day)
    held = t.held(crop)
    if held:
        ours[day] = ours.get(day, 0) + held
    theirs = farm_sales(t.rival_tiles, crop, day) if t.rival_tiles is not None else {}
    if crop == "STRAWBERRY" and t.rival_tiles is not None and day < P["rival_straw_day"]:
        # plantings the rival has still to make, spread over the days up to its assumed last sowing day
        more = max(0, P["rival_straw_final"] - t.rival_crop[crop])
        sow_days = list(range(day + 1, P["rival_straw_day"] + 1))
        for sd in sow_days:
            crop_sales(theirs, crop, sd, day, more / float(len(sow_days)))
    demand = town_demand(crop, day, t.hour, t.shops, P["book_unlock_w"])
    book = MarketBook(crop, day, t.minv[crop], demand, ours, theirs)
    n_fert, labor, life = BOOK_UPKEEP[crop]
    cost = CROPS[crop]["seed"] + n_fert * min(t.fert_price, P["book_fert_cap"]) + labor * P["book_labor"]
    alt = P["book_alt"] * min(life, DAYS - day)
    n = 0
    while n < cap:
        extra = crop_sales({}, crop, day, day)
        if not extra or book.gain(extra) - cost - alt < 0:
            break
        book.commit(extra)
        n += 1
    return n


# units above neutral inventory the tomato / carrot markets absorb at a fair price
ROOM_SLACK = {"TOMATO": 20, "CARROT": 40}


def crop_room(t, P):
    """units of tomatoes and carrots the market can still absorb at a fair price after both farms' pipelines."""
    room = {}
    for crop in ("TOMATO", "CARROT"):
        dem = sum(town_demand(crop, t.day, 0, t.shops, P["w_future"]).values())
        mine = remaining_supply(t.tiles, crop, t.day)
        theirs = remaining_supply(t.rival_tiles, crop, t.day) if t.rival_tiles is not None else 0.0
        room[crop] = P["room_mult"] * (ROOM_SLACK[crop] + (NEUTRAL_INV - t.minv[crop])) + dem - theirs - mine
    return room


class Plan:
    """Purchases and tile roles decided this turn."""

    def __init__(self):
        self.hire_target = 0
        self.hire_cost = 0
        self.land_buy = False
        self.wheat_buy = 0
        self.buy_animals = {a: 0 for a in ANIMALS}
        self.seed_buy = {c: 0 for c in CROPS}
        self.tiles = {}           # pos -> ("BUILD", kind) | ("PLANT", crop)
        self.early_wheat = 0      # wheat harvested at age 2 to free tiles for premium crops
        self.wheat_reserve = 0    # shed stock kept back from sale
        self.fert_reserve = 0
        self.pre_sell = {}        # what the shed would sell before this turn's drops

    def spend(self, t):
        """coins this turn's orders will spend."""
        total = self.hire_cost
        total += (LAND_PRICES[t.n_quads - 1] if self.land_buy else 0) + self.wheat_buy * (t.wheat_price + 2)
        total += sum(self.buy_animals[a] * ANIMALS[a]["cost"] for a in ANIMALS)
        total += sum(self.seed_buy[c] * CROPS[c]["seed"] for c in CROPS)
        return total


def sellable(shed_state, wheat_reserve, fert_reserve):
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


def fertilizer_need(t, fert_on_wheat):
    """fertilizer our crops will want over the next day or two."""
    day = t.day
    need = 0
    for _, tile in t.plants:
        crop = tile["crop"]
        age = day - tile["planted_day"]
        fed_until = tile.get("fertilized_until_day", -1)
        if crop == "STRAWBERRY" and age + 2 >= 9 and age <= 13:
            if fed_until < day + 1:
                need += 1
        elif crop == "TOMATO" and age + 2 >= 7 and age <= 10:
            if fed_until < day + 1:
                need += 1
        elif crop in ("WHEAT", "CARROT") and fert_on_wheat and age <= 2:
            if fed_until < day:
                need += 1
    if fert_on_wheat:
        need += len(t.empties) // 3
    return need


def make_plan(t, P, mem, feed_jobs, fert_on_wheat):
    day, hour = t.day, t.hour
    pl = Plan()
    sched = P["hires"]
    pl.hire_target = sched[min(day, len(sched) - 1)]
    if hour <= 3 and t.hires_today < pl.hire_target:
        pl.hire_cost = fib_sum(t.hires_today, pl.hire_target)

    wheat_need = feed_jobs - t.held("WHEAT")
    if hour <= 20 and wheat_need > 0:
        pl.wheat_buy = wheat_need + (0 if day < 3 else (1 if day < 8 else 2))
    pl.fert_reserve = max(0, fertilizer_need(t, fert_on_wheat) - t.carried.get("FERTILIZER", 0))
    pl.wheat_reserve = max(0, feed_jobs - t.carried.get("WHEAT", 0))
    if day == 0:
        pl.wheat_reserve = t.shed.get("WHEAT", 0)  # day-0 wheat includes tomorrow's morning ration
    herd_size = len(t.animals) + sum(t.stock.values())
    if hour >= P["wheat_keep_hour"]:
        # keep tomorrow's feed instead of selling tonight and buying back at hour 0
        pl.wheat_reserve += herd_size + 2

    # budget: cash plus most of what the shed sells this turn, minus this turn's fixed spending
    pl.pre_sell = sellable(t.shed, pl.wheat_reserve, pl.fert_reserve)
    est_sales = 0.0
    for item, n in pl.pre_sell.items():
        est_sales += sell_revenue(item, t.minv[item], n)
    budget = t.money + 0.92 * est_sales
    budget -= pl.hire_cost
    budget -= pl.wheat_buy * (t.wheat_price + 2)
    if hour >= P["night_hour"]:
        # tomorrow's hires and morning feed must be affordable at hour 0
        nxt = sched[min(day + 1, len(sched) - 1)]
        budget -= fib_sum(0, nxt) + max(0, herd_size - t.shed.get("WHEAT", 0)) * (t.wheat_price + 2)

    # land: buy when affordable; when only the goods waiting on animals and ripe melons would cover it,
    # save for it and let only the surplus go to animals and seeds
    cheap_extra = 0.0  # wheat seed may still dip into the land savings
    n_extra = t.n_quads - 1
    if n_extra < 3 and P["land_first"][n_extra] <= day <= P["land_last"][n_extra]:
        price = LAND_PRICES[n_extra]
        if budget >= price:
            pl.land_buy = True
            budget -= price
        else:
            liquid = budget
            for _, tile in t.animals:
                liquid += 0.9 * int(tile.get("yield_units", 0)) * t.prices[ANIMALS[tile["animal"]]["product"]]
            for _, tile in t.plants:
                if tile["crop"] == "MELON" and day - tile["planted_day"] >= 9:
                    liquid += 0.9 * 6 * t.prices["MELON"]
            if liquid >= price:
                cheap_extra = min(price, max(0.0, budget), 250.0)
                budget -= price

    plan_tiles(t, P, mem, pl, herd_targets(t, P), budget, cheap_extra)
    return pl


def plan_tiles(t, P, mem, pl, tgt, budget, cheap_extra):
    """Pens for animals bought or to buy, then a crop for every other free tile, within the budget."""
    day = t.day
    melon_tiles = t.melon_tiles
    home_spare = t.home["spare"]
    free = sorted(t.empties + t.weeds, key=lambda p: CROP_RANK[p])
    free_set = set(free)
    unplaced = {"COOP": t.stock["GOOSE"], "PASTURE": t.stock["COW"] + t.stock["SHEEP"]}
    want_new = {a: max(0, tgt[a] - t.have[a]) for a in ANIMALS}
    plan = pl.tiles

    struct_tiles = [p for p in STRUCT_ORDER if p in free_set]
    if day == 0:
        first = t.home["pens"] + home_spare
        struct_tiles = [p for p in first if p in free_set] + [p for p in struct_tiles if p not in first]
    used = set()

    def take_struct_tile():
        for p in struct_tiles:
            if p in used or (day <= 9 and p in melon_tiles):
                continue
            used.add(p)
            return p
        return None

    for kind in ("PASTURE", "COOP"):
        for _ in range(max(0, unplaced[kind] - len(t.structs[kind]))):
            p = take_struct_tile()
            if p is None:
                break
            plan[p] = ("BUILD", kind)

    n_straw = t.n_crop["STRAWBERRY"]
    n_tom = t.n_crop["TOMATO"]
    straw_season = P["straw_first"] <= day <= P["straw_last"]
    tom_season = P["tom_first"] <= day <= P["tom_last"]
    m_wave = 0
    if P["wave_first"] <= day <= P["wave_last"]:
        m_wave = book_additions(t, P, "MELON", P["wave_cap"])
    s_target = n_straw
    if straw_season:
        s_target = min(P["straw_cap"], n_straw + book_additions(t, P, "STRAWBERRY", P["straw_cap"]))
    room = crop_room(t, P)
    t_target = min(P["tom_cap"], n_tom + int(max(0.0, room["TOMATO"]) // 8))
    if t.prices["TOMATO"] < P["tom_min_price"]:
        t_target = n_tom
    carrot_ok = room["CARROT"] > 0 and t.prices["CARROT"] > 1.25 * t.wheat_price + 3
    carrot_cap = int(max(0.0, room["CARROT"]) // 4)

    # animals: wool first when a yarn store buys it, each on a free pen or a new one
    spare_struct = {k: len(t.structs[k]) - unplaced[k] for k in t.structs}
    buy_order = ["SHEEP", "COW", "GOOSE"] if "YARN_STORE" in t.shops else ["COW", "SHEEP", "GOOSE"]
    for a in buy_order:
        kind = ANIMALS[a]["kind"]
        cost = ANIMALS[a]["cost"]
        while want_new[a] > 0 and budget >= cost:
            if spare_struct[kind] > 0:
                spare_struct[kind] -= 1
            else:
                p = take_struct_tile()
                if p is None:
                    break
                plan[p] = ("BUILD", kind)
            pl.buy_animals[a] += 1
            want_new[a] -= 1
            budget -= cost

    # tiles next to the shed stay free for animals still to come
    zone_free = [p for p in struct_tiles if p in ZONE and p in free_set and p not in plan and p not in melon_tiles]
    fut_need = sum(max(0, tgt[a] - t.have[a] - pl.buy_animals[a]) for a in ANIMALS)
    zone_hold = day < P["zone_release_day"]
    if zone_hold:
        fut_need += P["zone_margin"]
    if day > P["sheep_last"]:
        fut_need = 0
    keep = set(zone_free[:max(0, fut_need)])
    if day < P["open_spare_until"]:
        keep |= set(home_spare)
    if day == 0:
        keep |= set(t.home["topup"])  # the top-up tiles wait for the day-1 decision

    seed_buy = pl.seed_buy
    seeds_left = dict(t.seeds)
    melons_left = max(0, P["melon_n"] - mem["melons"])
    n_carrot = 0
    n_wave = 0
    crop_tiles = [p for p in free if p not in plan and p not in keep] if t.hour <= HOURS - 2 else []
    for p in crop_tiles:
        choice = None
        if day <= 1 and p in melon_tiles:
            # every melon tile is sown on day 0 (day 1 only as a fallback) and kept for melons until then
            if melons_left <= 0:
                continue
            choice = "MELON"
            melons_left -= 1
        else:
            in_zone = p in ZONE and zone_hold
            if not in_zone and straw_season and n_straw < s_target:
                choice = "STRAWBERRY"
                n_straw += 1
            # tomatoes before the melon wave: the wave is sized from the melon book alone, and in a town with
            # heavy tomato demand it would take the tiles the tomato target asked for, at a fraction of their value
            elif not in_zone and tom_season and n_tom < t_target:
                choice = "TOMATO"
                n_tom += 1
            elif not in_zone and n_wave < m_wave:
                choice = "MELON"
                n_wave += 1
            elif carrot_ok and n_carrot < carrot_cap and day <= P["carrot_last"]:
                choice = "CARROT"
                n_carrot += 1
            elif day <= P["wheat_last"]:
                choice = "WHEAT"
            elif day <= P["carrot_last"]:
                choice = "CARROT"
            else:
                continue
        if choice in ("WHEAT", "CARROT") and day >= DAYS - 4 and seeds_left.get(choice, 0) <= 0:
            # seeds still held after the last sowing day are lost: use up the other filler's seeds first
            other = "CARROT" if choice == "WHEAT" else "WHEAT"
            if seeds_left.get(other, 0) > 0:
                choice = other
        cost = CROPS[choice]["seed"]
        if seeds_left.get(choice, 0) > 0:
            seeds_left[choice] -= 1
        elif budget >= cost:
            seed_buy[choice] += 1
            budget -= cost
        elif choice in ("STRAWBERRY", "TOMATO", "MELON") and day <= 12:
            continue  # the tile waits for the premium crop
        elif budget + cheap_extra >= CROPS["WHEAT"]["seed"] and day <= P["wheat_last"]:
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

    prem_want = 0
    if straw_season:
        prem_want += max(0, s_target - n_straw)
    if tom_season:
        prem_want += max(0, t_target - n_tom)
    if prem_want > 0:
        pl.early_wheat = max(0, min(int(max(0, budget) // 60), prem_want))


# ============================================================================ labour: tile jobs


def build_jobs(t, P, needs, pl, fert_on_wheat):
    """Tile jobs as (pos, prio_full, acts_full, need_full, prio_part, acts_part, n_acts).

    The full job needs the item named by need_full in hand (wheat, fertilizer, a seed or an animal); the
    partial job is what a unit without it can still do there. Returns (jobs, fertilizer jobs, ripe melons)."""
    day, hour = t.day, t.hour
    jobs = []
    fert_jobs = 0
    melon_ripe = set()
    early_wheat = pl.early_wheat

    for (p, tile) in t.animals:
        a, need_feed, need_care, collect, must_harv, want_harv, unfed, prod_today, pend, fed = needs[p]
        prod = ANIMALS[a]["product"]
        acts_full = []
        acts_part = []
        if need_feed:
            v = 95.0
            if unfed >= 1:
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
            cv = 85.0 if day < 10 else (P["collect_base"] + P["collect_mult"] * t.fert_price)
            acts_full.append((cv, ["COLLECT_FERTILIZER"]))
            acts_part.append((cv, ["COLLECT_FERTILIZER"]))
        if must_harv:
            acts_full.append((105.0, ["HARVEST"]))
            acts_part.append((105.0, ["HARVEST"]))
        elif want_harv:
            hv = 45.0 + min(40.0, 0.05 * t.prices[prod] * tile["yield_units"])
            if day <= P["early_drop_day"]:
                hv = 90.0
            if day <= P["prem_rush_day"] and prod in ("MILK", "WOOL"):
                hv = max(hv, P["prem_harv"])
            acts_full.append((hv, ["HARVEST"]))
            acts_part.append((hv, ["HARVEST"]))
        if not acts_full:
            continue
        pf = max(v for v, _ in acts_full)
        if need_feed:
            if acts_part:
                pp, ap = max(v for v, _ in acts_part), acts_part[0][1]
            else:
                pp, ap = None, None
            jobs.append((p, pf, acts_full[0][1], "WHEAT", pp, ap, len(acts_full)))
        else:
            jobs.append((p, pf, acts_full[0][1], None, None, None, len(acts_full)))

    for kind, lst in t.structs.items():
        for p in lst:
            jobs.append((p, 150.0, ["PLACE", kind], "ANIMAL:" + kind, None, None, 3))

    for (p, tile) in t.plants:
        crop = tile["crop"]
        cd = CROPS[crop]
        age = day - tile["planted_day"]
        watered = bool(tile.get("watered_today"))
        unwatered = int(tile.get("consecutive_unwatered", 0))
        yu = int(tile.get("yield_units", 0))
        fed_until = int(tile.get("fertilized_until_day", -1))
        acts = []   # (prio, action, need)
        if not cd["ongoing"]:
            ws = (cd["mxd"] + 1) // 2
            in_window = ws <= age <= cd["mxd"]
            # a crop whose only growth-window day is the last day takes its dose early (a dose lasts 3 days),
            # so the final watering doubles without a separate trip for the fertilizer
            dose_age = age == ws or (DAYS - 1 - tile["planted_day"] == ws and age < ws)
            fert_now = crop in ("WHEAT", "CARROT") and fert_on_wheat and dose_age and fed_until < day and not watered
            if crop == "WHEAT":
                h_age = 3 if fed_until >= day - 1 else 4
                if early_wheat > 0 and age >= 2 and day <= max(P["straw_last"], P["tom_last"]):
                    h_age = 2
            elif crop == "CARROT":
                h_age = 3
            else:
                h_age = 10
            if day == DAYS - 2 and age + 1 > cd["mxd"]:
                h_age = cd["fyd"]
            ready = age >= max(h_age, cd["fyd"]) and yu > 0
            if crop == "WHEAT" and ready and h_age == 2 and age < 3:
                early_wheat -= 1
            must_w = (not watered) and unwatered >= 1 and not (ready and not in_window)
            yield_w = (not watered) and in_window and yu < cd["max_yield"]
            if fert_now:
                acts.append((92.0, ["FERTILIZE"], "FERTILIZER"))
                fert_jobs += 1
            if must_w or yield_w:
                urgent = (120.0 if crop == "MELON" else 100.0) + 2 * hour
                if must_w and not yield_w:
                    pr = 0 if ready else urgent
                else:
                    pr = 95.0 if crop == "MELON" else 88.0
                    if must_w:
                        pr = max(pr, urgent)
                if pr > 0:
                    acts.append((pr, ["WATER"], None))
            if ready:
                if crop == "MELON":
                    hv = P["melon_harv_prio"]
                    melon_ripe.add(p)
                elif crop == "WHEAT" and age >= 4:
                    hv = 110.0
                else:
                    hv = 85.0
                acts.append((hv, ["HARVEST"], None))
        else:
            fyd = cd["fyd"]
            iv = cd["interval"]
            k = age + 1 - fyd
            prod_today = k >= 0 and k % iv == 0 and (k // iv + 1) <= cd["max_yield"]
            done = age > fyd - 1 + (cd["max_yield"] - 1) * iv
            fert_active = fed_until >= day
            # a production doubles when the plant is watered and fertilized at day end, in either order
            fert_now = prod_today and not fert_active
            must_w = (not watered) and unwatered >= 1 and not done
            prod_w = (not watered) and prod_today and (fert_active or fert_now)
            if fert_now:
                prio = P["fert_prio"] if crop == "STRAWBERRY" else P["fert_prio"] - 5
                acts.append((prio, ["FERTILIZE"], "FERTILIZER"))
                fert_jobs += 1
            if must_w or prod_w:
                pr = 88.0 if prod_w else 70.0
                if prod_w and fert_active:
                    pr = P["fert_prio"] + 2 * hour  # fertilizer already invested: the water makes it count
                if must_w:
                    pr = max(pr, 100.0 + 2 * hour)
                # watering a production day only pays with fertilizer: a unit without fertilizer
                # may only do it when the plant would otherwise die tonight
                acts.append((pr, ["WATER"], None if (must_w or fert_active) else "NOFERT_SKIP"))
            if yu > 0 and age >= fyd and (yu >= 2 or done or day >= DAYS - 2
                                          or (prod_today and yu + 2 > cd["max_yield"])):
                hv = 75.0
                if prod_today and yu + (2 if fert_active else 1) > cd["max_yield"]:
                    hv = 100.0
                if done:
                    hv = P["final_harv_prio"] + 2 * hour  # decays to weed tomorrow
                acts.append((hv, ["HARVEST"], None))
            if done and yu == 0:
                acts.append((45.0, ["DIG"], None))
        if not acts:
            continue
        # actions run in list order; when the first needs fertilizer, the partial job skips it
        pf = max(a[0] for a in acts)
        first = acts[0]
        if first[2] == "FERTILIZER":
            rest = [a for a in acts[1:] if a[2] != "NOFERT_SKIP"]
            if rest:
                part = max(a[0] for a in rest) - 25.0
                jobs.append((p, pf + 5, first[1], "FERTILIZER", part, rest[0][1], len(acts)))
            else:
                jobs.append((p, pf + 5, first[1], "FERTILIZER", None, None, len(acts)))
        else:
            doable = [a for a in acts if a[2] != "NOFERT_SKIP"]
            if doable:
                jobs.append((p, max(a[0] for a in doable), doable[0][1], None, None, None, len(doable)))

    for p, (kind, what) in pl.tiles.items():
        tile = t.tiles[p[1]][p[0]]
        if isinstance(tile, dict) and tile.get("kind") == "WEED":
            jobs.append((p, 60.0, ["DIG"], None, None, None, 3))
        elif kind == "BUILD":
            jobs.append((p, 110.0, ["BUILD_" + what], None, None, None, 2))
        else:
            pv = 75.0 if what in ("STRAWBERRY", "TOMATO", "MELON") else 62.0
            jobs.append((p, pv, ["PLANT", what], "SEED:" + what, None, None, 2))
    # unplanned weeds are dug anyway: they block future use
    for p in t.weeds:
        if p not in pl.tiles and day <= DAYS - 4:
            jobs.append((p, 30.0, ["DIG"], None, None, None, 1))
    return jobs, fert_jobs, melon_ripe


def has_need(items, need, seeds):
    if need is None:
        return True
    if need.startswith("SEED:"):
        return seeds.get(need[5:], 0) > 0
    if need == "ANIMAL:COOP":
        return items.get("GOOSE", 0) > 0
    if need == "ANIMAL:PASTURE":
        return items.get("COW", 0) + items.get("SHEEP", 0) > 0
    return items.get(need, 0) > 0


# ============================================================================ labour: unit assignment


def overflow_couriers(t, P, pre_sell):
    """Units that should carry their goods to the shed now: late in the day, when carried goods plus the
    shed stock we keep would overflow the shed at the midnight auto-drop, the most loaded nearby units
    drop early so the goods get sold. Returns {unit: action} for couriers that must start walking."""
    hour = t.hour
    kept = sum(t.shed.values()) - sum(pre_sell.values())
    loads = []
    total = 0
    for i, items in enumerate(t.uitems):
        n = sum(v for k, v in items.items() if k not in ANIMALS)
        total += n
        d = dist(t.units[i], NEAR_SHED[t.units[i]])
        if n > 0 and hour + d <= HOURS - 1:
            loads.append((-n / (d + 1.0), i, n))
    couriers = set()
    excess = kept + total - SHED_CAP + P["overflow_margin"]
    if excess > 0:
        loads.sort()
        for _, i, n in loads:
            if excess <= 0:
                break
            if kept + n > SHED_CAP:
                continue
            couriers.add(i)
            excess -= n
    # a courier keeps working until it must walk back to arrive by the last hour
    out = {}
    for i in couriers:
        pos = t.units[i]
        if hour + dist(pos, NEAR_SHED[pos]) >= HOURS - 1:
            out[i] = ["DROP"] if pos in SHED_SET else [step_toward(pos, NEAR_SHED[pos])]
    return out


def assign_units(t, P, mem, pl, jobs, feed_jobs, fert_jobs, melon_ripe):
    """One action per unit: greedy over (unit, job) pairs by value minus walk, one unit per tile."""
    day, hour = t.day, t.hour
    units, uitems, prices = t.units, t.uitems, t.prices
    n_units = len(units)
    W = P["w_dist"]
    prev_tgt = mem.get("tgt", {}) if mem.get("tgt_day") == day else {}
    seed_avail = dict(t.seeds)            # for a PLANT this step
    seed_future = dict(t.seeds)           # including seeds bought this step
    for c, n in pl.seed_buy.items():
        seed_future[c] = seed_future.get(c, 0) + n
    actions = [None] * n_units
    tgt_now = {}
    shed_left = dict(t.shed)
    uncovered_feed = feed_jobs - t.carried.get("WHEAT", 0)
    uncovered_fert = fert_jobs - t.carried.get("FERTILIZER", 0)
    # animals waiting in the shed that a pen (existing or planned) can take
    open_slots = {k: len(t.structs[k]) + sum(1 for (kk, ww) in pl.tiles.values() if kk == "BUILD" and ww == k)
                  for k in t.structs}
    carried_kind = {"COOP": t.carried.get("GOOSE", 0), "PASTURE": t.carried.get("COW", 0) + t.carried.get("SHEEP", 0)}
    animal_pick = {"COOP": max(0, min(t.shed.get("GOOSE", 0), open_slots["COOP"] - carried_kind["COOP"])),
                   "PASTURE": max(0, min(t.shed.get("COW", 0) + t.shed.get("SHEEP", 0),
                                         open_slots["PASTURE"] - carried_kind["PASTURE"]))}
    early = day < P["early_drop_day"]
    crew = pl.hire_target + 1 if hour == 0 else n_units

    def drop_value(items):
        """value of dropping carried goods at the shed now."""
        sv = 0.0
        for k, n in items.items():
            if k == "WHEAT" or k in ANIMALS:
                continue
            if k == "FERTILIZER" and uncovered_fert > -3 and day >= 9:
                continue  # fertilizer in hand is needed on the crops
            sv += n * prices.get(k, 0)
        dv = 0.0
        if sv > 0:
            dv = min(130.0, 40.0 + sv / 8.0) if early else min(70.0, sv / 25.0)
        if not early:
            # steep goods the rival also holds or can harvest go to market first
            race = 0.0
            for k, n in items.items():
                if k in RACE_GOODS and t.rival_hold.get(k, 0) + t.rival_ripe.get(k, 0) > 0:
                    race += n * prices.get(k, 0)
            if race > 0:
                dv = max(dv, min(P["race_cap"], race * P["race_drop"]))
        if items.get("MELON", 0) > 0 and day <= P["rush_day"]:
            dv = max(dv, P["melon_rush"])  # carried melons reach market before the rival's glut lands
        if day <= P["prem_rush_day"] and (items.get("MILK", 0) > 0 or items.get("WOOL", 0) > 0):
            dv = max(dv, P["prem_drop"])
        return dv

    def shed_action(i):
        """best (value, action) for unit i at, or walking to, a shed tile."""
        items = uitems[i]
        best = (None, None)
        dv = drop_value(items)
        if dv > 0:
            best = (dv, ["DROP"])
        if items.get("GOOSE", 0) + items.get("COW", 0) + items.get("SHEEP", 0) == 0:
            for kind, kinds in (("PASTURE", ("SHEEP", "COW")), ("COOP", ("GOOSE",))):
                if animal_pick[kind] > 0:
                    for a in kinds:
                        if shed_left.get(a, 0) > 0:
                            if best[0] is None or 150.0 > best[0]:
                                best = (150.0, ["PICKUP", a, 1])
                            break
        if items.get("WHEAT", 0) == 0 and uncovered_feed > 0 and shed_left.get("WHEAT", 0) > 0:
            k = min(shed_left["WHEAT"], max(2, int(math.ceil(uncovered_feed / max(1, n_units, crew))) + 1))
            v = 100.0 + (2 * hour if hour > 12 else 0)
            if best[0] is None or v > best[0]:
                best = (v, ["PICKUP", "WHEAT", k])
        if items.get("FERTILIZER", 0) == 0 and uncovered_fert > 0 and shed_left.get("FERTILIZER", 0) > 0:
            k = min(shed_left["FERTILIZER"], max(2, int(math.ceil(uncovered_fert / 3.0))))
            if best[0] is None or 92.0 > best[0]:
                best = (92.0, ["PICKUP", "FERTILIZER", k])
        return best

    def take_from_shed(act):
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

    if hour >= P["overflow_hour"]:
        for i, act in overflow_couriers(t, P, pl.pre_sell).items():
            actions[i] = act

    # units standing on the shed take a pickup or drop when it beats the job on their own tile
    for i, pos in enumerate(units):
        if pos not in SHED_SET or actions[i] is not None:
            continue
        v, act = shed_action(i)
        if act is None:
            continue
        local = 0.0
        for j in jobs:
            if j[0] == pos:
                local = max(local, j[1] if has_need(uitems[i], j[3], seed_avail) else (j[4] or 0))
        if act[0] == "DROP" and v < local:
            continue
        if act[0] == "PICKUP" and act[1] in ("WHEAT", "FERTILIZER") and v < local - 20:
            continue
        actions[i] = act
        take_from_shed(act)

    pairs = []
    for i, pos in enumerate(units):
        if actions[i] is not None:
            continue
        items = uitems[i]
        pt = prev_tgt.get(i)
        for ji, (p, pf, af, nf, pp, ap, n) in enumerate(jobs):
            d = dist(pos, p)
            if hour + d > HOURS - 1:
                continue
            if has_need(items, nf, seed_future):
                v = pf
                full = True
                if nf is not None and nf.startswith("ANIMAL:"):
                    v += W * d  # placing a bought animal is worth any walk
                elif p in melon_ripe:
                    v += P["melon_rebate"] * d
            elif pp is not None:
                v = pp
                full = False
            else:
                continue
            s = v + P["burst"] * (n - 1) - W * d
            if pt == p:
                s += P["stick"]
            pairs.append((s, d, i, ji, full))
        v, act = shed_action(i)
        if act is not None:
            d = dist(pos, NEAR_SHED[pos])
            if hour + d <= HOURS - 1:
                if act[0] == "DROP" and items.get("MELON", 0) > 0 and day <= P["rush_day"]:
                    v += W * d  # melon carriers ignore the walk
                pairs.append((v - W * d, d, i, -1, act))
    pairs.sort(key=lambda z: (-z[0], z[1], z[2]))

    taken_u = set(i for i in range(n_units) if actions[i] is not None)
    taken_j = set()
    for s, d, i, ji, full in pairs:
        if i in taken_u:
            continue
        if ji == -1:
            v, act = shed_action(i)  # the shed may have been emptied by an earlier pick
            if act is None:
                continue
            taken_u.add(i)
            pos = units[i]
            if pos in SHED_SET:
                actions[i] = act
                take_from_shed(act)
            else:
                actions[i] = [step_toward(pos, NEAR_SHED[pos])]
                tgt_now[i] = NEAR_SHED[pos]
            continue
        if ji in taken_j:
            continue
        p, pf, af, nf, pp, ap, n = jobs[ji]
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
        taken_u.add(i)
        taken_j.add(ji)
        tgt_now[i] = p
        if d > 0:
            actions[i] = [step_toward(units[i], p)]
            continue
        items = uitems[i]
        act = list(act)
        if act[0] == "PLACE":
            if act[1] == "COOP":
                act = ["PLACE", "GOOSE", 1] if items.get("GOOSE", 0) > 0 else ["PASS"]
            elif items.get("SHEEP", 0) > 0:
                act = ["PLACE", "SHEEP", 1]
            elif items.get("COW", 0) > 0:
                act = ["PLACE", "COW", 1]
            else:
                act = ["PASS"]
        elif act[0] == "PLANT" and act[1] == "MELON":
            mem["melons"] += 1
        actions[i] = act

    for i in range(n_units):
        if actions[i] is None:
            actions[i] = ["PASS"]
    mem["tgt"] = tgt_now
    mem["tgt_day"] = day

    # never plant more of a crop than the seeds in hand
    planted = {}
    for i, a in enumerate(actions):
        if a[0] == "PLANT":
            c = a[1]
            planted[c] = planted.get(c, 0) + 1
            if planted[c] > t.seeds.get(c, 0):
                actions[i] = ["PASS"]
                if c == "MELON":
                    mem["melons"] -= 1
    return actions


# ============================================================================ market orders


def shed_after_actions(t, actions):
    """shed contents once this turn's drops and pickups have happened."""
    after = dict(t.shed)
    for i, a in enumerate(actions):
        if t.units[i] not in SHED_SET:
            continue
        if a[0] == "DROP":
            for k, v in t.uitems[i].items():
                after[k] = after.get(k, 0) + v
        elif a[0] == "PICKUP":
            after[a[1]] = max(0, after.get(a[1], 0) - int(a[2]))
    return after


def hold_for_later(t, P, pl, sells, shed_after):
    """Keep back the part of each batch that a later sale window is forecast to pay more for."""
    carried_all = sum(sum(it.values()) for it in t.uitems)
    room = SHED_CAP - (sum(shed_after.values()) - sum(sells.values())) - carried_all - P["hold_room"]
    cash_spare = t.money - pl.spend(t) - P["hold_cash"]
    for item in P["hold_items"]:
        n = sells.get(item, 0)
        if n <= 0 or room <= 0 or cash_spare <= 0:
            continue
        ours = farm_sales(t.tiles, item, t.day)
        theirs = farm_sales(t.rival_tiles, item, t.day) if t.rival_tiles is not None else {}
        arrivals = {d: ours.get(d, 0) + theirs.get(d, 0) for d in range(t.day + 1, DAYS)}
        soon = ours.get(t.day, 0) + theirs.get(t.day, 0) + t.carried.get(item, 0)
        now = sale_split(item, n, t.minv[item], t.step, LAST_STEP - 1, t.shops, t.rival_hold.get(item, 0), soon,
                         arrivals, P["hold_risk"], P["hold_windows"])
        held = min(n - now, room)
        if held > 0:
            cash_spare -= held * t.prices[item]
            room -= held
            sells[item] = n - held
            if sells[item] <= 0:
                del sells[item]


def midnight_overflow(t, actions, sells, shed_after):
    """At the last hour everything carried is dumped into the shed: sell what would not fit."""
    carried_after = sum(sum(it.values()) for it in t.uitems)
    for i, a in enumerate(actions):
        if a[0] == "DROP" and t.units[i] in SHED_SET:
            carried_after -= sum(t.uitems[i].values())
    excess = sum(shed_after.values()) - sum(sells.values()) + carried_after - SHED_CAP
    for item in DUMP_ORDER:
        if excess <= 0:
            break
        k = min(shed_after.get(item, 0) - sells.get(item, 0), excess)
        if k > 0:
            sells[item] = sells.get(item, 0) + k
            excess -= k


def race_order(steep, rival_hold, minv):
    """Order our steep sells against the rival's. Both order lists run slot by slot, so a product listed
    before the rival's slot for it sells entirely ahead of the rival's batch. The rival is assumed to list
    its tracked holdings steepest first; the permutation with the largest expected gain wins."""
    rival_items = [it for it in STEEP if rival_hold.get(it, 0) > 0]
    rival_slot = {it: k for k, it in enumerate(rival_items)}
    gain = {}
    for o in steep:
        item = o[1]
        if item in rival_slot:
            inv = minv[item]
            gain[item] = sell_revenue(item, inv, o[2]) - sell_revenue(item, inv + rival_hold[item], o[2])
    if not gain:
        return steep
    best_v, best_perm = None, None
    for perm in itertools.permutations(range(len(steep))):
        v = 0.0
        for slot, k in enumerate(perm):
            item = steep[k][1]
            if item in gain:
                r = rival_slot[item]
                v += gain[item] * (1.0 if slot < r else (0.5 if slot == r else 0.0))
        if best_v is None or v > best_v + 1e-9:
            best_v, best_perm = v, perm
    return [steep[k] for k in best_perm]


def sell_orders(t, sells):
    """sell orders split into steep and cheap goods, steep ones race-ordered at hour 0."""
    steep = []
    cheap = []
    for item in SELL_ORDER:
        n = sells.get(item, 0)
        if n > 0:
            (steep if item in STEEP else cheap).append(["SELL", item, n])
    if t.hour == 0 and len(steep) >= 2:
        steep = race_order(steep, t.rival_hold, t.minv)
    return steep, cheap


def hire_orders(t, hire_target):
    if t.hour <= 3 and t.hires_today < hire_target:
        return [["HIRE"]] * (hire_target - t.hires_today)
    return []


def combine_orders(steep, cheap, hires, buys):
    """over the order cap, priority is steep sells, hires, cheap sells, buys."""
    if len(steep) + len(hires) + len(cheap) + len(buys) > MAX_ORDERS:
        room = MAX_ORDERS - len(steep)
        h = hires[:max(0, room)]
        room -= len(h)
        c = cheap[:max(0, room)]
        room -= len(c)
        orders = steep + h + c + buys[:max(0, room)]
    else:
        orders = steep + cheap + hires + buys
    return orders[:MAX_ORDERS]


def market_orders(t, P, pl, actions, shed_after):
    sells = sellable(shed_after, pl.wheat_reserve, pl.fert_reserve)
    hold_for_later(t, P, pl, sells, shed_after)
    if t.hour == HOURS - 1:
        midnight_overflow(t, actions, sells, shed_after)
    steep, cheap = sell_orders(t, sells)
    buys = []
    if pl.land_buy:
        buys.append(["BUY_LAND"])
    for a in ("SHEEP", "COW", "GOOSE"):
        if pl.buy_animals[a] > 0:
            buys.append(["BUY_ANIMAL", a, pl.buy_animals[a]])
    if pl.wheat_buy > 0:
        buys.append(["BUY_PRODUCT", "WHEAT", pl.wheat_buy])
    for c in ("MELON", "STRAWBERRY", "TOMATO", "WHEAT", "CARROT"):
        if pl.seed_buy[c] > 0:
            buys.append(["BUY_SEED", c, pl.seed_buy[c]])
    return combine_orders(steep, cheap, hire_orders(t, pl.hire_target), buys)


# ============================================================================ last day


def sweep_tasks(day, tiles, prices):
    """Last-day work per tile as {pos: [(n_actions, coins, first_action)]}.

    Nothing produces after the final night, so only work that ends in goods in hand counts: harvests, a
    last watering inside a crop's growth window just before its harvest, and fertilizer collection."""
    fert_v = max(1, prices.get("FERTILIZER", 1))
    tasks = {}
    for y in range(N):
        row = tiles[y]
        for x in range(N):
            t = row[x]
            if not isinstance(t, dict):
                continue
            opts = []
            if t.get("kind") == "PLANT":
                crop = t["crop"]
                cd = CROPS[crop]
                age = day - t["planted_day"]
                yu = int(t.get("yield_units", 0))
                if yu <= 0 or age < cd["fyd"]:
                    continue
                pr = max(1, prices.get(crop, 1))
                opts.append((1, yu * pr, ["HARVEST"]))
                if (not cd["ongoing"] and (cd["mxd"] + 1) // 2 <= age <= cd["mxd"] and not t.get("watered_today")
                        and yu < cd["max_yield"]):
                    bonus = 2 if t.get("fertilized_until_day", -1) >= day else 1
                    opts.append((2, min(cd["max_yield"], yu + bonus) * pr, ["WATER"]))
            elif t.get("animal"):
                yu = int(t.get("yield_units", 0))
                collect = bool(t.get("fertilizer_available"))
                if yu > 0:
                    hv = yu * max(1, prices.get(ANIMALS[t["animal"]]["product"], 1))
                    opts.append((1, hv, ["HARVEST"]))
                    if collect:
                        opts.append((2, hv + fert_v, ["HARVEST"]))
                elif collect:
                    opts.append((1, fert_v, ["COLLECT_FERTILIZER"]))
            if opts:
                tasks[(x, y)] = opts
    return tasks


def final_sweep(t, P, mem):
    """Unit actions for the last day: collect the most coins that can still reach the shed by the final step.

    A unit takes a task only if it can finish it and walk back to drop before its deadline, so nothing is
    carried past the end. Tasks are assigned greedily by coins minus a per-step charge for the unit's time.
    Deadlines are staggered over the last steps so the final drops do not overflow the shed."""
    units, step = t.units, t.step
    tasks = sweep_tasks(t.day, t.tiles, t.prices)
    lam = P["sweep_step_coins"]
    prev = mem.get("sweep_tgt", {})
    pairs = []
    for i, pos in enumerate(units):
        deadline = LAST_STEP - (i % P["sweep_stagger"])
        for p, opts in tasks.items():
            d = dist(pos, p)
            slack = deadline - step - d - SHED_DIST[p]
            best = None
            for k, val, act in opts:
                if k <= slack:
                    s = val - lam * (d + k)
                    if best is None or s > best[0]:
                        best = (s, act)
            if best is None:
                continue
            s = best[0] + (P["stick"] if prev.get(i) == p else 0.0)
            pairs.append((s, d, i, p, best[1]))
    pairs.sort(key=lambda z: (-z[0], z[1], z[2]))
    actions = [None] * len(units)
    taken = set()
    tgt = {}
    for s, d, i, p, act in pairs:
        if actions[i] is not None or p in taken:
            continue
        taken.add(p)
        tgt[i] = p
        actions[i] = list(act) if d == 0 else [step_toward(units[i], p)]
    for i, pos in enumerate(units):
        if actions[i] is not None:
            continue
        if any(k in PRODUCTS for k in t.uitems[i]):
            actions[i] = ["DROP"] if pos in SHED_SET else [step_toward(pos, NEAR_SHED[pos])]
        else:
            actions[i] = ["PASS"]
    mem["sweep_tgt"] = tgt
    return actions


def last_day_orders(t, P, shed_after):
    """Sell everything, except that premium goods wait in the shed until final_hold_hour: town shops keep
    draining the market while rivals hold theirs for a late dump, and ours go out together just before it."""
    sells = {item: shed_after[item] for item in PRODUCTS if shed_after.get(item, 0) > 0}
    if t.hour < P["final_hold_hour"]:
        space = SHED_CAP - P["final_hold_room"]
        for item in LAST_DAY_HOLD:
            if item in sells:
                keep = min(sells[item], max(0, space))
                space -= keep
                sells[item] -= keep
                if sells[item] <= 0:
                    del sells[item]
    steep, cheap = sell_orders(t, sells)
    sched = P["hires"]
    return combine_orders(steep, cheap, hire_orders(t, sched[min(t.day, len(sched) - 1)]), [])


# ============================================================================ turn


def _act(obs, P, MEM):
    me_id = int(g(obs, "player", 0) or 0)
    step = int(g(obs, "step", 0) or 0)
    mem = MEM.get(me_id)
    if mem is None or step == 0 or mem.get("last_step", -1) >= step:
        mem = {"melons": 0}
        MEM[me_id] = mem
    mem["last_step"] = step

    t = Turn(obs, me_id, step)
    rv = mem.setdefault("rival", {"hold": {}})
    t.rival_hold, t.rival_ripe = track_rival(rv, t.rival_goods, step, t.minv, t.shops)

    if t.last_day:
        actions = final_sweep(t, P, mem)
        shed_after = shed_after_actions(t, actions)
        orders = last_day_orders(t, P, shed_after)
    else:
        setup_home(t, P, mem)
        fert_on_wheat = t.fert_price < P["fert_wheat_ratio"] * t.wheat_price
        needs, feed_jobs = animal_needs(t, P)
        pl = make_plan(t, P, mem, feed_jobs, fert_on_wheat)
        jobs, fert_jobs, melon_ripe = build_jobs(t, P, needs, pl, fert_on_wheat)
        actions = assign_units(t, P, mem, pl, jobs, feed_jobs, fert_jobs, melon_ripe)
        shed_after = shed_after_actions(t, actions)
        orders = market_orders(t, P, pl, actions, shed_after)
        if step == 0:
            orders = opening_orders(P, mem["open_plan"], len(t.home["rim"]))
    rv["my_sold"] = own_market_sales(orders, shed_after, t.prices)
    return {"farmer": actions[0], "hands": actions[1:], "market": orders}


def make_agent(params=None):
    P = dict(DEFAULT_PARAMS)
    if params:
        P.update(params)
    MEM = {}

    def act(obs, config=None):
        try:
            return _act(obs, P, MEM)
        except Exception:
            return {"farmer": ["PASS"], "hands": [], "market": []}

    return act


_AGENT = make_agent()


def agent(obs, config=None):
    return _AGENT(obs, config)
