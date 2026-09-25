# Kaggriculture: strategy spec for the new agent ("farm2")

Sources: 12 analyst reports covering about 52 top-20 replays. Every money flow in them was re-simulated through the engine, with 0 mismatches. I also checked `kaggriculture.py` directly (rules below are verified in the source) and read our `main.py`. `main.py` is not modified; the new agent goes in a new file.

**Target.** Top-10 agents make 100-145k coins in head-to-head games (top-13 mean 135.1k). Our agent makes about 69k: 69.2k mean over 16 self-play player-games, 77k against a copy of itself, and 65.4k against frozen top-player tapes, which themselves average 111.6k. The gap is about 65k, and it is structural rather than a matter of tuning. Tuning main.py's parameters made things worse (80.0k base down to 55.1k with all tweaks combined).

**The gap in one line:** strawberry +41.1k, wool +22.6k, tomato +6.1k, milk +4.3k, wheat +3.1k, carrot +0.9k, egg -3.8k, minus 8.7k of extra top-player spend on seeds, hires and land. That nets to -65.9k (top-13 mean vs ours, exact accounting).

**The six things top agents do that we don't:**
1. A scripted all-in D0 opening of 2 cows, 3 sheep, 6+4 melons, 10 wheat and 4 hires, with FEED and CARE on every animal from D0. The banked care pays out as capped first yields: 18 wool on D6 and 12 milk on D8.
2. Every coin is reinvested on D0-D10, funded by selling fertilizer at about $95. Land is bought the hour each windfall lands: NE on D6, SW on D8-9, SE on D10-11.
3. 25-44 strawberries, each fertilized at ages 9 and 13, for 8 berries per plant. This is the #1 revenue line, and we plant zero.
4. The herd is sized to the town shops, and every animal gets FEED and CARE every day. Feeding drops to maintenance when a product's price crashes.
5. 12-13 units from D10, animals packed around the shed, and multi-action tile visits: 42% moves vs our 59%, about 150-176 productive actions a day vs our 81-100.
6. Water and fertilizer only when it changes the outcome. Sell continuously, and end with an empty shed.

---

## 1. Engine facts that drive the strategy (checked in `kaggriculture.py`)

**Turn order within a step:**
1. Unit actions run first, in the order farmer then hands, with atomic PLANT validation.
2. The market runs next, slot by slot, in lockstep across both players.
3. Town consumption follows.
4. Plants decay.
5. At hour 23, the end-of-day refresh runs.

Consequences:
- Seeds or animals bought at step t can be used at step t+1 at the earliest.
- A DROP and a SELL in the same step work: the unit drops first, then the market sells.
- The **last processed step is 718** (D29 hour 22). The D29 end-of-day drop never runs, so anything still in a unit's inventory at the end is lost.

**Market slots:**
- An order at slot i finishes completely before slot i+1 starts.
- HIRE and BUY_LAND at slot i run before slot i's trades, using money from slots below i. So `[SELL WOOL, BUY_LAND]` in one turn works.
- At the same slot, both players get the same per-unit quote. A lower slot sells strictly before the opponent's higher slot.
- Buys are quoted at inventory-1 and sells at inventory, so a same-turn round trip nets exactly 0.
- `BUY_PRODUCT` and `BUY_ANIMAL` fail when the shed holds 100 or more items.
- At most 10 orders per turn are processed; the rest are dropped.

**Atomic PLANT:** if the number of PLANT requests for a crop this turn exceeds the seeds held, *all* PLANTs of that crop fail.

**Plants:**
- A new plant starts with `consecutive_unwatered=1`, so it **must be watered on its planting day**. It becomes a weed after 2 dry days, so watering every other day is the minimum.
- One-time crops (wheat, carrot, melon) start at yield 1. WATER inside the window `[ceil(mxd/2), mxd]` adds +1 immediately, or +2 if `fertilized_until_day >= day`, up to the cap.
  - Wheat window is ages 2-4, cap 6.
  - Carrot window is ages 2-3, cap 4.
  - Melon window is ages 6-12, cap 6. HARVEST requires age ≥ 10, so fertilizer is useless on melons.
- Decay starts at hour 0 of age `mxd+1` and removes 1 unit every 2 steps: wheat age 5, carrot age 4, melon age 13.
- FERTILIZE sets `fertilized_until_day = day+2`, covering 3 days.
- Ongoing crops produce at the **end** of a day when `(day+1-planted-fyd) % interval == 0`, for 4 productions in total. Each production gives +1, or +2 if the plant was watered that day and fertilized through that day. `yield_units` is capped at 4.
  - Strawberry produces at the end of ages 9, 11, 13 and 15 (harvestable at 10, 12, 14, 16) and decays from age 17.
  - Tomato produces at the end of ages 7, 8, 9 and 10 (harvestable 8-11) and decays from age 12.

**Animals:**
- A new animal starts with `consecutive_unfed=0`, so it survives its first day unfed. It escapes after 2 consecutive unfed days.
- Production happens at the end of day `placed+fyd-1+k*interval`:
  - Goose: every day from the end of placed+3.
  - Cow: every 2 days from the end of placed+7.
  - Sheep: every 3 days from the end of placed+5.
- On a production day, if the animal was fed, the whole `pending_care_bonus` is added. The bank resets to 0 on **every** production, fed or not. Then +1 is banked if the animal was fed AND cared today.
- Yield is capped at `max_held` (goose 4, cow 6, sheep 6).
- First yield with daily FEED and CARE from placement: sheep 1+5=6, cow min(6,1+7)=6 (one care day can be skipped), goose 1+3=4.
- Steady state: sheep 4 wool per 3 days, cow 3 milk per 2 days, goose 2 eggs a day (vs 1 per interval without care).
- A goose fed every other day gets no care benefit.
- Every surviving animal makes 1 fertilizer each night. It does not accumulate, so collect it daily.

**Town demand:**
- Shops unlock at hour 0 of D3, D6, D9, D12, D15, D18, D21 and D24 (8 draws with replacement, uniform over 8 types).
- Each shop instance consumes 1 of each of its products at steps where `step%4==0`, i.e. 6 per product per day, or 12 for single-product shops (YARN_STORE for wool, PET_CAFE for carrot).
- The town center consumes 1 per product per day (not fertilizer).
- Fertilizer has no town demand, so its price only falls: 100 - 0.2 per unit above I0.
- Strawberry demand per day = 1 + 6 × (BRUNCH + ICE_CREAM + SMOOTHIE + FARMERS_MARKET). Milk demand = 1 + 6 × (PIZZA + ICE_CREAM + SMOOTHIE). Wool demand = 1 + 12 × YARN. Egg demand = 1 + 6 × (BAKERY + BRUNCH). Tomato demand = 1 + 6 × (PIZZA + FM). Carrot demand = 1 + 12 × PET + 6 × FM. Wheat demand = 1 + 6 × (BAKERY + PIZZA + BRUNCH + ICE + FM).

**Price quick reference:**
- Above I0, the premium goods are steep:
  - Strawberry: -1.92 per unit, $1 at +62.
  - Milk: -2.10 per unit, $1 at +76.
  - Wool: 200 - 0.058x², $1 at +58.
  - Melon: 250 - 0.01x², $1 at +158.
- Below I0 they are flat:
  - Strawberry: 120 + 8.4√x ($204 at -100).
  - Milk: 160 + 8.7√x.
  - Wool: 200 + 8.6 ln(1+x) (about $245 at -200).
  - Wheat: 25 + √x ($45 at -400). Above I0 wheat follows a log curve and bottoms near $19-20.
