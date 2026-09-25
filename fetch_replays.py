"""Download recent replays for top leaderboard submissions."""
import json, subprocess, sys, os
per = int(sys.argv[1]) if len(sys.argv) > 1 else 3
top = json.load(open("top30.json"))
os.makedirs("replays", exist_ok=True)
index = []
for rank, team, sub, score in top:
    out = subprocess.run([sys.executable, "-m", "kaggle.cli", "competitions", "episodes", str(sub), "-v"],
                         capture_output=True, text=True).stdout
    eps = [l.split(",")[0] for l in out.splitlines() if l and l[0].isdigit() and "COMPLETED" in l and "PUBLIC" in l]
    for ep in eps[:per]:
        path = f"replays/{ep}.json"
        if not os.path.exists(path):
            subprocess.run([sys.executable, "-m", "kaggle.cli", "competitions", "replay", ep, "-p", "replays", "-q"],
                           capture_output=True, text=True)
        index.append({"rank": rank, "team": team, "sub": sub, "episode": ep})
    print(rank, sub, len(eps), "episodes", flush=True)
json.dump(index, open("replays/index.json", "w"), indent=1)
