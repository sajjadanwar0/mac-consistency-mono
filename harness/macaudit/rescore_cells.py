#!/usr/bin/env python3
"""rescore_cells.py -- monorepo port of the pilot's check_tables.sh cell gate.

Scores every committed op-record cell named in results/expected.json under
Definition 1 (Anomalies.tla, StaleGeneration: i # j, agent_i # agent_j, the
strict window, value #) with an implementation independent of both the Verus
detector and the Rust analyser, and exits non-zero on any disagreement.

    python3 harness/macaudit/rescore_cells.py --root results
    python3 harness/macaudit/rescore_cells.py --root results --quiet

python3 only; no network, no keys, no cargo.
"""
from __future__ import annotations
import argparse, json, os, sys

NULL = "NULL"


def agent(r):
    a = r.get("agent")
    return a if a is not None else r.get("agent_id")


def load(p):
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def a1(h) -> bool:
    n = len(h)
    for i in range(n):
        for j in range(n):
            if i == j or agent(h[i]) == agent(h[j]):
                continue
            for c in set(h[i].get("read_set") or []) & set(h[j].get("write_set") or []):
                if h[i]["read_time"] < h[j]["write_time"] < h[i]["write_time"] \
                   and (h[i].get("read_values") or {}).get(c, NULL) != (h[j].get("write_values") or {}).get(c, NULL):
                    return True
    return False


def score_dir(d):
    fs = sorted(f for f in os.listdir(d) if f.endswith(".jsonl"))
    return len(fs), sum(1 for f in fs if a1(load(os.path.join(d, f))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    R = a.root
    exp = json.load(open(os.path.join(R, "expected.json")))
    bad, checked, pool = [], 0, {}

    def report(ok, label, k, n, want):
        if not a.quiet:
            print(f"  {'ok ' if ok else 'MISS'} {label:48s} {k:4d}/{n:<4d} expected {want:4d}")

    for stamp, spec in exp["runs"].items():
        for cell, want in spec["cells"].items():
            p = os.path.join(R, "runs", stamp, cell)
            if not os.path.isdir(p):
                bad.append(f"{stamp}/{cell}: directory absent"); continue
            n, k = score_dir(p); checked += 1
            pool.setdefault(cell, [0, 0]); pool[cell][0] += n; pool[cell][1] += k
            ok = (n == want["n"] and k == want["a1"])
            if not ok: bad.append(f"{stamp}/{cell}: scored {k}/{n}, expected {want['a1']}/{want['n']}")
            report(ok, f"runs/{stamp}/{cell}", k, n, want["a1"])
    for cell, want in exp["pooled"].items():
        if cell.startswith("_"): continue
        n, k = pool.get(cell, [0, 0]); checked += 1
        ok = (n == want["n"] and k == want["a1"])
        if not ok: bad.append(f"pooled/{cell}: scored {k}/{n}, expected {want['a1']}/{want['n']}")
        report(ok, f"pooled/{cell}", k, n, want["a1"])
    for model, cells in exp["live"].items():
        if model.startswith("_"): continue
        S = os.path.join(R, model, "sessions")
        if not os.path.isdir(S):
            bad.append(f"live/{model}: sessions/ absent"); continue
        fs = os.listdir(S)
        for kind, want in cells.items():
            sel = sorted(f for f in fs if f.startswith(kind + "_") and f.endswith(".jsonl"))
            k = sum(1 for f in sel if a1(load(os.path.join(S, f)))); checked += 1
            ok = (len(sel) == want["n"] and k == want["a1"])
            if not ok: bad.append(f"live/{model}/{kind}: scored {k}/{len(sel)}, expected {want['a1']}/{want['n']}")
            report(ok, f"{model}/{kind}", k, len(sel), want["a1"])
    for b in bad:
        print("FAIL:", b, file=sys.stderr)
    print(f"{'OK' if not bad else 'FAIL'}: {checked} cells rescored under Definition 1, {len(bad)} disagreement(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
