#!/usr/bin/env python3
"""303_live_a1_outcome.py -- the live LangGraph A1 study, re-run as an OUTCOME
experiment with a revision PROBABILITY instead of a forced revision.

What is wrong with Sec 5.11 as it stands (committed data, see
harness/macaudit/outcome_rescore.py):

  * the date agent revises the trip date in 100% of sessions, so the booking
    contradicts the final trip date in 100/100 vanilla AND 100/100 "sequential
    control" sessions; A1 catches only the timing-dependent subset (60, 91, 1);
  * under the L1 discipline the booking is STILL wrong in 34 / 7 / 100 of 100
    sessions (the revision landed after the commit), yet the paper reports
    "read-set validation removes every firing" and a "material" column that is
    conditioned on the flag;
  * the per-model rates (60% vs 91% vs 1%) are the ratio of two API latencies
    plus a hard-coded 150 ms, not a property of the framework.

This probe keeps the paper's harness (it imports it, unmodified) and changes
three things so the numbers mean something:

  1. --p-revise P   the revision happens with probability P per session (seeded),
                    so "booking != final" has a denominator the harness did not
                    force to 100%;
  2. --offset-ms    the start offset of the date agent is SWEPT (0, 150, 500,
                    1500 ms) instead of fixed at 150 ms, giving the firing rate as
                    a function of relative latency -- the quantity the paper's
                    "60% vs 91%" actually is;
  3. outcome        every session records booking_matches_final (the harm),
                    a1 and a7 (the predicates), and regenerations (the cost), and
                    the receipt reports all of them per cell, with Clopper-Pearson CIs;
  4. --modes ledger the L5 discipline: the L1 validated commit PLUS a basis
                    ledger at the store.  Every externalized booking registers its
                    basis {(trip/state/date, date_used)} by argument provenance and
                    a compensator; a later put that supersedes a basis value
                    registers a compensation obligation atomically and runs the
                    compensator (rebook with the new date: one more generation).
                    The receipt counts obligations registered / discharged and the
                    outcome, so the paper can report L5 on the same harness as L1.
  5. --modes verified  the SAME L1 discipline, but the commit/abort decision is taken
                    by the VERIFIED L1 store (crates/runtime, si_concurrent::SiConcurrent,
                    Verus-verified) running as a subprocess (examples/l1_server.rs,
                    JSON over stdio; --l1-server points at the binary).  Every store
                    read is paired with a verified `begin`, every put with a verified
                    `commit`, under one harness mutex so the two stores agree; a
                    refused commit regenerates.  This closes "the flagship study runs
                    an application-layer discipline, not the verified bytes": in this
                    mode the bytes that decide are the verified ones, and the bridge
                    (~100 lines of Rust + the interning below) is the only addition
                    to the trust base.  The per-session verified trace is kept in the
                    receipt.

    uv run --project envs/langgraph-1.2.0 python probes/303_live_a1_outcome.py \
        --provider openai --model gpt-4o-mini --n 100 --p-revise 0.5 \
        --offsets 0,150,500,1500 --modes vanilla,validated,sequential \
        --out results/live_a1_outcome/gpt-4o-mini.json

    python3 probes/303_live_a1_outcome.py --provider mock --n 20 --offsets 0,150   # mock model (langgraph still needed)
    cargo build --release --manifest-path crates/runtime/Cargo.toml --example l1_server   # once, for --modes verified

Reads the paper's harness from probes/*_langgraph_live_a1.py (monorepo) or
python/langgraph_live_a1.py (old layout).

Added 2026-10-14 (the arm-timing objection, harness/macaudit/arm_timing.py):
  --interleave      run the arms per SESSION in a seeded random order (session 0: all
                    modes, then session 1: all modes, ...) instead of as sequential
                    blocks, so provider-latency drift hits every arm alike and an arm
                    difference is attributable to the arm; order.tsv is the receipt.
  wall-clock stamps every record carries wall_read_ms / wall_commit_ms (ms since the
                    session's seed write) and every session reports revision_lag_ms =
                    date agent's commit - flight agent's commit: negative = the revision
                    landed inside the window (A1, or regenerated under L1), positive =
                    after the commit (the residue R), so R can be reported as a function
                    of the race distribution rather than as a point rate.
  --modes ledger_verified  the ledger over the VERIFIED L1 store (commit decision by
                    si_concurrent through the bridge, basis ledger + compensator on top),
                    so the ledger row of Table 3 and the verified row rest on one store.
  --runs R          repeat the whole protocol R times with seed, seed+1, ...; one receipt
                    per run (<out>.run<r>.json); harness/macaudit/live_runs_aggregate.py
                    reports between-run intervals.
"""
from __future__ import annotations
import argparse, glob, importlib.util, json, os, random, statistics, sys, threading, time
from datetime import date, timedelta
from typing import Any



