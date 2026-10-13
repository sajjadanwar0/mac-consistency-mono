#!/usr/bin/env python3
"""outcome_rescore.py -- score the live A1 study (Table 6 / Sec 5.11) on the
OUTCOME the introduction motivates, not on the predicate.

The paper's "material" column is computed as

    stale_in_booking_text = A1_fired AND date_used in text AND final not in text

i.e. it is CONDITIONED ON THE FLAG, so it can never exceed the A1 count.  The
harm the introduction describes -- "a booking that contradicts the system's
now-current state" -- is simply

    date_in_booking != date_at_commit

which every session records.  This script prints both, per model and mode, and
emits a LaTeX table.  It needs no API key and no third-party package.

    python3 outcome_rescore.py --root results            # monorepo layout
    python3 outcome_rescore.py --root ../mac-consistency-pilot/python   # old layout
    python3 outcome_rescore.py --root results --tex > outcome_table.tex
    python3 outcome_rescore.py --root results --check    # exit 1 if the numbers
                                                         # below are not reproduced

What it establishes (committed data, 2026-09-13 runs):

  model          mode        A1   wrong-booking  regenerations
  gpt-4o-mini    vanilla     60   100/100        0
  gpt-4o-mini    validated    0    34/100        66
  gpt-4o-mini    sequential   0   100/100        0
  claude-haiku   vanilla     91   100/100        0
  claude-haiku   validated    0     7/100        93
  claude-haiku   sequential   0   100/100        0
  llama3.2       vanilla      1   100/100        0
  llama3.2       validated    0   100/100        0
  llama3.2       sequential   0   100/100        0

Read: the L1 discipline removes every FIRING (true) but leaves the booking
contradicting the trip date in 34%, 7% and 100% of sessions, because the
harness forces a revision in 100% of sessions and L1 only catches the ones
whose timing lands inside the window.  The "sequential control" that the paper
reports as clean (0/100) produces the wrong booking in 100/100 sessions.
"""
from __future__ import annotations
import argparse, json, os, sys

MODELS = [("live_a1_gpt4omini", "gpt-4o-mini"), ("live_a1_haiku", "claude-haiku-4-5"),
          ("live_a1_llama", "llama3.2")]
MODES = ["vanilla", "validated", "sequential"]

EXPECTED = {  # (model_dir, mode) -> (a1, wrong_booking, regenerations)
    ("live_a1_gpt4omini", "vanilla"): (60, 100, 0), ("live_a1_gpt4omini", "validated"): (0, 34, 66),
    ("live_a1_gpt4omini", "sequential"): (0, 100, 0),
    ("live_a1_haiku", "vanilla"): (91, 100, 0), ("live_a1_haiku", "validated"): (0, 7, 93),
    ("live_a1_haiku", "sequential"): (0, 100, 0),
    ("live_a1_llama", "vanilla"): (1, 100, 0), ("live_a1_llama", "validated"): (0, 100, 0),
    ("live_a1_llama", "sequential"): (0, 100, 0),
}


def clopper_pearson(k: int, n: int, alpha: float = 0.05):
    # exact interval via the beta quantile, stdlib only (bisection on the regularized
    # incomplete beta is overkill: use the F-distribution-free binomial search).
    from math import comb
    def cdf(p, k, n): return sum(comb(n, i) * p**i * (1 - p)**(n - i) for i in range(k + 1))
    def solve(target, k, n, lo=0.0, hi=1.0):
        for _ in range(60):
            mid = (lo + hi) / 2
            if cdf(mid, k, n) > target: lo = mid
            else: hi = mid
        return (lo + hi) / 2
    lo = 0.0 if k == 0 else solve(1 - alpha / 2, k - 1, n)
    hi = 1.0 if k == n else solve(alpha / 2, k, n)
    return lo, hi


def load(root: str, mdir: str) -> dict:
    p = os.path.join(root, mdir, "results.json")
    with open(p) as f:
        return json.load(f)


def score(root: str):
    rows = []
    for mdir, label in MODELS:
        r = load(root, mdir)
        for mode in MODES:
            sess = r["store"][mode]["sessions"]
            n = len(sess)
            a1 = sum(1 for s in sess if s["a1"])
            wrong = sum(1 for s in sess if s["date_in_booking"] != s["date_at_commit"])
            wrong_clean = sum(1 for s in sess if (not s["a1"]) and s["date_in_booking"] != s["date_at_commit"])
            regen = sum(s.get("regenerations", 0) for s in sess)
            material_paper = sum(1 for s in sess if s.get("stale_in_booking_text"))
            rows.append(dict(model=label, mdir=mdir, mode=mode, n=n, a1=a1, wrong=wrong,
                             wrong_clean=wrong_clean, regen=regen, material_paper=material_paper,
                             ci=clopper_pearson(wrong, n)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results", help="dir holding live_a1_* directories")
    ap.add_argument("--tex", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    rows = score(a.root)
    if a.tex:
        print(r"\begin{tabular}{llrrrr}")
        print(r"\toprule")
        print(r"Model & Mode & $A_1$ fires & ``material'' (paper) & booking $\neq$ final date & regen.\\")
        print(r"\midrule")
        for r in rows:
            lo, hi = r["ci"]
            print(f"{r['model']} & {r['mode']} & {r['a1']}/{r['n']} & {r['material_paper']} & "
                  f"{r['wrong']}/{r['n']} [{100*lo:.1f}, {100*hi:.1f}] & {r['regen']}\\\\")
        print(r"\bottomrule")
        print(r"\end{tabular}")
        return 0
    print(f"{'model':18s} {'mode':11s} {'n':>4s} {'A1':>4s} {'paper-material':>14s} {'booking!=final':>14s} {'of which A1=0':>13s} {'regen':>6s}")
    for r in rows:
        print(f"{r['model']:18s} {r['mode']:11s} {r['n']:4d} {r['a1']:4d} {r['material_paper']:14d} "
              f"{r['wrong']:14d} {r['wrong_clean']:13d} {r['regen']:6d}")
    if a.check:
        bad = 0
        for r in rows:
            exp = EXPECTED[(r["mdir"], r["mode"])]
            got = (r["a1"], r["wrong"], r["regen"])
            if exp != got:
                bad += 1
                print(f"MISMATCH {r['mdir']}/{r['mode']}: expected {exp} got {got}", file=sys.stderr)
        print("OK: outcome table reproduced" if not bad else f"FAIL: {bad} cell(s) differ")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