- Tomato, egg and carrot use a hinge on the scarcity side. Tomato is 60 + 24(u + 8·max(0,u-1)²) with u = x/200: $84 at -200, $144 at -300, $300 at -400. So tomatoes that nobody sells reach $114-316.

**Hires:** the n-th hire of the day costs fib(n-1). Cumulative cost for h hires: 4 → $7, 6 → $20, 8 → $54, 9 → $88, 10 → $143, 11 → $232, 12 → $376, 13 → $609. Hands spawn on the shed-access tiles in NW, NE, SW, SE order by fewest occupants: the first hire goes to (5,4), then (4,5), (5,5), (4,4), and so on. PICKUP and DROP work from locked shed-access tiles.

**Shed-access tiles:** (4,4) NW, (5,4) NE, (4,5) SW, (5,5) SE. A pasture *on* (4,4) lets one unit PICKUP wheat and FEED without moving.

**Time:** actTimeout is 1s per step plus a 60s overage bank. Fourth Quadrant timed out in 113215371 while leading 34,144 to 26,585 and finished 181k behind.

---

## 2. What top agents do (consensus playbook)

### 2.1 Opening, D0 (identical across more than 10 top-10 agents; 52 of 102 ladder player-games)
The exact tape is 吃白饭的大肥鱼, ep 113211945 seat 0 (final 145.1k). It is stored in `tapes/113211945.json` → `actions[t][0]` for t = 0..23. Re-simulated D1 result: $7 left.

- **Step 0 market:** `HIRE ×4, BUY_PRODUCT WHEAT 4, BUY_ANIMAL COW 2, BUY_SEED MELON 6, BUY_ANIMAL SHEEP 3, BUY_SEED WHEAT 9`. **Step 1:** `BUY_SEED WHEAT 1`.
- **Steps 1-8:** each of the 5 units picks up one animal (step 1), picks up 1 wheat (step 2), walks 1-2 tiles, then BUILD_PASTURE, PLACE, FEED and CARE. All 5 animals are placed and 4 are fed and cared by step 8. The 5th, a cow, is fed D1, which is safe.
- **Steps 12-23:** plant 6 melons and 10 wheat, watering each on its planting step or the next.
- **D1 layout** (x → right, y ↓ down):
  ```
  y0: W W W W M
  y1: W W W . M
  y2: W W . M s
  y3: W . M c s
  y4: . M M s c        cow (4,4),(3,3); sheep (3,4),(4,3),(4,2); melons (4,0),(4,1),(3,2),(2,3),(1,4),(2,4)
  ```
  The 4 diagonal holes, (0,4), (1,3), (2,2) and (3,1), get the D1 melons (10 in total).
- **Variant used by Boey, TFC and FQ:** 5 hires, 3 cows + 2 sheep, 7 melons, 13 wheat, pasture built on (4,4) at step 0. It is equally strong. Boey is rank 1 but only wins 2.6-10% over meta opponents. Treat it as an A/B option (§5.5).

### 2.2 D1-D5: compounding on fertilizer
- **Every day:** collect fertilizer from all 5 animals and sell it immediately at $93-100, which brings in about $475-500 a day. FEED and CARE all 5 animals. Buy feed wheat as needed, about 5 a day at $27-30.
- **D1:** buy 4 melon seeds and plant them in the holes. Hire 4 ($7).
- **D2-D5:** harvest the D0 wheat at age 2-3 (2-3 units, used as feed) and replant those tiles with strawberries bought one at a time: 3-5 by D3, 8-10 by D5. Hands: 6 a day ($20).
- **Cash at hour 0:** $1-100 on D1-D4 and $250-500 on D5. Never sit on idle cash.
- Boey and MMPQ instead add 1 animal a day on D2-D4 (8-9 animals by D3). This is an A/B option.

### 2.3 Windfalls pay for the land
| Day | Windfall | Typical $ | Purchase, same day |
|---|---|---|---|
| D6 h0-3 | 3 sheep × 6 wool = 18 | $3.4-4.1k | **NE $1000 at h1-5**, then animals (by shops) and 10-20 strawberries in NE |
| D8 | 2 cows × 6 milk = 12 | $1.9-2.7k | SW $2000 on D8 h6-9 or D9 h0-8 (2nd wool: 12 on D9) |
| D10-11 | 10 melons × 6 = 60, sold 36 + 24 | $13-15k (first 36 at $238-272) | **SE $4000 on D10 h8-17 or D11** + fill it |

Money at hour 0 (top agents):
- D1: $0-19.
- D5: $250-500.
- D9: $8-2.3k.
- D11: $1-8.7k.
- D12: $5.9-11k.
- D15: $15-33k.
- D20: $43-71k (top-13 mean $56.9k; ours $26.4k).
- D25: $67-107k.
- Final: $105-145k.

### 2.4 Scaling timeline targets (per player)
| Day | Money h0 | Quadrants | Animals | Strawberry tiles | Melons | Wheat tiles | Units (farmer + hands) |
|---|---|---|---|---|---|---|---|
| D1 | ≤ 20 | 1 | 5 (2C 3S) | 0 | 6 | 10 | 5 |
| D3 | ≤ 100 | 1 | 5-6 | 3-5 | 10 | 5-7 | 7 |
| D5 | 250-500 | 1 | 5-7 | 8-10 | 10 | 0-2 | 7 |
| D7 | ≤ 300 | 2 | 10-14 | 15-26 | 10 | 5-10 | 9-10 |
| D9 | ≤ 1.2k | 2-3 | 14-20 | 18-30 | 10 | 8-15 | 10-11 |
| D11 | 1-9k | 3-4 | 16-22 | 26-36 | 0-4 | 13-23 | 12-13 |
| D12-19 | grows 6-9k/day | 3-4 | 18-25 | 28-44 (peak) | 0 | 15-30 | 12-13 |
| D20-26 | | | 18-25 | falling as spent plants are dug | 0 | 30-49 | 12-13 |
| D27-29 | | | feeding tapers | 0 | 0 | wheat/carrot | 12, 11, 10 |

Empty or weed tiles from D12 on: 2-10 on average for top agents; ours is 17-23.

### 2.5 Product economics (engine-exact yields; typical realized prices)
| Asset | Units per cycle | Tile-days | Actions per cycle | Units/tile-day | Typical price | $/tile-day gross |
|---|---|---|---|---|---|---|
| Sheep FULL (feed+care daily) | 4 per 3 days | 1 | ~3.3/day | 1.33 | $180-240 with a yarn store | 240-320 (+fert) - $38 feed |
| Cow FULL | 3 per 2 days | 1 | ~3.5/day | 1.5 | $150-210 with milk shops | 225-315 (+fert) - $38 |
| Goose FULL | 2 per day | 1 | ~3.5/day | 2.0 | $40-54 | 80-108 - $38 |
| Melon (first ~60 per player) | 6 | 10 | 10 | 0.6 | $200-250 | 120-150 (shared pool: 30 demand/season) |
| Strawberry, fertilized at 9 and 13 | 8 | ~17 | ~17 | 0.47 | $130-220 | 60-100 |
| Wheat, fertilized at 2, harvested at 3 | 5 | 3 | 6 | 1.67 | $33-45 | 55-75 (also feed) |
| Wheat, unfertilized, harvested at 4 | 4 | 4 | 6 | 1.0 | | 35-45 |
| Tomato, fertilized at 7 and 10 | 8 | 12 | ~16 | 0.67 | $60, or $100-300 if scarce | 40-200 |
| Carrot, fertilized at 2, harvested at 3 | 4 | 3 | 6 | 1.33 | $35, up to $70 with a pet cafe | 45-90 |

