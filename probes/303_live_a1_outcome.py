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
"""
from __future__ import annotations
import argparse, glob, importlib.util, json, os, random, statistics, sys, threading, time
from datetime import date, timedelta
from typing import Any



class BasisLedger:
    """L5 at the store: effects register (key, basis, compensator); a put that
    supersedes a basis value registers an obligation and runs the compensator."""
    def __init__(self):
        self.effects = {}      # key -> {"basis": {cell: value}, "compensate": fn, "obligation": bool, "discharged": bool}
        self.lock = threading.Lock()
        self.registered = 0; self.discharged = 0

    def register(self, key, basis, compensate):
        with self.lock:
            self.effects[key] = {"basis": dict(basis), "compensate": compensate, "obligation": False, "discharged": False}

    def superseded(self, cell, new_value):
        """called by the store after a put to `cell`: register + discharge obligations"""
        todo = []
        with self.lock:
            for key, e in self.effects.items():
                if cell in e["basis"] and e["basis"][cell] != new_value and not e["obligation"]:
                    e["obligation"] = True; self.registered += 1; todo.append((key, e))
        for key, e in todo:               # discharge outside the lock: the compensator may put
            e["compensate"](new_value)
            with self.lock:
                e["discharged"] = True; self.discharged += 1
                e["basis"][cell] = new_value   # the compensated effect's basis is now current ...
                e["obligation"] = False        # ... and it is a fresh effect: a further revision owes a further obligation
                                               # (the per-record flag in Guarded5.tla stays set; the replacement booking is
                                               # its own record with its own flag -- this workload revises once, so the
                                               # path is not exercised by Table 3)


def ledgered_store(H, clock, ledger):
    """subclass the paper's InstrumentedStore so that put() notifies the ledger"""
    class LedgeredStore(H.InstrumentedStore):
        def put(self, namespace, key, value, *args, **kwargs):
            old = self.get(namespace, key)
            r = super().put(namespace, key, value, *args, **kwargs)
            saved = self.local.last          # the caller's own put stamp: the compensator
            cell = "/".join(namespace) + "/" + key   # runs in this thread and must not clobber it
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
        # an effect later replaced by a compensation record is discharged: its obligation was registered
        replaced = any(rj.get("compensation") and set(rj.get("write_set", [])) & set(ri.get("write_set", [])) for rj in h)
        if replaced: continue
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
    ap.add_argument("--bridge-selftest", action="store_true", help="test VerifiedBridge against --l1-server (or the protocol mock) and exit")
    a = ap.parse_args()
    if a.bridge_selftest:
        binary = a.l1_server if os.path.exists(a.l1_server) else os.path.join(os.path.dirname(__file__), "303_l1_server_mock.py")
        return bridge_selftest(binary)
    H = load_paper_harness()
    from langgraph.graph import StateGraph, START, END   # same framework version as the paper's cell

    client = H.ModelClient(a.provider, a.model, base_url=a.base_url) if a.base_url else H.ModelClient(a.provider, a.model)
    if a.base_url and a.api_key_env:                       # a hosted OpenAI-compatible API (DeepSeek) needs a real key
        from openai import OpenAI
        key = os.environ.get(a.api_key_env)
        if not key: raise SystemExit(f"{a.api_key_env} is not set")
        client.client = OpenAI(base_url=a.base_url, api_key=key)
    from pathlib import Path
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # one records file per run (per model), next to the receipt -- never shared between models
    rec = H.Recorder(out_path.with_suffix(".records.jsonl"))
    rng = random.Random(a.seed)
    TRIP_NS, BOOK_NS, DATE_CELL, NULL = H.TRIP_NS, H.BOOK_NS, H.DATE_CELL, H.NULL

    def build(store, ev, mode, offset_ms, revise, ledger=None, vb=None):
        date_started, flight_read_done, flight_committed = ev
        FLIGHT, DATE = 1, 2                                  # agent ids in the verified store

        def flight_node(state, runtime):
            s = runtime.store; regenerations = 0
            while True:
                if mode == "verified":
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
                if mode in ("validated", "ledger"):
                    chk = s.get(TRIP_NS, "date"); _, t_chk, _ = s.last_stamp()
                    cur = chk.value["date"] if chk else NULL
                    if cur != seen:
                        regenerations += 1; continue
                    t_read = t_chk
                key = f"booking-{state['session']}"
                if mode == "verified":
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
                         verified_decision=(mode == "verified"))
                if mode == "ledger" and ledger is not None:
                    def compensate(new_date, _key=key, _session=state["session"]):
                        # rebook with the superseding value: one more generation, basis updated
                        text2 = client.complete("You are a flight-booking agent. Draft a ONE-sentence flight reservation "
                                                "request. Include the trip date verbatim in ISO format (YYYY-MM-DD).",
                                                f"Trip date: {new_date}. Route: LHR to ISB, economy, one passenger. "
                                                f"This REPLACES an earlier reservation.",
                                                mock_reply=f"Please reserve one economy seat LHR-ISB for {new_date} (replaces earlier).")
                        s.put(BOOK_NS, _key, {"date_used": new_date, "text": text2}); _, t_w2, _ = s.last_stamp()
                        rec.emit(agent="compensator", read_set=[DATE_CELL], read_values={DATE_CELL: new_date},
                                 read_time=t_w2 - 1 if t_w2 > 0 else 0, write_set=[f"trip/bookings/{_key}"],
                                 write_values={f"trip/bookings/{_key}": new_date}, write_time=t_w2,
                                 experiment="store-outcome", mode=mode, session=_session, compensation=True,
                                 offset_ms=offset_ms, booking_text=text2)
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
            if mode == "verified":
                with vb.lock:
                    item = s.get(TRIP_NS, "date"); dsnap = vb.begin(DATE, [DATE_CELL]); t_read = dsnap["read_time"]
            else:
                item = s.get(TRIP_NS, "date"); _, t_read, _ = s.last_stamp()
            old = item.value["date"] if item else NULL
            fb = (date.fromisoformat(old) + timedelta(days=7)).isoformat() if old != NULL else "2026-06-21"
            reply = client.complete("You are the user's assistant. The user wants to move the trip one week later. "
                                    "Reply with the new date only, ISO format YYYY-MM-DD.",
                                    f"Current trip date: {old}.", max_tokens=16, mock_reply=fb, mock_latency=0.05)
            new = H.parse_iso(reply); fallback = new is None or new == old
            if fallback: new = fb
            if mode == "verified":
                with vb.lock:                                # verified commit + LangGraph put, atomically
                    ok, t_write = vb.commit(dsnap, [(DATE_CELL, new)])
                    if not ok:                               # nobody else writes the date; a refusal here is a harness bug
                        raise RuntimeError("verified store refused the date agent's commit")
                    s.put(TRIP_NS, "date", {"date": new})
            else:
                s.put(TRIP_NS, "date", {"date": new}); _, t_write, _ = s.last_stamp()
            rec.emit(agent="date_agent", read_set=[DATE_CELL], read_values={DATE_CELL: old}, read_time=t_read,
                     write_set=[DATE_CELL], write_values={DATE_CELL: new}, write_time=t_write,
                     experiment="store-outcome", mode=mode, session=state["session"], offset_ms=offset_ms,
                     model_fallback=fallback)
            return {"new_date": new, "fallback": fallback}

        ga = StateGraph(H.FlightState); ga.add_node("book", flight_node); ga.add_edge(START, "book"); ga.add_edge("book", END)
        gb = StateGraph(H.DateState);   gb.add_node("update", date_node); gb.add_edge(START, "update"); gb.add_edge("update", END)
        return ga.compile(store=store), gb.compile(store=store)

    offsets = [int(x) for x in a.offsets.split(",")]
    modes = a.modes.split(",")
    result: dict[str, Any] = {"provider": a.provider, "model": a.model, "n": a.n, "p_revise": a.p_revise,
                              "seed": a.seed, "cells": []}
    for mode in modes:
        for off in offsets:
            if mode == "sequential" and off != offsets[0]: continue
            sessions = []
            for k in range(a.n):
                revise = rng.random() < a.p_revise
                clock = H.Clock(); first = len(rec.records)
                ledger = BasisLedger() if mode == "ledger" else None
                store = ledgered_store(H, clock, ledger) if ledger else H.InstrumentedStore(clock)
                vb = VerifiedBridge(a.l1_server) if mode == "verified" else None   # one verified store per session
                if vb is not None:
                    snap0 = vb.begin(0, []); ok0, t_seed = vb.commit(snap0, [(DATE_CELL, "2026-06-14")]); assert ok0
                    store.put(TRIP_NS, "date", {"date": "2026-06-14"})
                else:
                    store.put(TRIP_NS, "date", {"date": "2026-06-14"}); _, t_seed, _ = store.last_stamp()
                rec.emit(agent="seed", read_set=[], read_values={}, read_time=0, write_set=[DATE_CELL],
                         write_values={DATE_CELL: "2026-06-14"}, write_time=t_seed, experiment="store-outcome",
                         mode=mode, session=k, offset_ms=off, seed=True)   # every record of a run carries its offset
                ev = [threading.Event() for _ in range(3)]
                ga, gb = build(store, ev, mode, off, revise, ledger, vb)
                out: dict[str, Any] = {}
                ta = threading.Thread(target=lambda: out.__setitem__("a", ga.invoke({"session": k, "mode": mode})))
                tb = threading.Thread(target=lambda: out.__setitem__("b", gb.invoke({"session": k})))
                ta.start(); tb.start(); ta.join(); tb.join()
                h = rec.records[first:]
                wit = H.a1_witnesses(h)
                final = store.get(TRIP_NS, "date").value["date"]
                booking = store.get(BOOK_NS, f"booking-{k}").value
                vtrace = vb.trace() if vb is not None else None
                if vb is not None: vb.close()
                sessions.append({"session": k, "revise": revise, "a1": bool(wit),
                                 "a7": a7_fires(h), "verified_trace": vtrace,
                                 "booking_matches_final": booking["date_used"] == final,
                                 "regenerations": out["a"].get("regenerations", 0),
                                 "obligations_registered": ledger.registered if ledger else 0,
                                 "obligations_discharged": ledger.discharged if ledger else 0,
                                 "compensation_generations": ledger.discharged if ledger else 0})
            n = len(sessions); rev = [s for s in sessions if s["revise"]]
            a1 = sum(s["a1"] for s in sessions); wrong = sum(not s["booking_matches_final"] for s in sessions)
            wrong_rev = sum(not s["booking_matches_final"] for s in rev)
            n7 = sum(s["a7"] for s in sessions); obl = sum(s["obligations_registered"] for s in sessions)
            cell = {"mode": mode, "offset_ms": off, "n": n, "revised": len(rev), "a1": a1, "a1_ci": list(H.clopper_pearson(a1, n)),
                    "a7": n7, "obligations_registered": obl, "obligations_discharged": sum(s["obligations_discharged"] for s in sessions),
                    "compensation_generations": sum(s["compensation_generations"] for s in sessions),
                    "booking_wrong": wrong, "booking_wrong_ci": list(H.clopper_pearson(wrong, n)),
                    "booking_wrong_given_revised": wrong_rev, "regenerations": sum(s["regenerations"] for s in sessions),
                    "sessions": sessions}
            result["cells"].append(cell)
            print(f"{mode:10s} offset={off:5d}ms  n={n:3d} revised={len(rev):3d}  A1={a1:3d}  booking!=final={wrong:3d} "
                  f"(of revised {wrong_rev:3d})  regen={cell['regenerations']}")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=1); rec.close()
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