class BasisLedger:
    """L5 at the store: effects register (key, basis, compensator); a put that
    supersedes a basis value registers an obligation and runs the compensator.
    `on_register(key, cell, new_value)` (2026-10-14) is called at registration, BEFORE the
    compensator runs, so the probe can emit an explicit obligation record and the scorer
    decides R from the registration itself rather than from the compensation that followed."""
    def __init__(self, on_register=None):
        self.effects = {}      # key -> {"basis": {cell: value}, "compensate": fn, "obligation": bool, "discharged": bool}
        self.lock = threading.Lock()
        self.registered = 0; self.discharged = 0
        self.on_register = on_register

    def register(self, key, basis, compensate):
        with self.lock:
            self.effects[key] = {"basis": dict(basis), "compensate": compensate, "obligation": False, "discharged": False}

    def mark(self, cell, new_value):
        """REGISTRATION ONLY: set the obligation flag of every effect whose basis the write supersedes and return them.
        No callback, no model call: the ledgered store calls this INSIDE the store lock, in the same critical section as
        the superseding write, so the registration is atomic with it (the Verus model's write step)."""
        todo = []
        with self.lock:
            for key, e in self.effects.items():
                if cell in e["basis"] and e["basis"][cell] != new_value and not e["obligation"]:
                    e["obligation"] = True; self.registered += 1; todo.append((key, e))
        return todo

    def discharge(self, todo, cell, new_value, t=None):
        """the registration RECORD (stamped with the superseding put's stamp t) and the compensation, outside the lock"""
        for key, e in todo:
            if self.on_register is not None:
                self.on_register(key, cell, new_value, t=t)
            e["compensate"](new_value)
            with self.lock:
                e["discharged"] = True; self.discharged += 1
                e["basis"][cell] = new_value   # the compensated effect's basis is now current ...
                e["obligation"] = False        # ... and it is a fresh effect: a further revision owes a further obligation

    def superseded(self, cell, new_value):
        """the pre-2026-10-16 path (registration after the put returned): mark, then discharge"""
        self.discharge(self.mark(cell, new_value), cell, new_value)


# 2026-10-16: the executed ledger registers ATOMICALLY with the superseding write (inside the store's lock), as the
# Verus model does. "after" reproduces the receipts of 2026-10-14/15, in which registration followed the put.
LEDGER_REGISTRATION = "atomic"


def observed_store(H, clock, ledger=None):
    """the paper's InstrumentedStore (or its ledgered subclass) with per-thread tracking of the
    store KEYS a node read, so that each operation record can carry `observed_read_set` -- every
    store read the node performed between its first read and its commit -- beside the read set the
    harness DECLARES (hypothesis_gates.py H6 compares the two: trust-base item (ix), measured at
    the store boundary; reads that reach the model through prompt context are outside it)."""
    base = ledgered_store(H, clock, ledger).__class__ if ledger else H.InstrumentedStore
    class ObservedStore(base):
        def __init__(self, *a_, **k_):
            super().__init__(*a_, **k_)
            self._reads = {}
        def get(self, namespace, key, *args, **kwargs):
            r = super().get(namespace, key, *args, **kwargs)
            self._reads.setdefault(threading.get_ident(), []).append("/".join(namespace) + "/" + key)
            return r
        def reads_reset(self): self._reads[threading.get_ident()] = []
        def reads_snapshot(self): return sorted(set(self._reads.get(threading.get_ident(), [])))
    return ObservedStore(clock)


