# Kaggriculture agent

Agent and evaluation tooling for the Kaggle simulation competition
[Kaggriculture](https://www.kaggle.com/competitions/kaggriculture): a two-player farming game
where each player runs a 10x10 farm, both sell into one shared market, and the player with the
most coins after 720 turns wins.

## Agents

| File | Description |
|---|---|
| `agents/v7.py` | Current best. `v6` plus a ring layout opening with cash-sized day-0 orders, melon race priority, a day-by-day strawberry market forecast for planting, and a day-1 melon top-up. |
| `agents/v6.py` | Previous best. `v5_script` plus midnight overflow couriers, retuned demand model, rival-sales tracking with race selling, order-book optimization of premium sales, premium rush. |
| `agents/v5_script.py` | Scripted all-in opening (2 cows + 3 sheep around the shed, care from day 0), state-driven days 1-10, demand-sized strawberries/tomatoes, shop-driven herd, burst job engine. |
| `agents/v5_planner.py` | Alternative design: per-tile action calendars, labor planner, value-based router. |
| `agents/v5_evolve.py` | Alternative design evolved from v4. |
| `agents/v4.py` | Early greedy task-assignment agent (baseline). |

Every agent is a single standard-library file exposing `make_agent(params=None)` and ending with a
top-level `agent(obs, config)` (Kaggle runs the last callable in the file).

## Evaluation tools

| Tool | Purpose |
|---|---|
| `fastsim.py` | Runs the official engine directly (about 10x faster than `kaggle_environments.env.run`, identical results). |
| `tourney.py` | Parallel head-to-head: `python tourney.py agents/v6.py agents/v5_script.py --seeds 24`. |
| `tapes.py` | Turns downloaded top-player replays into replayable action tapes (`python tapes.py build`). |
| `panel.py` | Candidate vs frozen top-player tapes on their original seeds. |
| `panel2.py`, `cmp.py` | Low-noise panel (common random numbers) and paired comparison of two runs. |
| `h2h.py` | Paired head-to-head vs reactive agents in both seats (common random numbers); `--cmp A.json B.json` compares two runs. |
| `ledger.py` | Exact per-product revenue/cost ledger of a game. |
| `validate.py` | Loads a file the way Kaggle does, plays full games, checks errors and timing. |
| `prep_submit.py` | Static checks plus an official-engine smoke test in an empty directory; writes `submission/main.py`. |
| `fetch_replays.py`, `summarize_replay.py` | Download top-player replays (Kaggle CLI) and condense them into per-day summaries. |

## Setup

```bash
pip install -r requirements.txt
python fetch_replays.py 3      # needs Kaggle API credentials; top30.json lists leaderboard submissions
python tapes.py build          # builds tapes/ from replays/
python panel.py agents/v6.py --workers 8
```

## Docs

- `docs/PLAYBOOK.md`: consensus playbook of top agents, from re-simulated top-20 replays.
- `docs/STRATEGY.md`: detailed engine facts, economics, and the implementation plan.
