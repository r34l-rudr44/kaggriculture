"""Frozen top-player opponents from recorded replays.

Build compact tape files once:  python tapes.py build
Each tape: {"seed", "names", "rewards", "actions": [[a0, a1] per step]} saved to tapes/<ep>.json
TapeAgent(ep, seat) replays the recorded actions of that seat.
"""
import json, os, glob, sys

TAPE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tapes")


def build():
    os.makedirs(TAPE_DIR, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(os.path.dirname(TAPE_DIR), "replays", "episode-*-replay.json"))):
        ep = os.path.basename(f).split("-")[1]
        out = os.path.join(TAPE_DIR, f"{ep}.json")
        if os.path.exists(out):
            continue
        j = json.load(open(f))
        steps = j["steps"]
        acts = [[steps[t + 1][p].get("action") or {} for p in range(2)] for t in range(len(steps) - 1)]
        json.dump({"seed": j["info"]["seed"], "names": j["info"]["TeamNames"],
                   "rewards": [s["reward"] for s in steps[-1]], "actions": acts}, open(out, "w"))
        print("built", ep, flush=True)


_CACHE = {}


def load(ep):
    if ep not in _CACHE:
        _CACHE[ep] = json.load(open(os.path.join(TAPE_DIR, f"{ep}.json")))
    return _CACHE[ep]


class TapeAgent:
    def __init__(self, ep, seat):
        self.t = load(ep)
        self.seat = seat

    def __call__(self, obs, cfg=None):
        step = obs["step"] if isinstance(obs, dict) else obs.step
        acts = self.t["actions"]
        if step < len(acts):
            return acts[step][self.seat]
        return {}


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1] == "check":
        import fastsim
        ep = sys.argv[2]
        t = load(ep)
        r, _ = fastsim.play(TapeAgent(ep, 0), TapeAgent(ep, 1), t["seed"])
        print(ep, "replayed", r, "recorded", t["rewards"])
