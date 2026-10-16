#!/usr/bin/env python3
"""hypothesis_gates.py -- the paper's theorems and detectors are stated under
hypotheses; this gate checks, on EVERY committed operation record, which of
those hypotheses the data satisfies, and prints the counts the paper quotes.

  H1  per-agent non-overlap (Theorem 1 / Lemma 1): no two records of the same
      agent in one trace have overlapping read-to-commit windows.
  H2  value-unique writes (the A3 residue detector's soundness hypothesis,
      Sec. 3.3 / 5.1): within one trace, no two writes to the same cell carry
      the same value.
  H3  overwrite-restore (the one shape in which Definition 1 fires although the
      history is commit-order read consistent): among the A1 witnesses on the
      live records, how many have the read value restored by commit time.
  H4  provenance recall (the A7 / residue basis extractor): among the live
      booking records, how many carry their read date verbatim in the effect's
      arguments (write values or booking text), i.e. how many bases the
      argument-provenance extractor recovers.
  H5  at-most-once externalization (the runtime model's assumption, stated as
      predicate D in formal/tla/Duplication.tla): within one trace, an external
      effect key (trip/bookings/*) written by two or more non-compensation
      records is a duplicate emission.  The interrupt probe's receipt
      (results/python_loose/interrupt_probe_results.json) is reported beside it:
      the one place the artifact observed the hypothesis fail.
  H6  declared vs observed read sets (trust-base item ix, at the store boundary):
      on records that carry `observed_read_set` (probes 303/304 since 2026-10-14),
      the store keys the node actually read between its first read and its
      commit; a key read but not declared is an undeclared store read.  Reads
      that reach the model through prompt context are outside this instrument.

    python3 harness/macaudit/hypothesis_gates.py --root results            # report
    python3 harness/macaudit/hypothesis_gates.py --root results --check    # exit 1 if H1 fails anywhere
    python3 harness/macaudit/hypothesis_gates.py --root results --tex      # claims.tex macros

A trace = one .jsonl file of operation records (a session, a pilot trace, a
synthetic trace).  Records lacking read_time/write_time are skipped and counted.
"""
from __future__ import annotations
import argparse, glob, json, os, sys
from collections import defaultdict

EXTERNAL_PREFIX = "trip/bookings/"


def load(fp):
    out = []
    for line in open(fp):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def traces(root):
    """one trace = one session.  A campaign-wide records.jsonl beside a sessions/ directory is the
    same data twice and is skipped; a file whose records carry a `session` field is split by it."""
    for fp in sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)):
        if os.path.basename(fp) == "records.jsonl" and os.path.isdir(os.path.join(os.path.dirname(fp), "sessions")):
            continue
        rs = load(fp)
        rs = [r for r in rs if "read_time" in r and "write_time" in r]
        if not rs:
            continue
        if any("session" in r for r in rs):
            groups = defaultdict(list)
            for r in rs:
                groups[(r.get("mode"), r.get("experiment"), r.get("session"))].append(r)
            for k, g in groups.items():
                # probe 303's offset sweep appends every offset's run of a session to the same file, each run
                # starting with its own seed record: a seed record opens a new trace
                runs, cur = [], []
                for r in g:
                    if r.get("seed") and cur:
                        runs.append(cur); cur = []
                    cur.append(r)
                if cur:
                    runs.append(cur)
                for i, run in enumerate(runs):
                    yield f"{fp}#{k}#run{i}", run
        else:
            yield fp, rs


def campaign(fp, root):
    rel = os.path.relpath(fp.split("#")[0], root).split(os.sep)
    return rel[0] if len(rel) == 1 else "/".join(rel[:2]) if rel[0] == "runs" else rel[0]


def h0_read_before_commit(rs):
    """records (seed excluded) whose read_time is not strictly before their write_time"""
    return sum(1 for r in rs if not r.get("seed") and not r.get("obligation_for") and not (r["read_time"] < r["write_time"]))


def h1_overlaps(rs):
    """same-agent pairs whose windows overlap: (read_i, write_i) and (read_j, write_j) with read_j < write_i and read_i < write_j"""
    n = 0
    by_agent = defaultdict(list)
    for r in rs:
        if r.get("seed") or r.get("obligation_for"):     # seed writes and ledger registrations are not operations
            continue
        by_agent[r.get("agent")].append((r["read_time"], r["write_time"]))
    for ag, ws in by_agent.items():
        ws.sort()
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                ri, wi = ws[i]; rj, wj = ws[j]
                if rj < wi and ri < wj and (ri, wi) != (rj, wj):
                    n += 1
    return n


