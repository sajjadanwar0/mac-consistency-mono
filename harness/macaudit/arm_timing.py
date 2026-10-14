#!/usr/bin/env python3
"""arm_timing.py -- are the arms of Table 3 the same race?  (receipt-derived; no model calls)

The October four-arm run (probe 303, *_arms150.json) executed its arms as
SEQUENTIAL BLOCKS of 100 sessions (vanilla, then validated, then verified, then
ledger).  The residue R under an L1 discipline is the share of sessions whose
revision landed AFTER the flight agent's commit, i.e. a race between two
provider latencies (the flight agent's generation, recorded per session as
`pinned_seconds`, and the date agent's generation, not recorded in that run)
plus the fixed 150 ms offset.  Two arms that are the same discipline can
therefore differ by provider drift between their blocks, and the paper must
not attribute such a difference to the discipline or to "sampling".

This script reads the committed receipts and prints, per model and arm:
  * the pinned-interval distribution of the flight agent (what the harness
    recorded about the race), and
  * R, A1, regenerations, and Fisher's exact test between the two L1 arms of
    the same run (validated vs verified) and between the September and October
    validated arms, so the text can say exactly how large a block-to-block
    difference the design produces when nothing but the block changes.
It writes the LaTeX macros the paper quotes (--tex) and exits non-zero under
--check if any receipt is missing or an arm has n != 100.

    python3 harness/macaudit/arm_timing.py --root results            # table
    python3 harness/macaudit/arm_timing.py --root results --tex      # macros for claims_results.tex
"""
from __future__ import annotations
import argparse, glob, json, os, statistics as st, sys
from collections import defaultdict

ARMS = ["vanilla", "validated", "verified", "ledger"]


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """exact two-sided p for the 2x2 table [[a, b], [c, d]] (no scipy needed)"""
    from math import comb
    n = a + b + c + d
    r1, c1 = a + b, a + c
    def p_of(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
    p_obs = p_of(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return min(1.0, sum(p_of(x) for x in range(lo, hi + 1) if p_of(x) <= p_obs * (1 + 1e-12)))


def load_records(fp):
    out = []
    for line in open(fp):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results")
    ap.add_argument("--tex", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    receipts = sorted(glob.glob(os.path.join(a.root, "live_a1_outcome", "*_arms150.json")))
    if not receipts:
        print("no *_arms150.json receipts under", a.root); return 1
    september = {}   # model -> (validated residue, vanilla A1) from the September run, re-derived from its records
    for d in sorted(glob.glob(os.path.join(a.root, "live_a1_*", "results.json"))):
        try:
            r = json.load(open(d))
        except Exception:
            continue
        if "store" not in r or "validated" not in r["store"]:
            continue
        # residue under L1 = sessions whose booking value differs from the last value written to the date
        # cell (the same quantity a7_rescore.py / outcome_rescore.py report for the September cells)
        wrong = 0
        sess_files = sorted(glob.glob(os.path.join(os.path.dirname(d), "sessions", "store_validated_*.jsonl")))
        for sf in sess_files:
            rs = load_records(sf)
            dates = [x for x in rs if "trip/state/date" in x.get("write_set", [])]
            books = [x for x in rs if any(c.startswith("trip/bookings/") for c in x.get("write_set", []))]
            if dates and books:
                final = max(dates, key=lambda x: x["write_time"])["write_values"]["trip/state/date"]
                booked = [v for c, v in books[-1]["write_values"].items() if c.startswith("trip/bookings/")][0]
                wrong += (booked != final)
        september[r["model"]] = {"vanilla_a1": r["store"]["vanilla"]["a1_fires"],
                                 "validated_wrong": wrong if sess_files else None}
    rows, macros, problems = [], [], []
    print(f"{'model':18s} {'arm':10s} {'n':>4s} {'A1':>4s} {'R':>4s} {'wrong':>6s} {'regen':>6s} {'pinned mean':>12s} {'median':>7s} {'p10':>6s} {'p90':>6s} {'min':>6s}")
    for fp in receipts:
        d = json.load(open(fp)); model = d["model"]
        recs = load_records(fp.replace(".json", ".records.jsonl"))
        pinned = defaultdict(list)
        for r in recs:
            if r.get("agent") == "flight_agent" and "pinned_seconds" in r:
                pinned[r["mode"]].append(float(r["pinned_seconds"]))
        cells = {c["mode"]: c for c in d["cells"] if c["offset_ms"] == 150}
        for arm in ARMS:
            c = cells.get(arm)
            if c is None:
                problems.append(f"{model}: arm {arm} missing"); continue
            if c["n"] != 100:
                problems.append(f"{model}: arm {arm} has n={c['n']}")
            v = pinned[arm]; q = st.quantiles(v, n=10) if len(v) >= 10 else [0] * 9
            print(f"{model:18s} {arm:10s} {c['n']:4d} {c['a1']:4d} {c['a7']:4d} {c['booking_wrong']:6d} {c['regenerations']:6d} {st.mean(v):12.3f} {st.median(v):7.3f} {q[0]:6.3f} {q[8]:6.3f} {min(v):6.3f}")
            rows.append((model, arm, c, v))
        va, ve = cells.get("validated"), cells.get("verified")
        if va and ve:
            p = fisher_two_sided(va["a7"], 100 - va["a7"], ve["a7"], 100 - ve["a7"])
            print(f"{'':18s} validated R={va['a7']} vs verified R={ve['a7']} (same run, sequential blocks): Fisher p={p:.3f}")
            key = {"claude-haiku-4-5": "Haiku", "gpt-4o-mini": "Gpt", "deepseek-chat": "Deepseek"}.get(model, model.replace("-", ""))
            macros.append(f"\\newcommand{{\\ArmFisher{key}}}{{{p:.3f}}}")
            macros.append(f"\\newcommand{{\\ArmPinnedValidated{key}}}{{{st.median(pinned['validated']):.2f}}}")
            macros.append(f"\\newcommand{{\\ArmPinnedVerified{key}}}{{{st.median(pinned['verified']):.2f}}}")
        s = september.get(model)
        if s and s.get("validated_wrong") is not None and va:
            p = fisher_two_sided(s["validated_wrong"], 100 - s["validated_wrong"], va["a7"], 100 - va["a7"])
            p2 = fisher_two_sided(s["vanilla_a1"], 100 - s["vanilla_a1"], cells["vanilla"]["a1"], 100 - cells["vanilla"]["a1"])
            print(f"{'':18s} September validated residue={s['validated_wrong']} vs October={va['a7']}: Fisher p={p:.3f};  vanilla A1 {s['vanilla_a1']} vs {cells['vanilla']['a1']}: p={p2:.3f}")
            key = {"claude-haiku-4-5": "Haiku", "gpt-4o-mini": "Gpt"}.get(model)
            if key:
                macros.append(f"\\newcommand{{\\RunFisherValidated{key}}}{{{p:.3f}}}")
                macros.append(f"\\newcommand{{\\RunFisherVanilla{key}}}{{{p2:.3f}}}")
    print("\nArms were executed as sequential blocks (probe 303 loops modes, then sessions); "
          "a block-to-block latency drift changes where the revision lands, so an arm difference "
          "is attributable to the discipline only when the arms are interleaved per session "
          "(probe 303 --interleave).")
    if a.tex:
        print("\n% --- arm timing (harness/macaudit/arm_timing.py --tex) ---")
        for m in macros:
            print(m)
    if problems:
        for p in problems:
            print("PROBLEM", p)
        return 1 if a.check else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
