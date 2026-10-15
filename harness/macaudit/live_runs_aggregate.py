#!/usr/bin/env python3
"""live_runs_aggregate.py -- between-run statistics for the replicated live study.

probe 303 --runs R writes <out>.run<r>.json (one receipt per run, seeds seed..seed+R-1,
arms interleaved per session).  Table 3 reports single runs with within-run
Clopper-Pearson intervals, which say nothing about run-to-run variation; this
script reports, per model and cell, every run's value, the mean, the range and a
t-interval over runs (R-1 degrees of freedom), and the pooled count with its exact
interval, and emits the LaTeX macros the paper quotes.

    python3 harness/macaudit/live_runs_aggregate.py --root results/live_a1_outcome --tex
"""
from __future__ import annotations
import argparse, glob, json, math, os, re, sys
from collections import defaultdict

METRICS = [("a1", "A1"), ("a7", "R"), ("booking_wrong", "wrong"), ("regenerations", "regen")]
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def binom_cdf(k, n, p):
    from math import comb
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(0, k + 1))


def cp(k, n, alpha=0.05):
    """Clopper-Pearson exact interval, by bisection on the binomial CDF.  (Until 2026-10-14 this fell back to a
    Wald interval when scipy was absent and still printed it under 'exact CI': the first uploaded tools/live_runs.log
    shows [-0.3, 1.6]% for 2/300 and [0.0, 0.0]% for 0/300, which no exact interval can produce; the exact values are
    [0.1, 2.4]% and [0.0, 1.2]%.  The paper never quoted that column; it takes its intervals from claims_from_results.py.)"""
    if n == 0:
        return (0.0, 1.0)
    def solve(f, lo, hi):
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lo = 0.0 if k == 0 else solve(lambda p: 1 - binom_cdf(k - 1, n, p) <= alpha / 2, 0.0, 1.0)
    hi = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p) > alpha / 2, 0.0, 1.0)
    return (lo, hi)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results/live_a1_outcome")
    ap.add_argument("--tex", action="store_true")
    a = ap.parse_args()
    runs = defaultdict(list)   # (model, stem) -> [receipt, ...]
    for fp in sorted(glob.glob(os.path.join(a.root, "*.run*.json"))):
        m = re.match(r"(.+)\.run(\d+)\.json$", os.path.basename(fp))
        if not m:
            continue
        d = json.load(open(fp)); runs[(d["model"], m.group(1))].append(d)
    if not runs:
        print("no *.run<r>.json receipts under", a.root); return 1
    macros = []
    for (model, stem), ds in sorted(runs.items()):
        R = len(ds); n = ds[0]["n"]
        print(f"\n{model} ({stem}): {R} runs, n={n} per cell per run, seeds {[d['seed'] for d in ds]}, interleaved={[d.get('interleaved') for d in ds]}")
        print(f"{'cell':26s} {'metric':6s} {'per run':28s} {'mean':>6s} {'min-max':>9s} {'t-CI over runs':>16s} {'pooled':>8s} {'exact CI':>14s}")
        cells = defaultdict(dict)
        for r, d in enumerate(ds):
            for c in d["cells"]:
                cells[(c["mode"], c["offset_ms"])][r] = c
        for (mode, off), by_run in sorted(cells.items()):
            for key, label in METRICS:
                vals = [by_run[r][key] for r in range(R) if r in by_run]
                mean = sum(vals) / len(vals)
                if len(vals) >= 2:
                    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
                    t = T975.get(len(vals) - 1, 1.96); half = t * sd / math.sqrt(len(vals))
                    ci = f"[{max(0, mean - half):.1f}, {min(n, mean + half):.1f}]"
                else:
                    ci = "n/a"
                pooled = sum(vals); N = n * len(vals)
                lo, hi = cp(pooled, N) if key != "regenerations" else (None, None)
                exact = f"[{100 * lo:.1f}, {100 * hi:.1f}]%" if lo is not None else ""
                print(f"{mode + '@' + str(off) + 'ms':26s} {label:6s} {str(vals):28s} {mean:6.1f} {str(min(vals)) + '-' + str(max(vals)):>9s} {ci:>16s} {str(pooled) + '/' + str(N):>8s} {exact:>14s}")
                if key in ("a1", "a7", "booking_wrong"):
                    k = re.sub(r"[^A-Za-z]", "", f"{model}{mode}{off}{label}")
                    macros.append(f"\\newcommand{{\\Runs{k}}}{{{'/'.join(str(v) for v in vals)}}}")
    if a.tex:
        print("\n% --- replicated live cells (harness/macaudit/live_runs_aggregate.py --tex) ---")
        for m in macros:
            print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