- Every animal also yields 1 fertilizer a day, worth $95 on D1-5, about $60 on D12, $29 on D20 and $15 on D26.
- CARE is the most valuable single action: about $143-186 per action on cows and sheep. A cow placed D1 gives 36 milk with care vs 11 without; a sheep gives 34 wool vs 8.
- Hands cost $6-18 per action at the margin, and every row above earns $30-85 per action. Labor is worth buying up to 12-13 units.

**Revenue mix of 130k+ agents** (top-13 mean): strawberry 41.1k (24%), wool 37.9k, milk 28.6k, melon 14.8k, fertilizer 12.3k, wheat 9.9k net, egg 6.8k, tomato 6.1k. Costs: seeds 6.9k, animals 9.8k, land 4.5k, hires 6.3k (287 hires). Scores correlate 0.75 with the value of the season's shop draw. Ladder players leave only about 10.7k of demand unfilled per game; our self-play leaves about 105k.

### 2.6 Crop calendars (ages in days since planting; the order within a visit matters)
- **WHEAT** (default): age 0: PLANT, WATER. Age 1: skip. Age 2: FERTILIZE, WATER. Age 3: WATER, **HARVEST (5)**, PLANT, WATER. Without fertilizer: water 0, 2, 3, 4 and harvest 4 at age 4. As emergency feed: age 2 WATER then HARVEST (2, or 3 fertilized). Never leave wheat past age 4.
- **CARROT:** 0 PLANT+WATER; 2 FERTILIZE+WATER (3); 3 WATER+HARVEST (4). Never past age 3.
- **MELON:** 0 PLANT+WATER; water at 2 and 4; water daily at 6-10; age 10 WATER then HARVEST (6). Never fertilize. Must harvest by age 12. On D10, harvest at hours 0-6 and sell first (Boey from h7; others from h9+).
- **STRAWBERRY:** 0 P+W; W at 2, 4, 6, 8. Age 9: FERTILIZE+WATER. Age 11: HARVEST (2)+WATER. Age 13: HARVEST+FERTILIZE+WATER. Age 15: HARVEST+WATER. Age 16: HARVEST, DIG, PLANT (wheat or carrot), WATER. That is about 10 visits in 17 days for 8 berries. Top agents: fertilized and watered on 95-99% of production days, 7.2-8.0 berries per plant. If the price crashes below about 35% of base with no recovery drift, dig early and replant wheat (Boey, 113207234).
- **TOMATO:** 0 P+W; W at 2, 4, 6. Age 7: FERTILIZE+WATER. Age 8: WATER. Age 9: HARVEST (4)+WATER. Age 10: FERTILIZE+WATER. Age 11: HARVEST (4), DIG, replant.
- Evidence: 吃白饭 FERTILIZE strawberry at age 9 ×35 and age 13 ×35, never waters at ages 10/12/14 and never waters melons at ages 1/3/5. Vadim waters strawberries at age 1 on 8/44 plants and at ages 9/11/13/15 on 42/43, 42/43, 40/42 and 35/35.

### 2.7 Animals: care, feeding modes, harvest
- **FULL** mode while the product sells: FEED+CARE+COLLECT_FERTILIZER every day in **one visit**, plus HARVEST.
  - Top agents: fed 0.86, cared 0.84 and fertilizer collected 0.92-0.96 per animal-day.
  - Ours: fed 0.69, cared 0.37, collected 0.55. Our geese are cared on 0%, so they make 1.0 egg per goose-day vs Boey's 2.02-2.10.
- **MAINT** mode when the price crashes: feed (and care) **on production days only**, keeping feeds at most 2 days apart. The animal cannot escape and still gives fertilizer daily.
  - Cow: feed+care on alternate production days gives 2 milk per 2 days for 1 wheat.
  - Sheep: feed+care on P+2 and P+3 of each 3-day cycle gives 3 wool per 3 days for 2 wheat.
  - Goose: feed every other day, no care (care is worthless if not fed daily), giving 1 egg a day.
- **ABANDON:** stop feeding, let the animal escape, DIG the structure and reuse the tile. Examples: DECEM dropped 3 cows at milk $7; TFC swapped cows for sheep when milk fell to $1-5.
- **Thresholds** with λ ≈ $15 per action and wheat price w:
  - FULL beats MAINT when price > w + 2λ: milk or wool above about $70, eggs above about 0.5w + 25 (about $45).
  - MAINT beats ABANDON when milk is above about $35 or wool above about $40.
  - Observed switches: MG put cows on MAINT at milk $40-55; 吃白饭 put geese on MAINT at eggs $42 vs wheat $40-44 and starved sheep at wool $1-55.
- **Harvest:** sheep after every production (4+4 > 6); geese every 2 days (2+2 = 4); cows can hold 2 productions (3+3 = 6).
  - Using cows as storage raises milk per harvest to 4.0-4.4, vs 3.0-3.3 for opponents.
  - Holding product on the animal while its price is depressed is free storage: MG held wool D16-21 at $1-31 and harvested 19/18/27 when the price was back to $98-177.
- **Placement timing:** each day of delay costs about $250 per cow or sheep. A cow placed D1 instead of D10 is worth about +2.2k.
  - For late sheep, place on days ≡ 2 (mod 3), which gives the most harvests by D29. Placed D11: harvests D17, 20, 23, 26, 29 (5). Placed D12: 4.
  - Last purchases: goose ≤ D15, cow ≤ D19, sheep ≤ D21.

### 2.8 Fertilizer lifecycle
- **Collection:** 415-517 per game at the top vs 256 for us.
- **Sold:** 206-322 units for $11-15k, mostly on D1-D10 at $60-100. **Used:** 180-250 FERTILIZE actions per game. Never bought except late at $3-22 (吃白饭 bought 99 at $22, TFC 31 at $3-4).
- **Use priority:** strawberry at ages 9 and 13 (+2 berries each, worth $250-400) > tomato at 7 and 10 > wheat at age 2 (+2 wheat) > carrot at 2 (+1).
- **Timing:** sell everything D1-D9. From about D10 keep enough for the scheduled strawberry and tomato applications over the next 3 days. Use it on wheat when the fertilizer price is below 2 × the wheat price. Sell the surplus the same day.

### 2.9 Labor and logistics
- **Units:**
  - D0-1: 4-5 (farmer + 4).
  - D2-5: 6-7.
  - D6: 8-9.
  - D7-8: 9-10.
  - D9: 10-11.
  - D10: 12.
  - D11-27: 12-13 (12 hires = $376/day; the 13th unit costs $233).
  - D28-29: 10-12.
  - Hires go in at h0 (up to 8 orders) with the rest at h1. Top agents make 284-315 hires per game ($5.4-9.9k).
- **Action mix:** 40-45% moves, 47-58% productive, 0-7% PASS. 1.98 actions per tile visit (ours 1.43), and 65% of moves go to an adjacent tile (ours 49%).
  - Most common visit patterns: FEED-CARE-COLLECT (203 per game), FERT-WATER (161), WATER-HARVEST-PLANT-WATER (113).
- **Layout:** animals average 1.9 tiles from the shed-access tiles, with 72% within 2 (ours 4.1). Crops average 4.6. The shed-access tiles hold cows 187 times, sheep 81, geese 51 and wheat 19 across 104 player-games.
- **No fixed zones.** Units sweep to the nearest tile with work (hand-to-tile overlap between days is 0.05-0.3).
- **Item flow:**
  - Wheat and fertilizer are picked up at spawn in hours 1-2 (about 155 pickups per game, 2-4.5 per pickup).
  - Produce is carried all day and dropped when passing the shed; the end-of-day auto-drop does the rest.
  - Overflow averages 5.4 units per game at the top vs 48.5 for us.
  - **Exception:** keep mid-day unload trips on D0-D10, while cash still limits growth. Carrying everything to the end of day early collapsed a prototype to 15-36k.

