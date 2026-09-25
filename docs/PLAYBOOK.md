# Kaggriculture top-10 playbook (consensus of 12 replay analysts, exact re-simulations)

Target: 115-145k coins/game vs top agents. Our v4 (`main.py`) gets ~69k (panel: 10/104 wins vs frozen top-20 tapes, 69.5k vs 118.8k).
Top-13 mean revenue 174.6k: Strawberry 41.1k (24%), Wool 37.9k (22%), Milk 28.6k (16%), Melon 14.8k, Fert 12.3k (net), Wheat 9.9k, Egg 6.8k, Tomato 6.1k.
Costs: seeds 6.9k, animals ~9.8k, land 4.5k, hires 6.3k. Revenue by phase: D0-9 16k, D10-19 73k, D20-29 86k (8.6k/day late).
Ours: 88k revenue, 0 strawberry, 0 tomato, 3.4k revenue D0-9.

## Day 0 — all-in (template shared by ~8 top teams)
- Step 0 market: buy 2 cows + 3 sheep (or 3 cows + 2 sheep), 6 melon seeds (+4 more on D1), ~10 wheat seeds, ~4 wheat product for feed, hire 4 hands. ~$0-10 left at end of D0.
- Build 5 PASTURES on tiles ringing the shed, starting with (4,4) (the shed-access tile in NW), then (3,4),(4,3),(3,3),(2,4)/(4,2)... Place animals immediately (farmer + hands PICKUP from shed, PLACE on pasture).
- FEED + CARE every animal every day from D0 → care bank fills → first yields capped: 6 wool/sheep available D6 (18 wool ≈ $3.5k), 6 milk/cow on D8 (12 milk ≈ $2-2.7k).
  (Sheep placed day d produce at end of days d+5, d+8, ... ; cow at d+7, d+9, ...; bank adds 1 per fed+cared day, paid at next production if fed that day; product caps at 6 held (goose 4)).
- Plant melons + wheat on remaining NW tiles.

## D1-D9 — compounding
- COLLECT_FERTILIZER from every animal every day (≈5/day) and SELL at ~$95-100 (price drops 0.2/unit sold). Each animal repays its cost in 3-5 days from fertilizer alone. Plow every coin back: 4 more melons D1, ~10 strawberry seeds D2-D4, more animals (≈1 cow/day), keep cash near $0.
- Land: NE on D6 (right after wool sells, hour ~5), SW on D8-9 (milk money), SE ($4000) on D10 right after selling 36-48 melons (optional; bought in 3/4 wins but Boey never buys SE — decide by cash/labor).
- Hands: 4 on D0-D5, ramp to 11-13 by D10-11 (hire cost fib; 12 hires ≈ $376/day). 0-2% idle turns.

## D10-D29 — saturated farm (all ~100 tiles in use by D12)
- ~20-25 animals, ALL fed + cared daily (incl. geese: 2 eggs/day vs 1). Pick species by shops unlocked (visible in obs.town.unlocked_shops):
  YARN_STORE → sheep (12-18); PIZZA/ICE_CREAM/SMOOTHIE → cows (8-14); BAKERY/BRUNCH (no milk/wool demand) → geese. Buy animals the day the shop unlocks.
  Sheep placed on day 11 get 5 harvests (17,20,23,26,29) vs 4 if placed day 12.
- STRAWBERRIES: 26-45 plants, all planted before ~D13. Calendar (planted day d, age a = day-d):
  water ages 0,2,4,6,8 (every other day is enough to survive), then 9, 11, 13, 15 (production days); FERTILIZE at age 9 (covers ages 9-11) and 13 (covers 13-15) → every production doubled → 8 berries/plant instead of 4. Productions at end of ages 9,11,13,15 (available ages 10,12,14,16). yield cap is 4 → harvest at ages 12 and 16 (or each production). Dig at 16+ when empty (decays to weed otherwise).
- TOMATOES: winners hold ~10 tomato tiles by D20 (pizza shop / farmers market demand, hinge price → sells ~$114 when others don't grow them). Productions at end of ages 7..10 (first_yield_day 8, interval 1, 4 productions), fertilize+water → 2 each.
- WHEAT filler (fertilized): plant+water age 0, fertilize+water age 2, water age 3, harvest age 3 → 5 wheat in 3 days. Grow own feed wheat (don't buy it at $40).
- MELONS: only the early batch (10). Water ages 0,2,4 then daily 6-10, harvest age 10 → 6 each. Melon pool is small (crashes after ~158 units combined) — sell the moment harvested (first seller wins; Boey sells D10 hour 7).
- When a product's price crashes: feed that species only every other day (keeps alive, no care), stop buying more, or let escape.
- Fertilizer: collect on ~96% of animal-days; sell while price high (early), use on strawberries/wheat/tomatoes from ~D11.

## Logistics (labor is the bottleneck; top: 42% moves / 47% productive; ours 59% / 35%)
- Animals ring the shed (avg 1.9 tiles away; 72% within 2 tiles); crops in solid blocks at the edges.
- Each visit is a burst on one tile: animals FEED→CARE→COLLECT_FERTILIZER(→HARVEST); wheat harvest day WATER→HARVEST→PLANT→WATER; strawberries FERTILIZE→WATER.
- Nearest-work sweep (no fixed zones). Load wheat/fertilizer at morning spawn (units spawn at shed; hours 1-2 pickups).
- Water only when needed (survival: never 2 unwatered days in a row; bonus days: window for one-time crops, production days for ongoing).
- No mid-day unload trips unless standing at the shed; shed cap 100 → at hour 23 sell exactly what the midnight drop would destroy (overflow guard). End-of-day auto drop moves carried items into the shed.
- 12-13 units get ~160-176 productive actions/day (ours ~100).

## Market
- Put steep-price goods FIRST in the order list (wool, milk, strawberry, melon), HIREs after sells: +1.2-2.6k/game margin swing. Both players' lists run in lockstep per slot.
- Sell premium goods as soon as they reach the shed (holding for price loses; every sale is also denial).
- Wheat tick timing (buy last at hours 0,4,8,12,16,20, sell next step) ≈ +0.7-0.9k — optional.
- NOOP padding / 1-unit buy-sell churn = worthless.
- Endgame: care stops D27-28 (care on day 28+ banks nothing useful), no feeding D29, only wheat/carrots replanted D25+, SELL everything by step 718 (last processed step; day 29 hour 22).

## Traps (from failed prototypes)
- Capacity must be sized to demand: 77 strawberries with one berry shop collapsed to $1 (score 3.9k). Expected season town consumption split between both players: wheat 525, strawberry 426, milk 327, carrot 327, egg/tomato/wool 228 each, melon 30.
- More hands / earlier land alone did not help when the planner filled space with geese+wheat and bought wheat at $40.
- Carrying all produce with no drops broke early cash flow; protect melon harvest (sell immediately).
- Never time out (actTimeout 1s + small overage bank); keep < 50 ms/turn.
