"""Fast local runner for Kaggriculture: drives the official interpreter directly,
skipping kaggle_environments' per-step schema validation and deep copies.

Agents receive live observation objects (they must not mutate them).
play(agent0, agent1, seed) -> (rewards, final_state)
"""
import io, contextlib, importlib.util, os

def _quiet_import():
    # OpenSpiel prints game lists at C level on import; silence fds 1/2 temporarily.
    saved = [os.dup(1), os.dup(2)]
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import kaggle_environments  # noqa: F401
    finally:
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(devnull)
        os.close(saved[0])
        os.close(saved[1])
    return kaggle_environments


kaggle_environments = _quiet_import()
_KG_PATH = os.path.join(os.path.dirname(kaggle_environments.__file__), "envs", "kaggriculture", "kaggriculture.py")
_spec = importlib.util.spec_from_file_location("kg_engine", _KG_PATH)
K = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(K)


class Struct(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


DEFAULT_CFG = {
    "episodeSteps": 720, "actTimeout": 1, "boardSize": 10, "startingMoney": 3000,
    "maxMarketOrdersPerTurn": 10, "turnsPerDay": 24, "shedCapacity": 100,
    "weedSpawnChance": 0.005, "townShopUnlockInterval": 3, "townShopSellInterval": 4,
    "townCenterSellInterval": 24, "farmHandCostMult": 1,
}


class Env:
    def __init__(self, seed, config=None):
        cfg = dict(DEFAULT_CFG)
        if config:
            cfg.update(config)
        cfg["seed"] = seed
        self.configuration = Struct(cfg)
        self.info = {}
        self.done = False


def play(agent0, agent1, seed, config=None, record=None):
    env = Env(seed, config)
    agents = [agent0, agent1]
    state = [Struct(observation=Struct(step=0, remainingOverageTime=60), action=None, status="ACTIVE", reward=0)
             for _ in range(2)]
    state = K.interpreter(state, env)
    step = 0
    n_steps = env.configuration.episodeSteps
    while True:
        for i in range(2):
            state[i].observation.step = step
        actions = []
        for i in range(2):
            try:
                a = agents[i](state[i].observation, env.configuration)
            except Exception:
                a = None
            actions.append(a if isinstance(a, dict) else {})
        if record is not None:
            record.append(actions)
        for i in range(2):
            state[i].action = actions[i]
        state = K.interpreter(state, env)
        step += 1
        if all(s.status != "ACTIVE" for s in state) or step >= n_steps - 1:
            break
    rewards = [s.reward for s in state]
    return rewards, state


if __name__ == "__main__":
    import sys, time
    from tourney import load_agent
    path = sys.argv[2] if len(sys.argv) > 2 else "agents/v6.py"
    t = time.time()
    r, st = play(load_agent(path), load_agent(path), int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(r, f"{time.time()-t:.2f}s")
