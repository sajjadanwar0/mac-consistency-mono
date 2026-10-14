#!/usr/bin/env python3
"""a7_rescore.py -- score the committed live sessions under A7 (superseded-basis
effect), with the basis recovered by ARGUMENT PROVENANCE from the records alone.

A7 (Guarded5.tla, SupersededBasisEffect): an operation i whose effect is out,
some (c, v) in its basis, the LATEST post-commit writer j of c (write_time_j >
write_time_i) wrote a value other than v, and no compensation obligation is
registered for i.

Basis by argument provenance: for an effect-bearing record i (a write to an
external cell -- here `trip/bookings/*`), basis(i) = {(c, read_values_i[c]) :
c in read_set_i and read_values_i[c] appears in the effect's arguments},
where the arguments are the external write values and, when recorded, the
booking text.  No declaration by the agent is used.

Relation to Definition 1: A1 is the window BEFORE commit (superseding write
inside (read_time, write_time)); A7 is the window AFTER it.  The two are
disjoint on a given (i, j) pair and together cover "effect out on a
superseded basis".  On the live data every obligation field is absent (no
ledger ran), so A7 = "booking stale with respect to the final trip date"
re-derived from the TRACE rather than read off the store -- which is the
point: the predicate is decidable on records, the ledger can be verified
against it, and the outcome column of Table 3 is its instance.

    python3 harness/macaudit/a7_rescore.py --root results
    python3 harness/macaudit/a7_rescore.py --root results --check
"""
from __future__ import annotations
import argparse, glob, json, os, sys

EXTERNAL_PREFIX = "trip/bookings/"
MODELS = [("live_a1_gpt4omini", "gpt-4o-mini"), ("live_a1_haiku", "claude-haiku-4-5"), ("live_a1_llama", "llama3.2")]
MODES = ["vanilla", "validated", "sequential"]
EXPECTED = {("live_a1_gpt4omini", "vanilla"): (60, 40, 100), ("live_a1_gpt4omini", "validated"): (0, 34, 34),
            ("live_a1_gpt4omini", "sequential"): (0, 100, 100),
            ("live_a1_haiku", "vanilla"): (91, 9, 100), ("live_a1_haiku", "validated"): (0, 7, 7),
            ("live_a1_haiku", "sequential"): (0, 100, 100),
            ("live_a1_llama", "vanilla"): (1, 99, 100), ("live_a1_llama", "validated"): (0, 100, 100),
            ("live_a1_llama", "sequential"): (0, 100, 100)}


def load(fp):
    return [json.loads(l) for l in open(fp) if l.strip()]


def is_effect(r):
    return any(c.startswith(EXTERNAL_PREFIX) for c in r.get("write_set", []))


def basis(r):
    args = " ".join(str(v) for c, v in r.get("write_values", {}).items() if c.startswith(EXTERNAL_PREFIX))
    args += " " + str(r.get("booking_text", ""))
    # a read value is in the basis iff it appears verbatim in the effect's arguments; an absent
    # read value (None) is never a basis (a NULL read's provenance cannot be recovered from text)
    return {(c, r["read_values"].get(c)) for c in r.get("read_set", [])
            if r["read_values"].get(c) is not None and str(r["read_values"].get(c)) in args}


def a1(h):
    for i, ri in enumerate(h):
        for j, rj in enumerate(h):
            if i == j or ri.get("agent") == rj.get("agent"): continue
            for c in set(ri.get("read_set", [])) & set(rj.get("write_set", [])):
                if ri["read_time"] < rj["write_time"] < ri["write_time"] and ri["read_values"].get(c) != rj["write_values"].get(c):
                    return True
    return False


def obligated(ri, h):
    """the obligation field, or -- for probe 303's ledger arm, whose ledger registers the obligation by firing the
    compensator -- a later compensation record on the same effect cell (ledger.register -> compensate -> emit)"""
    if ri.get("obligation"):
        return True
    cells = [c for c in ri.get("write_set", []) if c.startswith(EXTERNAL_PREFIX)]
    return any(rj.get("compensation") and rj["write_time"] > ri["write_time"] and set(cells) & set(rj.get("write_set", []))
               for rj in h)