### 2.10 Market tactics
- **Selling:** top agents sell nearly everything within a day of production, in chunks. They do not hoard.
  - Holding premium goods for a better price cost the public tape bot 7.5-34k per game, and Majkel lost 113210740 by $262 after hoarding 47-53 strawberries and dumping 33 at $15.
  - They **do** pause selling when a premium good is past I0 (a glut) and the town is draining it. M&M paused wool at $192 and resumed at $238-240.
  - At depressed prices they sell only 1-2 per shop tick: Vadim's wool averaged $127 while the market sat at $31-61.
- **Melons:** sell all on D10-11 as they are harvested. The first seller gets $238-272; later sellers get $137-170.
- **Order slots:** put steep goods first. Moving contested sells from the back of the list to the front swings about 775 coins per player-game. Re-sorting our current order list by price impact is worth +650 per game against top-team order streams and +1,221 in self-play, with the opponent losing 550-1,334 (margin +1.2 to +2.6k).
- **Churn and NOOPs: no value.** Across 104 player-games, same-step buy/sell churn netted +185 coins in total and removing NOOPs changed money by -8. Boey's churn is a leftover of a tape template, and the public "route tape" bots pad with empty orders to keep slot positions. **Do not implement either.**
- **Wheat tick trade** (the only net-positive micro trick, medium confidence): shops consume after the orders sent at hours 0/4/8/12/16/20, so buy wheat last at those hours and sell it one step later. Worth +700-900 per game (N=50); the opponent gains about 330, so the net margin is +400-700. The algorithm is in §5.2 C13.
- **Last day:** SELL every item with qty 10000 each step from D29 h0 (sorted by impact), and have every unit DROP at the shed by step 718. TFC sold $17.9-18.1k on D29; MMPQ turned a -16.3k position at D29 h0 into a +4.8k win by selling 25.6k.

### 2.11 Endgame (D25-D29)
- **Last plantings:**
  - Strawberry D13 (a D14-15 planting gets only 3 productions).
  - Tomato D18 (productions at the end of ages 7-10 must fall on or before D28).
  - Melon: effectively D2.
  - Wheat D26 (harvest age 3 on D29) or D27 (harvest age 2).
  - Carrot D26-27.
  - No seed purchases on D28-29 except for those plantings.
- **CARE** only if the animal has a production at the end of some later day ≤ D28 and will be fed on that production day.
- **FEED** only if the animal produces tonight (day ≤ 28), or `consecutive_unfed == 1` and a future production ≤ D28 remains. Nothing on D29.
- In practice: sheep feeding stops D26-27, cow and goose feeding D28, and no FEED or CARE on D29 (sheep fed 7/17 on D27 and 4/17 on D28; D29 FEED = 0).
- **D29:** harvest every plant with yield ≥ 1 and every animal. Units walk back and DROP between h10 and h22. Sell continuously so drops fit under the 100 cap. Final shed ≤ 5 items. D29 revenue: $5-26k.

### 2.12 Contradictions and how they are resolved
| Question | Evidence for | Evidence against | Resolution |
|---|---|---|---|
| Buy SE ($4000)? | Vadim +15.6k vs his clone without SE (113207221); MG +9.9k vs clone Arda (no SE); SE owners won 3/4 in DECEM's games; 7 of the top-13 buy it | Boey never buys SE and won all 4; two SE buyers lost to Boey by 5.6k/8.0k (they also had fewer geese and less fertilizer) | **Default: buy SE on D10-D11** if cash ≥ 4000 + reserve after the melon sale, ≥ 20 SE tiles have a planned use, and the labor budget allows. Otherwise skip. A/B test it. |
| Opening herd | 2C+3S used by MG, DECEM, Vadim, Densike, 吃白饭, mtmr, TheEggman, DSM (52/102 games); the bigger D6 wool check pays for NE | 3C+2S used by Boey (rank 1), TFC, FQ | Default 2C+3S (majority, exact tape available); 3C+2S as an A/B. The public-notebook claim that "cow / 4-hire openings lose" is contradicted by the replays. |
| Melon count | 10 is the modal count; 13 vs 10 gave MG +2.3k; 17 vs 10 gave mtmr +4.2k | 18 each in self-play → 108 sold at $137 and about 22 per player at $1 | **Adaptive 8-12:** total = clamp(21 - opponent D0 melon count, 8, 12), bought on D1. Combined supply of about 120-130 units keeps the marginal price near or above $100. |
| Hold vs sell | MMPQ's last-day stockpile; M&M pausing wool; holding milk on cows | Public tape bot lost 7.5-34k by holding; Majkel dumped at $15 | Sell by default. Hold **only** when the price is below its floor **and** the estimated drift (town demand minus rival sales) is positive, and only up to shed limits. Stock accumulates naturally in the last days; don't build it deliberately. |
| Fertilizer on wheat | Boey, MG, MMPQ: 60-124 wheat fertilizations per game | Gap analyst: "never on wheat" | Sell on D1-D9 (price $78-100 > 2 wheat). Later, use on wheat age 2 when fertilizer price < 2 × wheat price and strawberry/tomato needs for the next 3 days are covered. |
| Wheat harvest age | Boey age 3, 5 units (1.67/tile-day) | MMPQ and IsaiahP age 4, 6 units | Age 3 while tiles are scarce (D6-D24); age 4 is allowed when the labor budget is tight (1.75 vs 2.0 actions/tile-day). |
| Tomatoes | 5 of 12 analysts: minor (top-13 mean 6.1k) | Public notebook: "biggest hole" (winners sell ~71 at ~$114); mtmr +15.8k with pizza + farmers market | Conditional program: only with PIZZA/FM demand, 5 plants per such shop (cap 15), while the tomato price is ≥ $70 or inventory is below I0-100. |
| Geese | MMPQ wins with 11-15 geese (brunch/bakery) | FQ uses none; our 14-19 uncared geese are a sink | Geese only with BAKERY/BRUNCH demand and eggs ≥ $48, always FULL. Cap 3 × (BAKERY+BRUNCH), max 12. |
| 12 vs 13 units | MG and mtmr run 13 | Boey and DECEM run 11-12 | Size to the day's work each day, with a hard cap of 13 units. |
| Seat asymmetry in self-play (13%) | market-micro: 77.5k vs 67.6k | Public notebook: a seat swap replays the same game | Evaluate on ≥ 40 seeds × both seats, with paired comparisons. Never trust a single game. |

---

## 3. Exploits and opponent interactions

