"""Download recent ladder episodes of our submissions (the opponents we really face).

python fetch_ladder.py SUBMISSION_ID [SUBMISSION_ID ...] --n 40
Writes replays/episode-*.json and appends episode ids to ladder_set.json (used by gate.py).
"""
import argparse, json, os, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument("subs", nargs="+")
ap.add_argument("--n", type=int, default=40)
a = ap.parse_args()
os.makedirs("replays", exist_ok=True)
path = "ladder_set.json"
have = json.load(open(path)) if os.path.exists(path) else []
for sub in a.subs:
    out = subprocess.run([sys.executable, "-m", "kaggle.cli", "competitions", "episodes", sub, "-v"],
                         capture_output=True, text=True).stdout
    eps = [l.split(",")[0] for l in out.splitlines() if l[:1].isdigit() and "COMPLETED" in l and "PUBLIC" in l]
    for ep in eps[: a.n]:
        if not any(os.path.basename(f).startswith(f"episode-{ep}") for f in os.listdir("replays")):
            subprocess.run([sys.executable, "-m", "kaggle.cli", "competitions", "replay", ep, "-p", "replays", "-q"],
                           capture_output=True)
        if ep not in have:
            have.append(ep)
    print(sub, "episodes considered:", min(len(eps), a.n), flush=True)
json.dump(have, open(path, "w"), indent=0)
print("ladder set size:", len(have))