def h2_collisions(rs):
    """(cells written >= 2 times, collisions: two writes to the same cell with the same value)"""
    seen = defaultdict(list)
    for r in rs:
        for c, v in (r.get("write_values") or {}).items():
            seen[c].append(json.dumps(v, sort_keys=True))
    multi = sum(1 for c, vs in seen.items() if len(vs) >= 2)
    coll = sum(1 for c, vs in seen.items() if len(vs) != len(set(vs)))
    return multi, coll


def a1_pairs(rs):
    out = []
    for i, ri in enumerate(rs):
        for j, rj in enumerate(rs):
            if i == j or ri.get("agent") == rj.get("agent"):
                continue
            for c in set(ri.get("read_set", [])) & set(rj.get("write_set", [])):
                if ri["read_time"] < rj["write_time"] < ri["write_time"] and ri["read_values"].get(c) != rj["write_values"].get(c):
                    out.append((i, j, c))
    return out


def h3_restored(rs):
    """among A1 witnesses (i, j, c): the value of c at i's commit equals i's read value (overwrite-restore)"""
    wit = a1_pairs(rs); restored = 0
    for i, j, c in wit:
        ri = rs[i]
        # latest write to c strictly before i's commit
        later = [r for r in rs if c in (r.get("write_set") or []) and r["write_time"] < ri["write_time"]]
        if later:
            last = max(later, key=lambda r: r["write_time"])
            if last["write_values"].get(c) == ri["read_values"].get(c):
                restored += 1
    return len(wit), restored


def h4_recall(rs):
    """booking records: basis recovered iff the read date appears verbatim in the effect's arguments"""
    tot = rec = 0
    for r in rs:
        if not any(c.startswith(EXTERNAL_PREFIX) for c in r.get("write_set", [])):
            continue
        if r.get("compensation"):
            continue
        tot += 1
        args = " ".join(str(v) for c, v in r.get("write_values", {}).items() if c.startswith(EXTERNAL_PREFIX)) + " " + str(r.get("booking_text", ""))
        vals = [r["read_values"].get(c) for c in r.get("read_set", [])]
        if any(v is not None and str(v) in args for v in vals):
            rec += 1
    return tot, rec


def h5_duplicates(rs):
    """(external effect keys, keys written by >= 2 non-compensation records in this trace)"""
    writers = defaultdict(int)
    for r in rs:
        if r.get("compensation"):
            continue
        for c in r.get("write_set", []):
            if c.startswith(EXTERNAL_PREFIX):
                writers[c] += 1
    return len(writers), sum(1 for c, n in writers.items() if n >= 2)


def h6_coverage(rs):
    """(records carrying observed_read_set, records with an undeclared store read)"""
    tot = und = 0
    for r in rs:
        obs = r.get("observed_read_set")
        if obs is None:
            continue
        tot += 1
        if set(obs) - set(r.get("read_set", [])):
            und += 1
    return tot, und


# traces converted from third-party transcripts or tool logs: MAST transcripts (mast_oprecords), the production
# code-review traces (production_traces: a cell such as run_python:0 is a tool channel whose write is the request and
# whose read is the response), the racy demo (oprecords) and the synthetic detector fixtures (traces, with deliberate
# ghost values).  Their initial state is not in the trace and their channels are not store cells, so the store axiom
# is REPORTED on them and not gated; H0/H1 (structural) are gated on them like everywhere else.
CONVERTED = {"production_traces", "mast_oprecords", "oprecords", "traces"}