Worth implementing, in order of value:
1. **Care-bank capped first yields.** A mechanic rather than a trick, and the basis of the D6/D8 cash. Also skip 1 cow care day before its first production to save wheat when cash is tight (TFC).
2. **Same-turn sequencing.** Sells go first in the list, so HIRE, BUY_LAND and BUY_ANIMAL at later slots can spend the proceeds. DROP and SELL in the same step. Buy seeds exactly 1 step before PLANT.
3. **Slot priority on contested steep sells.** Order sells by `(price(inv) - price(inv+n))`, descending. This matters for WOOL (+286 per game front vs back), MILK (+139), STRAWBERRY (+133) and MELON (+49). Never split one product across slots.
4. **Race detection.** Estimate what the rival sold each step: `rival_sold = (inv_t - inv_{t-1}) + town_draw(step_{t-1}) - own_sold_{t-1}` for products the rival can't buy (all except wheat and fertilizer; count only units sold above $1). If the rival starts selling a premium product and its price is still ≥ base, sell ours now. This matters most for the D6 wool, D8 milk and D10 melon batches.
5. **Demand denial.** Every premium unit we sell before the glut is one the rival sells lower. Skipping D11 strawberries when no berry shop was open cost the tape bot 1.5k, because the rival sold them instead.
6. **Watching the opponent.** `farms[opp].tiles` is public. Count its melons (to size ours on D1), strawberry and tomato tiles, and each animal type. Two players building the same 12-cow / 36-strawberry engine crashed milk to $45 and strawberries to $5 (113209485); the winner came from the pivots.
7. **Fertilizer arbitrage over time.** Its price only falls, so sell early and buy back late at ≤ $12 for strawberry and tomato applications.
8. **Animals as storage.** Cows can hold 2 productions; products stay on the animal while the price is depressed.
9. **Shed buffer control.** At h20-23, sell exactly what the midnight drop would otherwise destroy. The market can serve as free overnight storage for wheat (sell, then buy back at h0 at about zero net), which is only useful when the shed is at the cap.
10. **Wheat tick trade:** +0.4-0.7k net margin (§5.2 C13). Implement last.

Defend against:
- **Timeout.** Keep a per-step time budget (C14). Worker speed varies about 1.5×; M&M's step-1 cost ranged 25-50s.
- **The rival selling first:** handled by slot ordering and race detection.
- **A product glut when both players chase the same good:** shop-demand sizing plus opponent-aware caps, and MAINT/ABANDON modes.
- **A dead opponent** (money unchanged for 24 or more steps and 0 hands after h1). Optionally switch to maximum expansion of goods the town buys. The rating gain is small; this is about +50-100k coins in rare games.

Not exploitable, so don't build them: NOOP padding, same-step churn, and hurting the opponent through order position at the same slot (both players get identical quotes).

---

## 4. Our agent's biggest gaps, ranked by coin impact

| # | Gap | Where in main.py | Evidence | Est. gain |
|---|---|---|---|---|
| 1 | **No strawberries or tomatoes at all** | Plant options (lines 347-406) only cover WHEAT, MELON, COW, SHEEP, GOOSE, CARROT | Top strawberry revenue $17-68k per player; ours $0, which leaves the price at $276-306; unfilled demand 156-372 units per game | **+20-35k** (a rough patch measured +13.7k vs tapes, +27.8k in self-play) |
| 2 | **Weak opening and idle cash on D1-D9** | 18 melons + 2 cows on D0 (melon_total=18), $578 unspent, 3 hands | D0-9 revenue 3.4k vs 14-16k; money $600-1,700 idle on D5-D9; 2 animals until D9-D10 | **+10-20k** |
| 3 | **Late land and idle cash on D11-D16** | Land rule (757-760): empties+weeds ≤ 3 and a $1200 reserve | NE on D9, SW on D15-21, SE almost never; $12-17k idle on D11-16 with 15-30 empty tiles | **+10-20k** |
| 4 | **Wrong herd: no sheep, uncared geese, fixed caps** | goose_care=False (105), cow_cap 8 and sheep_cap 6 (106-107), goose-biased option scoring (368-370) | Wool gap 22.6k; 14-19 geese per game on alternate-day feeding (about 25 eggs each at $42); 176 CARE actions per game vs 401 | **+8-15k** |
| 5 | **Labor volume and efficiency** | Hire formula work/23 with a 35%-of-budget cap (243-294); single highest-priority action per animal (461-487); `priority - 6×dist` scoring; nearest-first crop placement (342) | 3 hands D0-9; 59% moves; 81 productive actions a day vs 148; animals 4.1 tiles from the shed | **+10-15k** (enabler) |
| 6 | **Fertilizer** | Used only on wheat and carrot, only when fertilizer price < 1.8 × wheat price (237); collection priority 20 + 0.7p (483) | Collected 55% of animal-days; 56 used vs 203; about 150-200 units per game never collected | **+3-8k** |
| 7 | **Selling** | HIRE before sells (747); sells in fixed product order; premium floor 0.35 × base with late dumps; melon floor dumps | 22 melons per player at $1; 14-42 milk at $1 in some seeds; floor-hoarded strawberries dumped at $1-20 in patched runs | **+3-8k** |
| 8 | **Watering waste** | Ongoing crops watered daily at priority 85 (433-438); melons at ages 1/3/5; wheat at age 1 | Top agents water 0.66-0.80 per plant-day | **+1-3k** (labor) |
| 9 | **Overflow and decay losses** | guard_hour=17 evening unload | 48.5 units per game overflow (up to 159); 36-52 wheat decayed | **+2-5k** |
| 10 | **Endgame upkeep** | Feeds and cares through D29 | Top agents stop care D26-27 and feed D28 | **+1-3k** |

**Warning from the prototypes.** Fixing #5 alone made the agent lose: a better scheduler lost 5 of 6 games because it bought 34 geese and 442-570 market wheat while selling 364-414, and lost 31 melons. More hands alone (58.5k) and earlier land alone (42-52k) also lost. Changes #1-#5 must ship together, with the planner sizing assets to demand and to the labor budget.

---

## 5. Implementation plan

### 5.1 Architecture
Create a new file, e.g. `farm2.py`. Its last callable must be `agent(obs, config)`, because Kaggle runs the last callable. main.py stays as the baseline opponent.

**Keep from main.py:**
- Constants: `CROPS`, `ANIMALS`, `MARKET_PARAMS`, `LAND_PRICES`, `SHED_TILES`.
- Helpers: `_shape`, `market_price`, `quadrant_of`, `dist`, `step_toward`, `nearest_shed`, `g()`, `fib_costs`.
- The `make_agent` closure with a per-player `mem`, and the try/except that falls back to PASS.
- The tile survey loop (lines 188-218) and the shop-demand table (221-232), extended with fertilizer=0 and single-product ×2.
- The inventory reservation pattern (`unit_has`/`consume`) and the floor-limited sell quantity loop (740-742), reused as a helper.

**Rewrite everything else as these modules:**
1. `World`: parses observations; derives per-tile age, production-day flags, next production, window flags and deadlines; tracks opponent stats and rival-sales estimates; computes daily demand per product.
2. `Planner`: runs at hour 0 and on events (land bought, cash windfall, shop unlock). Produces the tile role map, herd targets and crop targets, checks the labor budget, and builds the purchase list and hire count.
3. `Layout`: ranks tiles per quadrant.
4. `Calendar`: per-tile work orders for today (the rules in §2.6-2.7 and §5.2).
5. `Scheduler`: assigns units to work orders and handles item logistics.
6. `Market`: sells, buys, land and hires, in slot order.
7. `Opening`: the D0 tape with validation.
8. `Endgame`: the rules in §2.11.
9. `Guard`: time budget and fallback.

### 5.2 Components (ordered by expected gain; dependencies noted)

**C1. World model and calendars** (enabler, needed by everything).
- Plant production today: `d = day+1-planted-fyd; d >= 0 and d % interval == 0 and d//interval+1 <= 4`.
- Animal production today: `d = day+1-placed-fyd; d >= 0 and d % interval == 0`.
- Window start for one-time crops: `(mxd+1)//2`, which gives wheat 2, carrot 2, melon 6.
- Decay start (hour 0): wheat age 5, carrot 4, melon 13, strawberry 17, tomato 12.
- Demand per product per day `D_p` as in §1.
- `rival_rate_p` is the EMA over 24 steps of `rival_sold`.
- `drift_p = D_p - rival_rate_p` (units per day).