def ledgered_store(H, clock, ledger):
    """subclass the paper's InstrumentedStore so that put() notifies the ledger.
    LEDGER_REGISTRATION == "atomic": the old value is read, the new one installed, the clock stamped AND the obligations
    flagged in ONE critical section of the store lock; the registration record and the compensation follow outside it.
    LEDGER_REGISTRATION == "after": the 2026-10-14/15 behaviour (put, release the lock, then notify the ledger)."""
    class LedgeredStore(H.InstrumentedStore):
        def put(self, namespace, key, value, *args, **kwargs):
            cell = "/".join(namespace) + "/" + key
            if LEDGER_REGISTRATION == "atomic" and cell == H.DATE_CELL:
                with self.clock.lock:
                    old = super(H.InstrumentedStore, self).get(namespace, key)        # InMemoryStore.get: not a node read
                    super(H.InstrumentedStore, self).put(namespace, key, value, *args, **kwargs)
                    self.clock.t += 1; t = self.clock.t
                    new = value["date"]
                    todo = ledger.mark(cell, new) if (old is None or old.value.get("date") != new) else []
                self.local.last = ("put", t, time.perf_counter())
                self.log.append({"op": "put", "ns": "/".join(namespace), "key": key, "t": t})
                saved = self.local.last          # the compensator runs in this thread and must not clobber the caller's stamp
                if todo:
                    ledger.discharge(todo, cell, new, t=t)
                self.local.last = saved
                return None
            old = H.InstrumentedStore.get(self, namespace, key)   # the hook's own read: not a node read (H6)
            r = super().put(namespace, key, value, *args, **kwargs)
            saved = self.local.last
            if cell == H.DATE_CELL:
                new = value["date"]
                if old is None or old.value.get("date") != new:
                    ledger.superseded(cell, new)
            self.local.last = saved
            return r
    return LedgeredStore(clock)



EXTERNAL_PREFIX = "trip/bookings/"

class VerifiedBridge:
    """JSON-lines client of crates/runtime/examples/l1_server.rs (the verified SiConcurrent store).
    Strings are interned to small integers here; the verified store sees cells and values as usize."""

    def __init__(self, binary):
        import subprocess
        if not os.path.exists(binary):
            raise SystemExit(f"--l1-server {binary} not found: cargo build --release --manifest-path crates/runtime/Cargo.toml --example l1_server")
        self.p = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.lock = threading.Lock()          # pairs a LangGraph get/put with its verified begin/commit
        self.cells: dict[str, int] = {}; self.vals: dict[str, int] = {}

    def _rpc(self, obj):
        assert self.p.stdin and self.p.stdout
        self.p.stdin.write(json.dumps(obj) + "\n"); self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line: raise RuntimeError("l1_server exited")
        r = json.loads(line)
        if "error" in r: raise RuntimeError(r["error"])
        return r

    def cell(self, name): return self.cells.setdefault(name, len(self.cells) + 1)
    def val(self, v):     return self.vals.setdefault(str(v), len(self.vals) + 1)
    def begin(self, agent, cells): return self._rpc({"op": "begin", "agent": agent, "cells": [self.cell(c) for c in cells]})
    def commit(self, snap, writes):
        r = self._rpc({"op": "commit", "snap": snap["snap"], "writes": [[self.cell(c), self.val(v)] for c, v in writes]})
        return bool(r["ok"]), int(r["time"])
    def clock(self): return int(self._rpc({"op": "clock"})["time"])
    def trace(self): return self._rpc({"op": "trace"})["trace"]
    def close(self):
        try: self._rpc({"op": "quit"})
        except Exception: pass