def a7(h):
    for i, ri in enumerate(h):
        if not is_effect(ri) or ri.get("compensation") or obligated(ri, h): continue
        for (c, v) in basis(ri):
            later = [rj for rj in h if c in rj.get("write_set", []) and rj["write_time"] > ri["write_time"]]
            if later:
                latest = max(later, key=lambda r: r["write_time"])
                if latest["write_values"].get(c) != v:
                    return True
    return False


def runs_303(fp):
    """probe 303 records: one file per campaign; a trace is one (mode, session) run, and the offset sweep appends
    every offset's run of a session to the same file, each opening with its own seed record"""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in load(fp):
        groups[(r.get("mode"), r.get("session"))].append(r)
    for (mode, sess), g in groups.items():
        cur = []
        for r in g:
            if r.get("seed") and cur:
                yield mode, sess, cur; cur = []
            cur.append(r)
        if cur:
            yield mode, sess, cur


def october(root, check):
    """probe 303 campaigns (results/live_a1_outcome/<model>_<run>.records.jsonl): A1 and R re-derived from the records
    and, with --check, compared with the cells the probe wrote (a1, a7, booking_wrong) in <model>_<run>.json"""
    bad = 0
    for fp in sorted(glob.glob(os.path.join(root, "live_a1_outcome", "*.records.jsonl"))):
        stem = os.path.basename(fp)[:-len(".records.jsonl")]
        cells = {}
        try:
            for c in json.load(open(fp[:-len(".records.jsonl")] + ".json")).get("cells", []):
                cells[(c["mode"], int(c["offset_ms"]))] = c
        except Exception:
            pass
        from collections import defaultdict
        tally = defaultdict(lambda: [0, 0, 0, 0])   # (mode, offset) -> n, a1, r, either
        for mode, sess, h in runs_303(fp):
            off = next((r.get("offset_ms") for r in h if r.get("offset_ms") is not None), None)
            x1, x7 = a1(h), a7(h)
            t = tally[(mode, off)]; t[0] += 1; t[1] += x1; t[2] += x7; t[3] += (x1 or x7)
        for (mode, off), (n, n1, n7, either) in sorted(tally.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0)):
            c = cells.get((mode, off)); exp = (c["a1"], c.get("a7"), c["booking_wrong"]) if c else None
            flag = "" if not c else ("" if exp == (n1, n7, either) else "  MISMATCH vs probe cell " + str(exp))
            print(f"{stem:34s} {mode:11s} {str(off)+'ms':7s} {n:4d} {n1:4d} {n7:4d} {either:9d}{flag}")
            if check and c and exp != (n1, n7, either):
                bad += 1
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default="results"); ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    bad_oct = october(a.root, a.check)
    print(f"{'model':18s} {'mode':11s} {'n':>4s} {'A1':>4s} {'A7':>4s} {'A1 or A7':>9s}   (A1: superseded inside the window; A7: superseded after commit)")
    bad = 0
    for mdir, label in MODELS:
        for mode in MODES:
            files = sorted(glob.glob(os.path.join(a.root, mdir, "sessions", f"store_{mode}_*.jsonl")))
            n = len(files); n1 = n7 = either = 0
            for fp in files:
                h = load(fp); x1, x7 = a1(h), a7(h)
                n1 += x1; n7 += x7; either += (x1 or x7)
            print(f"{label:18s} {mode:11s} {n:4d} {n1:4d} {n7:4d} {either:9d}")
            if a.check and EXPECTED.get((mdir, mode)) != (n1, n7, either):
                bad += 1; print(f"  MISMATCH: expected {EXPECTED.get((mdir, mode))}", file=sys.stderr)
    bad += bad_oct
    if a.check:
        print("OK: A7 table reproduced (September cells and every probe-303 cell)" if not bad else f"FAIL: {bad} cell(s) differ"); return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