def h7_store_axiom(rs):
    """the store axiom of CommitOrder.tla (ReadsReflectMemory), on the records: a declared read of c returns the
    value of the latest write to c with write_time <= read_time, or NULL when there is none.  Returns
    (reads checked, disagreements with a recorded prior write, non-NULL reads of a cell with no recorded prior write).
    A trace is one session: the latest write is sought among that session's records (seed writes included,
    registration and compensation records excluded, as they are not operations)."""
    writes = defaultdict(list)             # cell -> [(write_time, value)]
    for r in rs:
        if r.get("obligation_for"):
            continue
        for c in r.get("write_set", []):
            if c in r.get("write_values", {}):
                writes[c].append((r["write_time"], r["write_values"][c]))
    for c in writes:
        writes[c].sort(key=lambda t: t[0])
    checked = bad = unrecorded = 0
    for r in rs:
        rv = r.get("read_values")
        if not isinstance(rv, dict) or r.get("seed") or r.get("obligation_for") or r.get("compensation"):
            continue
        for c in r.get("read_set", []):
            if c not in rv:
                continue
            checked += 1
            visible = [(t, v) for t, v in writes.get(c, []) if t <= r["read_time"]]
            got = rv[c]
            if visible:
                if str(got) != str(visible[-1][1]):
                    bad += 1
            elif not (got is None or str(got) == "NULL"):
                unrecorded += 1
    return checked, bad, unrecorded


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results"); ap.add_argument("--check", action="store_true"); ap.add_argument("--tex", action="store_true")
    ap.add_argument("--live-l2", default="crates/runtime/tools/live_l2/sessions", help="live L2 replay receipts (H2 on the data the A3 residue detector scores)")
    ap.add_argument("--include-mock", action="store_true", help="count *mock* campaigns (excluded from the paper's totals by default)")
    a = ap.parse_args()
    per = defaultdict(lambda: {"traces": 0, "records": 0, "h0": 0, "h1": 0, "h2_multi": 0, "h2_coll": 0, "h2_traces_with_coll": 0,
                               "a1": 0, "restored": 0, "book": 0, "recall": 0, "ext": 0, "dup": 0, "obs": 0, "und": 0,
                               "h7_reads": 0, "h7_bad": 0, "h7_unrec": 0, "h7_traces": 0})
    for fp, rs in traces(a.root):
        c = campaign(fp, a.root)
        if "mock" in c and not a.include_mock:
            continue
        d = per[c]
        d["traces"] += 1; d["records"] += len(rs)
        d["h0"] += h0_read_before_commit(rs)
        d["h1"] += h1_overlaps(rs)
        m, k = h2_collisions(rs); d["h2_multi"] += m; d["h2_coll"] += k; d["h2_traces_with_coll"] += (1 if k else 0)
        if c.startswith("live_a1"):
            w, r = h3_restored(rs); d["a1"] += w; d["restored"] += r
            t, r2 = h4_recall(rs); d["book"] += t; d["recall"] += r2
        e, k = h5_duplicates(rs); d["ext"] += e; d["dup"] += k
        o, u = h6_coverage(rs); d["obs"] += o; d["und"] += u
        n7, b7, u7 = h7_store_axiom(rs); d["h7_reads"] += n7; d["h7_bad"] += b7; d["h7_unrec"] += u7; d["h7_traces"] += (1 if n7 else 0)
    # the live L2 replay: the one live campaign the A3 residue detector scores; one plan cell and one
    # result cell per session, so value-uniqueness is the question whether the two values differ
    l2n = l2bad = 0
    for fp in sorted(glob.glob(os.path.join(a.live_l2, "*.json"))):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        if "plan_value" in d and "result_value" in d:
            l2n += 1; l2bad += (d["plan_value"] == d["result_value"])
    tot = {k: sum(d[k] for d in per.values()) for k in next(iter(per.values())).keys()} if per else {}
    print(f"{'campaign':34s} {'traces':>6s} {'records':>8s} {'H1 same-agent overlaps':>23s} {'H2 cells>=2 writes':>18s} {'H2 collisions':>13s} {'A1 wit':>7s} {'restored':>8s} {'bookings':>8s} {'basis recovered':>15s}")
    for c in sorted(per):
        d = per[c]
        print(f"{c:34s} {d['traces']:6d} {d['records']:8d} {d['h1']:23d} {d['h2_multi']:18d} {d['h2_coll']:13d} {d['a1']:7d} {d['restored']:8d} {d['book']:8d} {d['recall']:15d}")
    print(f"{'TOTAL':34s} {tot['traces']:6d} {tot['records']:8d} {tot['h1']:23d} {tot['h2_multi']:18d} {tot['h2_coll']:13d} {tot['a1']:7d} {tot['restored']:8d} {tot['book']:8d} {tot['recall']:15d}")
    coll_campaigns = sorted(c for c, d in per.items() if d["h2_coll"])
    print(f"\nH0: {tot['h0']} records with read_time >= write_time (read-before-commit) over {tot['records']} records")
    print(f"H1: {tot['h1']} same-agent overlapping windows over {tot['records']} records in {tot['traces']} traces")
    print(f"H2: value-unique writes hold in {len(per) - len(coll_campaigns)}/{len(per)} campaigns; collisions in: {coll_campaigns or 'none'} "
          f"({tot['h2_coll']} cells in {tot['h2_traces_with_coll']} traces)")
    if l2n:
        print(f"H2 (live L2 replay, where the A3 residue detector is scored): {l2n} sessions, value collision in {l2bad}")
    print(f"H3: {tot['restored']} of {tot['a1']} live A1 witnesses are overwrite-restore shapes")
    print(f"H4: argument provenance recovers the basis of {tot['recall']}/{tot['book']} live booking records")
    ip = os.path.join(a.root, "python_loose", "interrupt_probe_results.json"); ip_before = ip_div = None
    if os.path.exists(ip):
        try:
            j = json.load(open(ip)); ip_before = len(j.get("effects_before", [])); ip_div = bool(j.get("effects_diverge"))
        except Exception:
            pass
    print(f"H6: {tot['und']} undeclared store reads over {tot['obs']} records that carry an observed read set (0 records = no run has carried it yet)")
    inst = {c: d for c, d in per.items() if c not in CONVERTED}; conv = {c: d for c, d in per.items() if c in CONVERTED}
    h7 = {k: sum(d[k] for d in inst.values()) for k in ("h7_reads", "h7_bad", "h7_unrec", "h7_traces")} if inst else {"h7_reads": 0, "h7_bad": 0, "h7_unrec": 0, "h7_traces": 0}
    h7c = {k: sum(d[k] for d in conv.values()) for k in ("h7_reads", "h7_bad", "h7_unrec")} if conv else {"h7_reads": 0, "h7_bad": 0, "h7_unrec": 0}
    print(f"H7 (store axiom, ReadsReflectMemory) on the store-instrumented campaigns: {h7['h7_bad']} declared reads disagree with the latest "
          f"visible write and {h7['h7_unrec']} read a never-written cell as non-NULL, over {h7['h7_reads']} declared reads in {h7['h7_traces']} traces; "
          f"converted campaigns {sorted(conv)}: {h7c['h7_reads']} reads, {h7c['h7_bad']} disagree, {h7c['h7_unrec']} unrecorded (tool channels and transcripts: reported, not gated)")
    print(f"H5: {tot['dup']} external effect keys emitted twice over {tot['ext']} externalized effects in the committed records"
          + (f"; the interrupt probe emitted the pre-gate effect {ip_before} times (arguments diverge: {ip_div})" if ip_before is not None else ""))
    if a.tex:
        print("\n% --- hypothesis gates (harness/macaudit/hypothesis_gates.py --tex) ---")
        print(f"\\newcommand{{\\HypRecords}}{{{tot['records']:,}}}".replace(",", "{,}"))
        print(f"\\newcommand{{\\HypTraces}}{{{tot['traces']:,}}}".replace(",", "{,}"))
        print(f"\\newcommand{{\\HypReadBeforeCommitViolations}}{{{tot['h0']}}}")
        print(f"\\newcommand{{\\HypSameAgentOverlaps}}{{{tot['h1']}}}")
        print(f"\\newcommand{{\\HypCampaigns}}{{{len(per)}}}")
        print(f"\\newcommand{{\\HypValueUniqueCampaigns}}{{{len(per) - len(coll_campaigns)}}}")
        print(f"\\newcommand{{\\HypCollisionCells}}{{{tot['h2_coll']}}}")
        print(f"\\newcommand{{\\HypCollisionTraces}}{{{tot['h2_traces_with_coll']}}}")
        print(f"\\newcommand{{\\HypLiveLtwoSessions}}{{{l2n}}}")
        print(f"\\newcommand{{\\HypLiveLtwoCollisions}}{{{l2bad}}}")
        print(f"\\newcommand{{\\HypAOneWitnesses}}{{{tot['a1']}}}")
        print(f"\\newcommand{{\\HypRestored}}{{{tot['restored']}}}")
        print(f"\\newcommand{{\\HypBookings}}{{{tot['book']}}}")
        print(f"\\newcommand{{\\HypBasisRecovered}}{{{tot['recall']}}}")
        print(f"\\newcommand{{\\HypExternalEffects}}{{{tot['ext']:,}}}".replace(",", "{,}"))
        print(f"\\newcommand{{\\HypDuplicateEffects}}{{{tot['dup']}}}")
        print(f"\\newcommand{{\\HypObservedRecords}}{{{tot['obs']:,}}}".replace(",", "{,}"))
        print(f"\\newcommand{{\\HypUndeclaredReads}}{{{tot['und']}}}")
        if ip_before is not None:
            print(f"\\newcommand{{\\HypInterruptEmissions}}{{{ip_before}}}")
        print(f"\\newcommand{{\\HypStoreAxiomReads}}{{{h7['h7_reads']:,}}}".replace(",", "{,}"))
        print(f"\\newcommand{{\\HypStoreAxiomTraces}}{{{h7['h7_traces']:,}}}".replace(",", "{,}"))
        print(f"\\newcommand{{\\HypStoreAxiomViolations}}{{{h7['h7_bad'] + h7['h7_unrec']}}}")
        print(f"\\newcommand{{\\HypStoreAxiomConvertedReads}}{{{h7c['h7_reads']:,}}}".replace(",", "{,}"))
        print(f"\\newcommand{{\\HypStoreAxiomConvertedCampaigns}}{{{len(conv)}}}")
    if a.check and (tot["h1"] or tot["h0"] or h7["h7_bad"] or h7["h7_unrec"]):
        print("FAIL: Theorem 1's hypotheses do not hold on this data (H0 read-before-commit, H1 per-agent non-overlap or H7 store axiom violated)"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