def a7_fires(h):
    """SupersededBasisEffect (Guarded5.tla) with the basis recovered by argument provenance."""
    for ri in h:
        if not any(c.startswith(EXTERNAL_PREFIX) for c in ri.get("write_set", [])): continue
        if ri.get("obligation") or ri.get("compensation"): continue
        args = " ".join(str(v) for c, v in ri.get("write_values", {}).items() if c.startswith(EXTERNAL_PREFIX)) + " " + str(ri.get("booking_text", ""))
        # an explicit obligation record for this effect (emitted at registration, before any compensation), or --
        # older receipts -- a later compensation record on the same effect cell: the obligation was registered
        cells = set(ri.get("write_set", []))
        registered = any(rj.get("obligation_for") in cells for rj in h)
        replaced = any(rj.get("compensation") and set(rj.get("write_set", [])) & cells for rj in h)
        if registered or replaced: continue
        for c in ri.get("read_set", []):
            v = ri["read_values"].get(c)
            if str(v) not in args: continue
            later = [rj for rj in h if c in rj.get("write_set", []) and rj["write_time"] > ri["write_time"]]
            if later and max(later, key=lambda r: r["write_time"])["write_values"].get(c) != v:
                return True
    return False


def load_paper_harness():
    for pat in ("probes/*_langgraph_live_a1.py", "python/langgraph_live_a1.py", "langgraph_live_a1.py"):
        m = glob.glob(pat)
        if m:
            spec = importlib.util.spec_from_file_location("live_a1", m[0])
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod
    raise SystemExit("langgraph_live_a1.py not found (run from the repo root)")