**C2. Layout and scheduler with logistics** (enabler; ship together with C3-C6).
- **Layout:**
  - For each owned quadrant, rank tiles by Manhattan distance to the nearest shed-access tile.
  - Structure slots are the d ≤ 2 tiles, 6 per quadrant: NW (4,4); (3,4),(4,3); (2,4),(3,3),(4,2). NE (5,4); (6,4),(5,3); (7,4),(6,3),(5,2). SW (4,5); (3,5),(4,6); (2,5),(3,6),(4,7). SE (5,5); (6,5),(5,6); (7,5),(6,6),(5,7). Spill to d = 3 when needed.
  - Cows go on shed-access tiles first, then sheep, then geese.
  - Wheat and carrots go at d 3-5. Strawberries, tomatoes and melons go at d ≥ 4 in contiguous row or column blocks at the farm edge.
  - Never put melons or strawberries on ring tiles.
- **Work orders:** for each tile, the ordered list of today's executable ops.
  - Animal: `[PLACE?] FEED(wheat) CARE COLLECT_FERTILIZER [HARVEST if yield+next_prod > max_held, or yield ≥ 3 (cow/sheep) or ≥ 2 (goose), or day ≥ 28]`.
  - One-time crop on harvest day: `WATER HARVEST PLANT(seed) WATER`.
  - Strawberry or tomato: `[HARVEST] [FERTILIZE] [WATER]` per the calendar.
  - New land: `BUILD_* PLACE` or `PLANT WATER`. Weeds: `DIG` (if ≥ 3 days left) followed by the planned use.
  - Never CARE an animal that nobody will FEED today: route only wheat-carrying units to unfed animals.
- **Assignment:**
  - A unit standing on a tile with executable work continues there.
  - Otherwise, greedy by `score = value - 8×dist + 12×(same target as last step)`, where `value = 60 + 10×(ops-1) + urgency`.
  - `urgency = +100` when failure tonight would lose value (unwatered with `consecutive_unwatered ≥ 1`, unfed with `consecutive_unfed ≥ 1`, would hit the yield cap tonight, melon at age ≥ 10, D10 melon race) and `hours_left ≤ dist + ops + 2`.
  - One unit per tile. Reserve seeds, fertilizer and wheat when a unit claims a tile.
  - Count PLANTs per crop against seeds exactly, because of atomic validation.
- **Items:**
  - At h0-2, units on shed-access tiles PICKUP `ceil(animals_to_feed/units)+1` wheat, and the crop crew picks up the day's fertilizer.
  - Feed harvested wheat directly. Put collected fertilizer straight on the day's FERTILIZE targets.
  - D0-D10: a unit carrying ≥ 4 premium units or ≥ 8 items within 3 tiles of the shed walks back to DROP.
  - D11+: DROP only when already on a shed-access tile, plus overflow control. From h20, keep `shed + Σcarried + expected harvests ≤ 100` by selling from the shed.
- **Targets:** move share ≤ 45%, ≥ 1.8 actions per visit, ≥ 150 productive actions a day on D11-26.

**C3. Opening (D0 tape + D1-D5)**. +10-15k; depends on C1 and C2 from D1.
- **D0:** replay `tapes/113211945.json` seat-0 actions for steps 0-23 verbatim. Pad or truncate `hands` to the real hand count.
  - Validate every step: expected money ≥ the order cost, and units at the expected positions. On mismatch, fall back to the planner with the §2.1 target layout.
  - Expected D1 state: $0-20, 2 cows at (4,4),(3,3), 3 sheep at (3,4),(4,3),(4,2), 6 melons, 10 wheat, 4 free diagonal tiles.
- **D1:** 4 hires. Collect all fertilizer, DROP, sell it. `BUY_PRODUCT WHEAT` for feed. FEED+CARE all animals (the unfed cow first). Buy melons up to `M = clamp(21 - opp_melons_D1, 8, 10 + free_tiles_available)`, default 4 more for 10 in total, and plant them in the holes.
- **D2-D5:** 6 hires a day. Harvest D0 wheat at age 2-3 (use it for feed, sell the surplus). Replant with strawberries as cash allows, 1 seed bought per planting step, until NW is full: 8-10 by D5.
- **Shop-triggered extra animal:** if the D3 shop is a YARN_STORE, buy 1 sheep, or a cow for a PIZZA, ICE_CREAM or SMOOTHIE, when a ring tile is free and cash ≥ price + $60.

**C4. Capital allocator and land** (D1-D12). +10-20k.
- `reserve = feed for the next 24h (animals × wheat_price) + tomorrow's hires ($20 early, $400 later)`.
- `available = money + proceeds of this turn's sells (placed before buys) - reserve`.
- Spend priority: (1) today's hires, (2) feed wheat, (3) **land** when affordable, (4) animals for planned empty structure slots, (5) seeds for tiles scheduled to be planted in the next 1-2 steps.
- Target: money at h0 ≤ $300 on D1-D10, unless within 24h of a land threshold.
- **Land rule:**
  - NE when money ≥ 1000 + reserve (expected D6 h1-5). SW when money ≥ 2000 + reserve (D8-9).
  - SE when money ≥ 4000 + reserve **and** day ≤ 11 (A/B: ≤ 12) **and** the planner has ≥ 20 SE tiles assigned **and** projected work stays within the 13-unit budget. Expected D10 h8-17.
  - No land after D12. Put BUY_LAND right after the sells in the order list.
  - Build and plant the new quadrant **the same day**: TFC planted 21 strawberries in NE on D6.
- After D12, money is idle. Buy only positive-ROI items: seeds, feed, hires, and animals before their cutoffs when demand supports them.

**C5. Hiring.** Enabler, about +3-5k on its own.
- `U_today = clamp(ceil(W_today / (24 × 0.56)), Umin(day), Umax(day))`.
- `W_today` = Σ today's calendar actions + planned plantings and builds + 0.3 per animal for wheat logistics.
- Bounds (farmer included):

| Day | D0-1 | D2-5 | D6 | D7-8 | D9 | D10 | D11-27 | D28 | D29 |
|---|---|---|---|---|---|---|---|---|---|
| Umin | 5 | 6 | 8 | 9 | 10 | 11 | 11 | 10 | 9 |
| Umax | 5 | 7 | 10 | 11 | 12 | 13 | 13 | 12 | 12 |

- Hire at h0: the top 1-2 sells, then up to 8 HIRE orders. The rest at h1.
- Never pay more than $233 for a single hire.

**C6. Strawberry program.** +20-30k; depends on C2-C5.
- `S = #BRUNCH + #ICE_CREAM + #SMOOTHIE + #FARMERS_MARKET` (known). `draws_left12` = remaining unlocks up to and including D12.
- `N_s(day) = min(44, 10 + 8 × (S + 0.5 × draws_left12))`. For example: D6 with S=0 → 18; S=1 → 26; S=2 → 34. From D12 on, use `10 + 8×S`.
- **Opponent adjustment:** `N_s -= max(0, opp_strawberry_tiles - 30) // 2`.
- **Waves:** 8-10 in NW on D2-D5 (unconditional); NE blocks on D6-D8; top up to `N_s` on D9-D13. Spread plantings across days to spread the harvest labor and sales.
- **No new plants after D13.** D14-15 is allowed only if S ≥ 3 and price ≥ 150 (3 productions).
- Calendar per §2.6. Harvest when yield ≥ 2 on a visit, and always before a production would exceed the cap of 4. Dig at 16, or early if price < 0.35 × base and `drift ≤ 0`.
- Target ≥ 7.0 berries per plant.

