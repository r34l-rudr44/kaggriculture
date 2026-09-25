"""Prepare a candidate for submission.

python prep_submit.py agents/v5_x.py
- static scan for file I/O / imports of local helper modules (would break on Kaggle)
- copies the file to submission/main.py
- plays one self-play game in the OFFICIAL engine inside an empty temp dir (only main.py present)
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))


def main(src):
    code = open(src, encoding="utf-8").read()
    lines = code.splitlines()
    pats = [r"\bopen\(", r"json\.load\(", r"__file__", r"sys\.path", r"os\.path",
            r"^\s*(import|from)\s+(fastsim|tapes|tourney|panel|ledger|main|validate)\b"]
    hits = []
    for pat in pats:
        for m in re.finditer(pat, code, re.M):
            ln = code[:m.start()].count("\n") + 1
            hits.append(f"line {ln}: {lines[ln - 1].strip()[:120]}")
    if hits:
        print("STATIC FINDINGS (review before submitting):")
        for h in sorted(set(hits)):
            print("  " + h)
    else:
        print("static: no file I/O, no local-module imports")

    os.makedirs(os.path.join(ROOT, "submission"), exist_ok=True)
    dst = os.path.join(ROOT, "submission", "main.py")
    shutil.copyfile(src, dst)
    print("copied to", dst, f"({os.path.getsize(dst)} bytes)")

    tmp = tempfile.mkdtemp(prefix="kg_sub_")
    shutil.copyfile(src, os.path.join(tmp, "main.py"))
    test = (
        "import io, contextlib, time\n"
        "with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):\n"
        "    from kaggle_environments import make\n"
        "t = time.time()\n"
        "env = make('kaggriculture', debug=True)\n"
        "env.run(['main.py', 'main.py'])\n"
        "print('OFFICIAL', [s.reward for s in env.steps[-1]], [s.status for s in env.steps[-1]], "
        "f'{time.time()-t:.0f}s')\n"
    )
    r = subprocess.run([sys.executable, "-c", test], cwd=tmp, capture_output=True, text=True, timeout=1200)
    out = [l for l in r.stdout.splitlines() if l.startswith("OFFICIAL")]
    if out:
        print(out[0])
        ok = "ERROR" not in out[0] and "INVALID" not in out[0] and "TIMEOUT" not in out[0]
        print("SMOKE TEST PASSED" if ok else "SMOKE TEST FAILED")
    else:
        print("SMOKE TEST FAILED")
        print(r.stdout[-1500:])
        print(r.stderr[-1500:])
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1])
