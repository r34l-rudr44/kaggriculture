"""Paired comparison of two panel2 results files: python cmp.py results/results_A.json results/results_B.json"""
import json, sys, math
A = {(r[0], r[1], r[2]): r for r in json.load(open(sys.argv[1]))}
B = {(r[0], r[1], r[2]): r for r in json.load(open(sys.argv[2]))}
ks = sorted(set(A) & set(B))
d = [B[k][3] - A[k][3] for k in ks]
dm = [(B[k][3] - B[k][4]) - (A[k][3] - A[k][4]) for k in ks]
n = len(d)
m = sum(d) / n
sd = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, n - 1))
mm = sum(dm) / n
sdm = math.sqrt(sum((x - mm) ** 2 for x in dm) / max(1, n - 1))
wa = sum(1 for k in ks if A[k][3] > A[k][4]); wb = sum(1 for k in ks if B[k][3] > B[k][4])
print(f"n={n}  me diff {m:+.0f} (SE {sd/math.sqrt(n):.0f})  margin diff {mm:+.0f} (SE {sdm/math.sqrt(n):.0f})  wins {wa} -> {wb}")