**C7. Fertilizer policy.** +3-8k.
- Collect from every animal every day as part of the animal visit while the fertilizer price ≥ $4.
- `fert_need_3d` = scheduled strawberry (ages 9, 13) + tomato (7, 10) applications in the next 3 days, plus wheat and carrot age-2 applications if `fert_price < 2 × wheat_price`.
- Sell `stock - fert_need_3d` every turn. D1-D9: sell all (no crop needs yet).
- If `fert_price ≤ 12` and `stock < fert_need_3d`: `BUY_PRODUCT FERTILIZER` for the shortfall.
- **Recovery rule** for missed timing: fertilize an ongoing plant today if a production day d ∈ [today, today+2] has `fertilized_until_day < d` and the plant will be watered on d.

**C8. Shop-driven herd and care modes.** +8-15k.
- **Targets**, recomputed at h0 and when shops unlock:
  - `sheep_T = 3 + round(4.5 × YARN)`, max 18. With YARN = 0, stay at 3 and never add.
  - `cow_T = 2 + round(2.5 × (PIZZA + ICE_CREAM + SMOOTHIE))`, max 12. With none, 2-3 (3 only if milk ≥ $180).
  - `goose_T = round(3 × (BAKERY + BRUNCH))`, max 12, only if egg ≥ $48.
  - Opponent adjustment: if the opponent's count of a species ≥ our target + 4, reduce our target by 2.
- **Buy guards:** no new purchase if the product price < 0.9 × base (milk < 144, wool < 180, egg < 45), unless there are ≥ 2 demand shops and market inventory is below I0. Cutoffs: goose ≤ D15, cow ≤ D19, sheep ≤ D21, with late sheep preferring days ≡ 2 (mod 3).
- **D6 purchase:** the first big buy, chosen by the two shops known on D6. After NE is bought, spend at most 60% of the rest on animals for NE ring slots and the rest on NE strawberries.
- **Modes per species, daily:**
  - FULL if price ≥ max(w + 30, 0.45 × base).
  - Otherwise MAINT if milk ≥ 35, wool ≥ 40, or egg ≥ 0.5w + 10.
  - Otherwise ABANDON: stop feeding, DIG after the escape, and reuse the tile for a demand-backed species or crop.
- **Endgame** per §2.11.

**C9. Market module.** +5-12k in total.
- **Order list:** `[SELLs sorted by price impact, desc] + [HIRE…] + [BUY_LAND] + [BUY_ANIMAL] + [BUY_SEED] + [BUY_PRODUCT]`. To stay within 10 orders, drop the lowest-impact sells first (they go out next turn).
- **Sell quantity per product:** sell units while the marginal `price ≥ floor_p(day)`.
  - Premium (strawberry, milk, wool): 0.55 × base until D25, 0.35 × base on D26-27, 0.12 × base on D28, $1 on D29.
  - Egg, carrot, tomato: 0.6 × base, then the same taper.
  - Wheat: sell stock above a 1.5-day feed reserve (net of expected own harvest) at a floor of $18.
  - Melon: on D10-12, sell everything harvested at a floor of $40. Other days 0.3 × base.
  - Never SELL and BUY_PRODUCT the same item in one turn: net them.
- **Hold vs dump:** if units remain above the floor-limited n:
  - If `drift_p > 0.5`/day and `shed + carried ≤ 85`, hold.
  - Else if `drift_p ≤ 0`, sell at least `max(1, D_p/6)` per tick, and all of it if the price trend over 24 steps is falling.
  - Never hold a product for more than 3 days.
- **Race:** if `rival_sold_p > 0` in the last 4 steps and price ≥ base, sell all available units of that product now, at slot priority.
- **Overflow:** at h ≥ 20, projected end-of-day shed = shed + Σcarried + remaining harvests. Sell the lowest-value items until it is ≤ 100.
- **D29:** SELL item 10000 for every product with a stock, every step, sorted by impact.
- **Buys:**
  - Seeds 1 step before the planned PLANT (buffer = plantings in the next 2 steps).
  - Animals when a matching structure exists or will be built within 3 steps.
  - Feed wheat at tick hours (0/4/8/12/16/20), only if `stock + expected harvest before tomorrow h2 < remaining today + tomorrow's first feed`.
- **Wheat self-sufficiency from D8:** wheat tiles ≥ `ceil(1.1 × daily_feed / 1.67)`. Top agents net-buy 104-172 wheat on D0-D12 and are net sellers after D13. Losers bought 199-286.

**C10. Endgame.** +1-3k; rules in §2.11. Also: 10-12 units on D29, units routed to arrive at a shed tile at the latest by step `718 - carried_trips`, a final DROP at step 718 (unit actions run before the market), and fertilizer collection on D29 only if a unit is already on the tile.

**C11. Tomato and carrot scarcity programs.** +2-6k, conditional.
- **Tomato:** if `PIZZA + FM ≥ 1` and day ∈ [9, 18] and (tomato price ≥ 70 or inventory < I0 - 100), target `N_t = min(15, 5 × (PIZZA + FM))`. Calendar per §2.6. Do not plant into a crashing book: stop if price < 50.
- **Carrot:** if `PET_CAFE ≥ 1` or carrot price ≥ 50, use carrots (fertilized, 3-day) as filler on up to `6 × (2×PET + FM)` tiles. Otherwise carrots only as D24-D27 filler.

**C12. Opponent-adaptive sizing.** +2-5k. Covers melons (C3), strawberries (C6) and herd (C8), all from `farms[opp].tiles`. Log the opponent's asset counts daily for diagnostics.

**C13. Wheat tick trade** (optional, after M3). Net +0.4-0.7k.
- At steps with `step % 4 == 0`, `step ≤ 716`, `day ≥ 8`:
  - `N = min(50, shed_room, spare_cash // (wheat_price + 2))`.
  - `shed_room = 100 - shed_after_actions - expected_drops_next_step - 8`.
  - `spare_cash = money + this_turn_sales - other_buys - 1500`.
  - If N ≥ 5: append `BUY_PRODUCT WHEAT N` as the **last** order and store N.
- At `step % 4 == 1`: add N to the WHEAT SELL, placed after the steep sells (never slot 0). Exclude these units from feed accounting.

**C14. Guard and robustness** (prevents catastrophic losses).
- Measure `perf_counter` at entry. Planning deadline 0.35-0.45s per step. Below 20s of overage, skip optional compute; below 8s, run only the cheap path. First-call setup < 5s.
- Keep the try/except fallback.
- **Sanity limits:**
  - Never hire more units than projected work justifies.
  - Keep cash ≥ next-day feed + hires.
  - No premium crop or animal purchases without their demand shops, beyond the unconditional minimums (10 strawberries, 3 sheep, 2 cows).
  - Treat any local game < 40k as a bug.

**Labor budget used by the Planner** (daily actions per asset): FULL animal 3.6; MAINT animal 2.2; strawberry 1.1; tomato 1.4; melon 1.0; wheat 3-day fertilized 2.0; wheat 4-day 1.75; carrot 3-day 2.0.
- Capacity = 0.56 × 24 × Umax, i.e. 175 actions a day at 13 units.
- If the plan exceeds capacity, first downgrade wheat to the 4-day cycle, then lower the strawberry and tomato targets. Never add animals because labor is idle.
- Reference plan: 22 animals × 3.6 + 36 strawberries × 1.1 + 30 wheat × 2 = 179.