def bridge_selftest(binary) -> int:
    """exercise the bridge: a stale snapshot must be refused, a fresh one accepted, the trace returned."""
    vb = VerifiedBridge(binary)
    s0 = vb.begin(0, []); ok, t = vb.commit(s0, [("trip/state/date", "2026-06-14")]); assert ok and t == 1, (ok, t)
    flight = vb.begin(1, ["trip/state/date"])                       # read at clock 1
    assert flight["read_time"] == 1 and flight["read_values"] == [[vb.cell("trip/state/date"), vb.val("2026-06-14")]]
    d = vb.begin(2, ["trip/state/date"]); ok, t = vb.commit(d, [("trip/state/date", "2026-06-21")]); assert ok and t == 2
    ok, t = vb.commit(flight, [("trip/bookings/booking-0", "2026-06-14")])
    assert not ok and t == 2, "a commit whose read cell was written inside its window must be refused"
    flight2 = vb.begin(1, ["trip/state/date"]); ok, t = vb.commit(flight2, [("trip/bookings/booking-0", "2026-06-21")])
    assert ok and t == 3, "the regenerated commit must be accepted"
    tr = vb.trace(); assert len(tr) == 3 and tr[-1]["write_time"] == 3, tr
    vb.close(); print("bridge selftest: refused stale commit, accepted fresh one, trace of 3 records: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock"); ap.add_argument("--model", default="mock")
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible endpoint (vLLM, DeepSeek: https://api.deepseek.com)")
    ap.add_argument("--api-key-env", default=None, help="env var holding the key for --base-url (e.g. DEEPSEEK_API_KEY); default: the harness's 'EMPTY' for local servers")
    ap.add_argument("--n", type=int, default=100); ap.add_argument("--seed", type=int, default=20261012)
    ap.add_argument("--p-revise", type=float, default=0.5)
    ap.add_argument("--offsets", default="0,150,500,1500", help="date-agent start offsets, ms, comma-separated")
    ap.add_argument("--modes", default="vanilla,validated,sequential,ledger")
    ap.add_argument("--l1-server", default="crates/runtime/target/release/examples/l1_server",
                    help="verified L1 store binary for --modes verified (cargo build --release --example l1_server)")
    ap.add_argument("--out", default="results/live_a1_outcome/out.json")
    ap.add_argument("--mock-latency", type=float, default=None, help="mock provider only: the flight agent's generation latency (s)")
    ap.add_argument("--bridge-selftest", action="store_true", help="test VerifiedBridge against --l1-server (or the protocol mock) and exit")
    ap.add_argument("--interleave", action="store_true", help="run every arm of a session back to back in a seeded random order (removes the block-order confound)")
    ap.add_argument("--runs", type=int, default=1, help="repeat the protocol this many times with seed, seed+1, ... (one receipt per run)")
    a = ap.parse_args()
    if a.bridge_selftest:
        binary = a.l1_server if os.path.exists(a.l1_server) else os.path.join(os.path.dirname(__file__), "303_l1_server_mock.py")
        return bridge_selftest(binary)
    H = load_paper_harness()
    from langgraph.graph import StateGraph, START, END   # same framework version as the paper's cell

    client = H.ModelClient(a.provider, a.model, base_url=a.base_url) if a.base_url else H.ModelClient(a.provider, a.model)
    if a.mock_latency is not None: client.mock_latency = a.mock_latency
    if a.base_url and a.api_key_env:                       # a hosted OpenAI-compatible API (DeepSeek) needs a real key
        from openai import OpenAI
        key = os.environ.get(a.api_key_env)
        if not key: raise SystemExit(f"{a.api_key_env} is not set")
        client.client = OpenAI(base_url=a.base_url, api_key=key)
    from pathlib import Path
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # one records file per run (per model), next to the receipt -- never shared between models;
    # `rec` is rebound per run below (the node closures read it from this scope)
    rec = None
    TRIP_NS, BOOK_NS, DATE_CELL, NULL = H.TRIP_NS, H.BOOK_NS, H.DATE_CELL, H.NULL

    def build(store, ev, mode, offset_ms, revise, ledger=None, vb=None):
        date_started, flight_read_done, flight_committed = ev
        FLIGHT, DATE = 1, 2                                  # agent ids in the verified store

        uses_vstore = mode in ("verified", "ledger_verified")
        uses_ledger = mode in ("ledger", "ledger_verified")
        wall0 = time.perf_counter()
        def ms(w): return round((w - wall0) * 1000.0, 2)

        def flight_node(state, runtime):
            s = runtime.store; regenerations = 0
            while True:
                if hasattr(s, "reads_reset"): s.reads_reset()
                if uses_vstore:
                    with vb.lock:                            # LangGraph get + verified begin, atomically
                        item = s.get(TRIP_NS, "date"); _, _, w_read = s.last_stamp()
                        snap = vb.begin(FLIGHT, [DATE_CELL]); t_read = snap["read_time"]
                else:
                    item = s.get(TRIP_NS, "date"); _, t_read, w_read = s.last_stamp()
                seen = item.value["date"] if item else NULL
                flight_read_done.set()
                text = client.complete("You are a flight-booking agent. Draft a ONE-sentence flight reservation request. "
                                       "Include the trip date verbatim in ISO format (YYYY-MM-DD).",
                                       f"Trip date: {seen}. Route: LHR to ISB, economy, one passenger.",
                                       mock_reply=f"Please reserve one economy seat LHR-ISB for {seen}.")
                if mode in ("validated", "ledger"):      # application-layer L1 (re-read before put)
                    chk = s.get(TRIP_NS, "date"); _, t_chk, _ = s.last_stamp()
                    cur = chk.value["date"] if chk else NULL
                    if cur != seen:
                        regenerations += 1; continue
                    t_read = t_chk
                key = f"booking-{state['session']}"
                if uses_vstore:
                    with vb.lock:                            # verified commit decides; the LangGraph put follows only if accepted
                        ok, t_write = vb.commit(snap, [(f"trip/bookings/{key}", seen)])
                        if ok:
                            s.put(BOOK_NS, key, {"date_used": seen, "text": text}); _, _, w_write = s.last_stamp()
                    if not ok:
                        regenerations += 1; continue
                else:
                    s.put(BOOK_NS, key, {"date_used": seen, "text": text}); _, t_write, w_write = s.last_stamp()
                rec.emit(agent="flight_agent", read_set=[DATE_CELL], read_values={DATE_CELL: seen}, read_time=t_read,
                         write_set=[f"trip/bookings/{key}"], write_values={f"trip/bookings/{key}": seen},
                         write_time=t_write, experiment="store-outcome", mode=mode, session=state["session"],
                         regenerations=regenerations, offset_ms=offset_ms, revise=revise,
                         pinned_seconds=round(w_write - w_read, 4), booking_text=text,
                         wall_read_ms=ms(w_read), wall_commit_ms=ms(w_write),
                         observed_read_set=(s.reads_snapshot() if hasattr(s, "reads_snapshot") else None),
                         verified_decision=uses_vstore)
                if uses_ledger and ledger is not None:
                    def compensate(new_date, _key=key, _session=state["session"]):
                        # rebook with the superseding value: one more generation, basis updated
                        text2 = client.complete("You are a flight-booking agent. Draft a ONE-sentence flight reservation "
                                                "request. Include the trip date verbatim in ISO format (YYYY-MM-DD).",
                                                f"Trip date: {new_date}. Route: LHR to ISB, economy, one passenger. "
                                                f"This REPLACES an earlier reservation.",
                                                mock_reply=f"Please reserve one economy seat LHR-ISB for {new_date} (replaces earlier).")
                        s.put(BOOK_NS, _key, {"date_used": new_date, "text": text2}); _, t_w2, w_w2 = s.last_stamp()
                        rec.emit(agent="compensator", read_set=[DATE_CELL], read_values={DATE_CELL: new_date},
                                 read_time=t_w2 - 1 if t_w2 > 0 else 0, write_set=[f"trip/bookings/{_key}"],
                                 write_values={f"trip/bookings/{_key}": new_date}, write_time=t_w2,
                                 experiment="store-outcome", mode=mode, session=_session, compensation=True,
                                 offset_ms=offset_ms, booking_text=text2, wall_commit_ms=ms(w_w2))
                    ledger.register(key, {DATE_CELL: seen}, compensate)
                    # close the put->register gap: a revision that landed in between is superseding now
                    cur_item = s.get(TRIP_NS, "date"); cur = cur_item.value["date"] if cur_item else NULL
                    if cur != seen:
                        ledger.superseded(DATE_CELL, cur)
                flight_committed.set()
                return {"booking_text": text, "date_used": seen, "regenerations": regenerations}

        def date_node(state, runtime):
            s = runtime.store
            if mode == "sequential": flight_committed.wait()
            else:
                flight_read_done.wait(); time.sleep(offset_ms / 1000.0)
            date_started.set()
            if not revise:                       # the session in which nobody changes the date
                return {"new_date": None, "fallback": False}
            if uses_vstore:
                with vb.lock:
                    item = s.get(TRIP_NS, "date"); _, _, w_dread = s.last_stamp()
                    dsnap = vb.begin(DATE, [DATE_CELL]); t_read = dsnap["read_time"]
            else:
                item = s.get(TRIP_NS, "date"); _, t_read, w_dread = s.last_stamp()
            old = item.value["date"] if item else NULL
            fb = (date.fromisoformat(old) + timedelta(days=7)).isoformat() if old != NULL else "2026-06-21"
            reply = client.complete("You are the user's assistant. The user wants to move the trip one week later. "
                                    "Reply with the new date only, ISO format YYYY-MM-DD.",
                                    f"Current trip date: {old}.", max_tokens=16, mock_reply=fb, mock_latency=0.05)
            new = H.parse_iso(reply); fallback = new is None or new == old
            if fallback: new = fb
            if uses_vstore:
                with vb.lock:                                # verified commit + LangGraph put, atomically
                    ok, t_write = vb.commit(dsnap, [(DATE_CELL, new)])
                    if not ok:                               # nobody else writes the date; a refusal here is a harness bug
                        raise RuntimeError("verified store refused the date agent's commit")
                    s.put(TRIP_NS, "date", {"date": new}); _, _, w_dwrite = s.last_stamp()
            else:
                s.put(TRIP_NS, "date", {"date": new}); _, t_write, w_dwrite = s.last_stamp()
            rec.emit(agent="date_agent", read_set=[DATE_CELL], read_values={DATE_CELL: old}, read_time=t_read,
                     write_set=[DATE_CELL], write_values={DATE_CELL: new}, write_time=t_write,
                     experiment="store-outcome", mode=mode, session=state["session"], offset_ms=offset_ms,
                     model_fallback=fallback, wall_read_ms=ms(w_dread), wall_commit_ms=ms(w_dwrite))
            return {"new_date": new, "fallback": fallback}

        ga = StateGraph(H.FlightState); ga.add_node("book", flight_node); ga.add_edge(START, "book"); ga.add_edge("book", END)
        gb = StateGraph(H.DateState);   gb.add_node("update", date_node); gb.add_edge(START, "update"); gb.add_edge("update", END)
        return ga.compile(store=store), gb.compile(store=store)

    offsets = [int(x) for x in a.offsets.split(",")]
    modes = a.modes.split(",")
    from pathlib import Path as _P

    def run_session(mode, off, k, revise, run_rec):
        """one session of one arm; returns the per-session receipt entry"""
        clock = H.Clock(); first = len(run_rec.records)
        def on_register(key, cell, new_value, _k=k, _mode=mode, _off=off, t=None):
            run_rec.emit(agent="ledger", read_set=[], read_values={}, read_time=0, write_set=[], write_values={},
                         write_time=(t if t is not None else clock.now()), experiment="store-outcome", mode=_mode, session=_k, offset_ms=_off,
                         obligation_for=f"trip/bookings/{key}", superseded_cell=cell, superseding_value=new_value)
        ledger = BasisLedger(on_register) if mode in ("ledger", "ledger_verified") else None
        store = observed_store(H, clock, ledger)
        vb = VerifiedBridge(a.l1_server) if mode in ("verified", "ledger_verified") else None   # one verified store per session
        if vb is not None:
            snap0 = vb.begin(0, []); ok0, t_seed = vb.commit(snap0, [(DATE_CELL, "2026-06-14")]); assert ok0
            store.put(TRIP_NS, "date", {"date": "2026-06-14"})
        else:
            store.put(TRIP_NS, "date", {"date": "2026-06-14"}); _, t_seed, _ = store.last_stamp()
        run_rec.emit(agent="seed", read_set=[], read_values={}, read_time=0, write_set=[DATE_CELL],
                     write_values={DATE_CELL: "2026-06-14"}, write_time=t_seed, experiment="store-outcome",
                     mode=mode, session=k, offset_ms=off, seed=True)   # every record of a run carries its offset
        ev = [threading.Event() for _ in range(3)]
        ga, gb = build(store, ev, mode, off, revise, ledger, vb)
        out: dict[str, Any] = {}
        errors: list[BaseException] = []
        def guarded(fn):
            # a thread that dies sets every event so that its peer returns; the run stops with the error (no hang)
            def go():
                try:
                    fn()
                except BaseException as ex:  # noqa: BLE001
                    errors.append(ex)
                    for e in ev:
                        e.set()
            return go
        ta = threading.Thread(target=guarded(lambda: out.__setitem__("a", ga.invoke({"session": k, "mode": mode}))))
        tb = threading.Thread(target=guarded(lambda: out.__setitem__("b", gb.invoke({"session": k}))))
        ta.start(); tb.start(); ta.join(); tb.join()
        if errors or "a" not in out or "b" not in out:
            if vb is not None: vb.close()
            raise SystemExit(f"session {k} ({mode}): agent thread failed: {errors[0]!r}" if errors else
                             f"session {k} ({mode}): an agent thread returned nothing")
        h = run_rec.records[first:]
        wit = H.a1_witnesses(h)
        final = store.get(TRIP_NS, "date").value["date"]
        booking = store.get(BOOK_NS, f"booking-{k}").value
        vtrace = vb.trace() if vb is not None else None
        if vb is not None: vb.close()
        # where the revision landed relative to the flight agent's (final) commit, in wall-clock ms
        fl = [r for r in h if r.get("agent") == "flight_agent" and not r.get("compensation")]
        da = [r for r in h if r.get("agent") == "date_agent"]
        lag = round(da[-1]["wall_commit_ms"] - fl[-1]["wall_commit_ms"], 2) if fl and da else None
        return {"session": k, "revise": revise, "a1": bool(wit),
                "a7": a7_fires(h), "verified_trace": vtrace,
                "booking_matches_final": booking["date_used"] == final,
                "regenerations": out["a"].get("regenerations", 0),
                "obligations_registered": ledger.registered if ledger else 0,
                "obligations_discharged": ledger.discharged if ledger else 0,
                "compensation_generations": ledger.discharged if ledger else 0,
                "revision_lag_ms": lag, "pinned_seconds": fl[-1].get("pinned_seconds") if fl else None}

    def summarize(mode, off, sessions):
        n = len(sessions); rev = [s for s in sessions if s["revise"]]
        a1 = sum(s["a1"] for s in sessions); wrong = sum(not s["booking_matches_final"] for s in sessions)
        wrong_rev = sum(not s["booking_matches_final"] for s in rev)
        n7 = sum(s["a7"] for s in sessions); obl = sum(s["obligations_registered"] for s in sessions)
        lags = sorted(s["revision_lag_ms"] for s in rev if s.get("revision_lag_ms") is not None)
        cell = {"mode": mode, "offset_ms": off, "n": n, "revised": len(rev), "a1": a1, "a1_ci": list(H.clopper_pearson(a1, n)),
                "a7": n7, "obligations_registered": obl, "obligations_discharged": sum(s["obligations_discharged"] for s in sessions),
                "compensation_generations": sum(s["compensation_generations"] for s in sessions),
                "booking_wrong": wrong, "booking_wrong_ci": list(H.clopper_pearson(wrong, n)),
                "booking_wrong_given_revised": wrong_rev, "regenerations": sum(s["regenerations"] for s in sessions),
                "revision_lag_ms": {"n": len(lags), "min": lags[0] if lags else None, "median": lags[len(lags) // 2] if lags else None,
                                    "max": lags[-1] if lags else None, "after_commit": sum(1 for x in lags if x > 0)},
                "sessions": sessions}
        print(f"{mode:16s} offset={off:5d}ms  n={n:3d} revised={len(rev):3d}  A1={a1:3d}  R={n7:3d}  booking!=final={wrong:3d} "
              f"(of revised {wrong_rev:3d})  regen={cell['regenerations']}  lag>0 in {cell['revision_lag_ms']['after_commit']}/{len(lags)}")
        return cell

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    for r in range(a.runs):
        seed = a.seed + r
        out_r = a.out if a.runs == 1 else str(_P(a.out).with_suffix(f".run{r}.json"))
        rec = H.Recorder(_P(out_r).with_suffix(".records.jsonl"))   # rebinds the closures' recorder
        run_rec = rec
        rng = random.Random(seed)
        result: dict[str, Any] = {"provider": a.provider, "model": a.model, "n": a.n, "p_revise": a.p_revise,
                                  "seed": seed, "run": r, "interleaved": bool(a.interleave), "cells": []}
        revise_of = [rng.random() < a.p_revise for _ in range(a.n)]     # one draw per session, shared by every arm
        cells_sessions: dict[tuple[str, int], list] = {(m, o): [] for m in modes for o in offsets if not (m == "sequential" and o != offsets[0])}
        if a.interleave:
            order_lines = []
            for k in range(a.n):
                arms = [key for key in cells_sessions]
                random.Random(seed * 1_000_003 + k).shuffle(arms)        # seeded per-session arm order
                for (m, o) in arms:
                    cells_sessions[(m, o)].append(run_session(m, o, k, revise_of[k], run_rec))
                    order_lines.append(f"{k}\t{m}\t{o}\t{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
            with open(_P(out_r).with_suffix(".order.tsv"), "w") as f:
                f.write("\n".join(order_lines) + "\n")                  # the receipt that the interleaving happened
        else:
            for (m, o) in cells_sessions:
                for k in range(a.n):
                    cells_sessions[(m, o)].append(run_session(m, o, k, revise_of[k], run_rec))
        for (m, o), sessions in cells_sessions.items():
            result["cells"].append(summarize(m, o, sessions))
        json.dump(result, open(out_r, "w"), indent=1)
        rec.close()
        print("wrote", out_r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