### 5.3 Milestones and measurable targets (local simulation)
Harness: `tourney.py` (fastsim, parallel, both seats) against `main.py` and self-play, and `tapes.py` TapeAgent against all 52 top-player tapes (both seats). For per-product revenue and labor metrics, extend `ledger.py` or reuse the exact accounting script in the scratchpad (acct.py).

**M1 = C1-C6 + basic C9** (sells first, impact-sorted, floors) **+ C14.**
| Metric | Target | Ours now | Top reference |
|---|---|---|---|
| Money at D1 h0 | ≤ $20 | $578 | $0-19 |
| Fertilizer sold D1-D5 | ≥ 24 units / ≥ $2.2k | ~$600 | $2.29-2.38k |
| Strawberries by D5 / D10 / peak | ≥ 8 / ≥ 20 / 28-44 | 0 | 10 / 19-36 / 34-44 |
| Land days | NE ≤ D6, SW ≤ D9, SE ≤ D11 (when enabled) | D9 / D15-21 / never | D6 / D8-9 / D10-11 |
| Revenue D0-D9 | ≥ $13k | $3.4k | $14-16.3k |
| Melons sold D10-D11, average price | 48-72 units at ≥ $200 | 108 at $137 | 60 at $222-249 |
| Units: D2-5 / D6 / D10+ | 6-7 / ≥ 8 / 12-13 | 3 / 3 / 6-8 | 7 / 9 / 12-13 |
| Empty + weed tiles, mean over D12-D27 | ≤ 6 | 17-23 | 2-10 |
| Self-play mean final (40 seeds × 2 seats) | ≥ 100k | 69k | — |
| vs main.py | ≥ 90% wins, margin ≥ +30k | — | — |

**M2 = + C7, C8, C10.**
| Metric | Target | Ours now | Top reference |
|---|---|---|---|
| Care per animal-day (FULL species) | ≥ 0.85 | 0.37 | 0.84 |
| Fertilizer collected / FERTILIZE / sold | ≥ 95% of animal-days / ≥ 180 / 200-320 | 55% / 56 / 194 | 92-96% / 203 / 310 |
| Strawberry units per plant | ≥ 7.0 | — | 7.2-8.0 |
| Money h0 D15 / D20 / D25 | ≥ 18k / ≥ 50k / ≥ 80k | 14.5k / 26.4k / 42.6k | 15-33k / 43-71k / 67-107k |
| Revenue D10-19 / D20-29 | ≥ 60k / ≥ 80k | 38.6k / 46.1k | 72.6k / 85.6k |
| Self-play mean final | ≥ 115k | 69k | 135k (top-13) |
| vs top tapes (52 × 2 seats) | mean ≥ 110k, ≥ 50% of games won vs the tape | 65.4k | tapes 111.6k vs ours |

**M3 = + full C9, C11, C12.**
| Metric | Target |
|---|---|
| Move share / actions per visit / productive actions per day (D11-26) | ≤ 45% / ≥ 1.8 / ≥ 150 |
| Shed overflow per game / final shed / wheat decayed | ≤ 10 / ≤ 5 / ≤ 5 |
| Units sold at price ≤ $5 (excluding D29) | ≤ 10 per game |
| vs top tapes | mean ≥ 120k, ≥ 65% won; no game < 60k in 100 seeds |

**M4 = C13 polish + A/B winners.** Then submit, and monitor the ladder. A single submission's rating swings ±100 on matchmaking luck, so judge over 50+ games.

### 5.4 Evaluation protocol
- Always use ≥ 40 seeds × both seats with paired comparisons (same seeds, same opponent). Accept a change only if the paired mean-margin t-stat is > 2 and no seed collapses below 40k.
- Opponent pool: main.py; the previous farm2 version; the 52 top tapes; self-play.
- Tapes do not react, so also require self-play gains; self-play alone overstates results against lagging opponents.
- Log per game: revenue by product, money at h0 each day, land days, units per day, move share, care and fertilizer rates, overflow, and units sold ≤ $5. Diff these against the top-reference columns above.

### 5.5 A/B experiments (after M2)
1. Opening 2C+3S+6/10 melons+4 hires (default) vs Boey/TFC 3C+2S+7 melons+13 wheat+5 hires.
2. SE on (≤ D11) vs off vs ≤ D12.
3. Early animals on D2-D5: {none, shop-triggered (default), 1/day like MMPQ}.
4. Wheat harvest age 3 vs 4.
5. Strawberry sizing coefficient {6, 8 (default), 10} per berry shop.
6. Hold-with-drift selling vs immediate selling.
7. Umax 12 vs 13.
8. Melon rule adaptive (default) vs fixed 10 vs fixed 12.
9. Geese FULL vs lean under bakery/brunch.
10. Wheat tick trade on vs off.

### 5.6 Risk register
| Risk | Seen in | Mitigation |
|---|---|---|
| Freed labor spent on bad assets | Prototype: 34 geese and 570 market wheat, lost 5 of 6 | Planner sizes assets to demand + labor budget; wheat self-sufficiency; never buy because labor is idle |
| Demand-blind strawberries | 77 plants with 1 berry shop → 3.9k final | `N_s` formula, drift-aware selling, early dig on crash |
| Cash starvation from carrying goods | carry-all variant 15-36k | Mid-day drops on D0-D10 |
| Unharvested melons lost | 31 of 108 lost in prototype | Melon urgency from age 10; harvest by age 12 |
| Atomic PLANT failure | Engine rule | Exact per-crop seed accounting per turn |
| Shed overflow on D28-29 | Densike left 46 items unsold | Continuous D29 selling, overflow rule, final DROP at step ≤ 718 |
| Timeout | FQ lost a won game | C14 guard |
| Mirror-strategy glut | 113209485: milk $45, strawberries $5 | Opponent-aware caps, MAINT/ABANDON, product pivots |

---

## Appendix A. Formulas
- Animal next production: smallest d ≥ day with `(d+1-placed-fyd) ≥ 0` and `% interval == 0`. Units at that production = `min(max_held, yield + 1 + (bonus if fed that day else 0))`.
- Sheep harvests before the end for placement day P: `floor((29-(P+6))/3)+1`. Cow: `floor((29-(P+8))/2)+1`.
- Care is useful today iff: fed today, and a production d exists with `today < d ≤ 28`, and the animal will be fed on d.
- Units per tile-day: wheat fertilized with harvest at 3 = 5/3; at 4 = 6/4; unfertilized at 4 = 4/4. Carrot fertilized at 3 = 4/3. Melon = 6/10. Strawberry fertilized = 8/17. Tomato fertilized = 8/12.
- Hire cost for the n-th hire of the day: fib(n-1), i.e. 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233.

## Appendix B. Evidence index (episodes cited)
- Openings: 113211945 and 113209485 (吃白饭); 113215092, 113212760, 113207235, 113217709 (MG and clones); 113214297, 113200049 (DECEM); 113207221 (Vadim/Densike); 113207353, 113200052, 113215373, 113207234 (Boey); 113200135, 113216186 (MMPQ); 113207284, 113215406 (FQ); 113215076, 113211971 (TFC); 113214970, 113220846 (TheEggman).
- SE decisive: 113207221 (+15.6k), 113207235 (+9.9k), 113205003 / 113213030 (±0.9k); Boey without SE: 113207353, 113200052.
- Hoarding losses: 113210740 (Majkel). Last-day win: 113200135 (MMPQ). Mirror glut: 113209485. Timeout outlier: 113215371 (not an exploit).
- Market micro (churn/NOOP ≈ 0, slot ordering +650/game, wheat tick +700-900/game): all 52 replays, scratchpad `mm/`.
