#!/usr/bin/env python3
"""304_ledger_world.py -- what the basis ledger buys in a WORLD, not in a store.

The ledger arm of probe 303 (main paper Table 3) scores "booking != final" on the
final STORE state: the compensator overwrites the booking cell, nothing reads the
first booking between its release and the compensation, the compensator cannot
fail, and the workload revises once.  A reviewer is right that this measures
"the compensator ran".  This probe keeps the same two agents, the same L1
discipline at the application layer and the same basis ledger, and adds the
three things the store cannot show:

  * an external WORLD (the airline): `book(date)` returns a confirmation and an
    active booking that stays active until `cancel(conf)`; the harm is counted
    in the world at the end of the session -- active bookings whose date is not
    the final trip date (stale bookings the compensation did not withdraw), and
    sessions with two active bookings (double bookings);
  * a CONSUMER: a downstream reader that, a random delay after the first
    booking is released, reads the active bookings from the world and acts on
    them (sends the itinerary).  `consumer_saw_stale` counts the sessions in
    which what it acted on is not the final date -- the consumption race the
    ledger cannot close, measured rather than argued;
  * a FALLIBLE compensator and a second revision: `--p-cancel-fail` and
    `--p-rebook-fail` make the world refuse a cancellation or a rebooking with
    the stated probability (the obligation then stays registered and
    undischarged, which the receipt counts), and `--revisions 2` revises the
    date twice, exercising the ledger's re-arm path, which Table 3's workload
    never reaches.

Arms (--modes): validated (L1, no ledger: the baseline harm in the world),
ledger (L1 + ledger + compensator that cancels the stale booking in the world
and books the new date), and ledger_norollback (the compensator books the new
date WITHOUT cancelling the old one -- the behaviour of probe 303's compensator,
seen from the world).

Compensator (--compensator):
  latest  the compensator of the first run (2026-10-14, receipts archived under
          results/ledger_world_v1_latest_conf/): it tracked ONE confirmation per
          effect, and generated the replacement text BETWEEN the cancellation and
          the rebooking.  Two consequences the world check caught: after a failed
          cancellation a retry cancelled the latest confirmation only, so the
          original booking stayed active while the ledger reported the obligation
          discharged; and the cancel-to-rebook window contained a model call, so a
          consumer reading in it saw no booking at all.  Kept so that the first
          run's receipts stay reproducible.
  all     (default) the compensator generates the replacement first, then cancels
          EVERY active confirmation the effect created, then rebooks; the
          obligation is discharged only if every cancellation and the rebooking
          succeeded, and a retry re-attempts every still-active stale confirmation.

    uv run --project envs/langgraph-1.2.0 python probes/304_ledger_world.py \\
        --provider anthropic --model claude-haiku-4-5 --n 100 --offset-ms 150 \\
        --modes validated,ledger,ledger_norollback --revisions 2 \\
        --p-cancel-fail 0.1 --p-rebook-fail 0.1 --consumer-max-ms 1500 \\
        --out results/ledger_world/claude-haiku-4-5.json

    python3 probes/304_ledger_world.py --provider mock --n 5   # mock model (langgraph still needed)

Receipt: per cell n, revised, a1, a7 (R on the records), world_wrong, double_booked,
consumer_saw_stale, obligations registered / discharged / failed, regenerations,
compensation generations, and per-session detail (lags, what the consumer saw).
"""
from __future__ import annotations
import argparse, glob, importlib.util, json, os, random, sys, threading, time
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def load_probe_303():
    here = os.path.dirname(os.path.abspath(__file__))
    for pat in (os.path.join(here, "303_live_a1_outcome.py"),):
        if os.path.exists(pat):
            spec = importlib.util.spec_from_file_location("probe303", pat)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod
    raise SystemExit("303_live_a1_outcome.py not found beside this probe")


class FallibleLedger:
    """probe 303's BasisLedger with one difference: a compensator that raises leaves the obligation
    REGISTERED AND UNDISCHARGED instead of propagating into the superseding writer's thread."""
    def __init__(self, base_cls, on_register=None):
        self.effects = {}; self.lock = threading.Lock(); self.registered = 0; self.discharged = 0; self.failed = 0; self.retries = 0
        self._base = base_cls; self.on_register = on_register

    def register(self, key, basis, compensate):
        with self.lock:
            self.effects[key] = {"basis": dict(basis), "compensate": compensate, "obligation": False, "discharged": False}

    def superseded(self, cell, new_value):
        todo = []
        with self.lock:
            for key, e in self.effects.items():
                if cell in e["basis"] and e["basis"][cell] != new_value:
                    if not e["obligation"]:
                        e["obligation"] = True; self.registered += 1
                    else:
                        self.retries += 1            # an OPEN obligation (earlier compensation failed) is retried
                    todo.append((key, e))
        for key, e in todo:
            if self.on_register is not None:          # the registration record, before any compensation attempt
                self.on_register(key, cell, new_value)
            try:
                e["compensate"](new_value)
            except Exception as ex:  # noqa: BLE001  -- the world refused: the obligation stays open
                self.failed += 1
                with self.lock:
                    e["discharged"] = False; e["error"] = str(ex)
                continue
            with self.lock:
                e["discharged"] = True; self.discharged += 1
                e["basis"][cell] = new_value       # re-arm: the replacement is a fresh effect with a current basis
                e["obligation"] = False


class World:
    """the airline: bookings are irreversible effects; a cancellation is a second effect that may fail"""
    def __init__(self, rng: random.Random, p_cancel_fail: float, p_rebook_fail: float):
        self.rng = rng; self.p_cancel_fail = p_cancel_fail; self.p_rebook_fail = p_rebook_fail
        self.lock = threading.Lock(); self.bookings: dict[int, dict] = {}; self.next = 1
        self.log: list[dict] = []

    def book(self, session: int, dt: str, kind: str = "booking") -> int | None:
        with self.lock:
            if kind == "rebooking" and self.rng.random() < self.p_rebook_fail:
                self.log.append({"op": "book", "session": session, "date": dt, "kind": kind, "ok": False}); return None
            conf = self.next; self.next += 1
            self.bookings[conf] = {"session": session, "date": dt, "active": True, "kind": kind, "t": time.perf_counter()}
            self.log.append({"op": "book", "session": session, "date": dt, "kind": kind, "ok": True, "conf": conf}); return conf

    def cancel(self, conf: int) -> bool:
        with self.lock:
            b = self.bookings.get(conf)
            if b is None or not b["active"]:
                return False
            if self.rng.random() < self.p_cancel_fail:
                self.log.append({"op": "cancel", "conf": conf, "ok": False}); return False
            b["active"] = False; self.log.append({"op": "cancel", "conf": conf, "ok": True}); return True

    def active(self, session: int) -> list[dict]:
        with self.lock:
            return [dict(b, conf=c) for c, b in self.bookings.items() if b["session"] == session and b["active"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock"); ap.add_argument("--model", default="mock")
    ap.add_argument("--base-url", default=None); ap.add_argument("--api-key-env", default=None)
    ap.add_argument("--n", type=int, default=100); ap.add_argument("--seed", type=int, default=20261014)
    ap.add_argument("--p-revise", type=float, default=1.0)
    ap.add_argument("--offset-ms", type=int, default=150, help="date agent start offset after the flight agent's read")
    ap.add_argument("--revisions", type=int, default=2, help="revisions per revising session (the second lands --second-gap-ms after the first)")
    ap.add_argument("--second-gap-ms", type=int, default=800)
    ap.add_argument("--modes", default="validated,ledger,ledger_norollback")
    ap.add_argument("--p-cancel-fail", type=float, default=0.1); ap.add_argument("--p-rebook-fail", type=float, default=0.1)
    ap.add_argument("--consumer-max-ms", type=int, default=1500, help="the consumer reads the world a uniform(0, this) ms after the first release")
    ap.add_argument("--compensator", choices=("latest", "all"), default="all",
                    help="latest: the first run's compensator (one tracked confirmation, model call between cancel and rebook); all: cancel every active stale confirmation, replacement generated first (default)")
    ap.add_argument("--interleave", action="store_true", default=True)
    ap.add_argument("--out", default="results/ledger_world/out.json")
    ap.add_argument("--mock-latency", type=float, default=None, help="mock provider only: the flight agent's generation latency (s)")
    a = ap.parse_args()
    P = load_probe_303(); H = P.load_paper_harness()
    from langgraph.graph import StateGraph, START, END

    client = H.ModelClient(a.provider, a.model, base_url=a.base_url) if a.base_url else H.ModelClient(a.provider, a.model)
    if a.mock_latency is not None: client.mock_latency = a.mock_latency
    if a.base_url and a.api_key_env:
        from openai import OpenAI
        key = os.environ.get(a.api_key_env)
        if not key: raise SystemExit(f"{a.api_key_env} is not set")
        client.client = OpenAI(base_url=a.base_url, api_key=key)
    out_path = Path(a.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    rec = H.Recorder(out_path.with_suffix(".records.jsonl"))
    TRIP_NS, BOOK_NS, DATE_CELL, NULL = H.TRIP_NS, H.BOOK_NS, H.DATE_CELL, H.NULL
    modes = a.modes.split(",")

    def build(store, ev, mode, k, revise, ledger, world, srng, consumer_state):
        flight_read_done, flight_committed, first_release = ev
        uses_ledger = mode in ("ledger", "ledger_norollback")
        wall0 = time.perf_counter()
        def ms(w): return round((w - wall0) * 1000.0, 2)
        confs: dict[str, int | None] = {}        # booking key -> latest confirmation in the world (--compensator latest)
        confs_all: dict[str, set[int]] = {}      # booking key -> every active confirmation the effect created (--compensator all)

        def flight_node(state, runtime):
            s = runtime.store; regenerations = 0
            while True:
                if hasattr(s, "reads_reset"): s.reads_reset()
                item = s.get(TRIP_NS, "date"); _, t_read, w_read = s.last_stamp()
                seen = item.value["date"] if item else NULL
                flight_read_done.set()
                text = client.complete("You are a flight-booking agent. Draft a ONE-sentence flight reservation request. "
                                       "Include the trip date verbatim in ISO format (YYYY-MM-DD).",
                                       f"Trip date: {seen}. Route: LHR to ISB, economy, one passenger.",
                                       mock_reply=f"Please reserve one economy seat LHR-ISB for {seen}.")
                chk = s.get(TRIP_NS, "date"); _, t_chk, _ = s.last_stamp()           # L1 at the application layer
                cur = chk.value["date"] if chk else NULL
                if cur != seen:
                    regenerations += 1; continue
                t_read = t_chk
                key = f"booking-{k}"
                conf = world.book(k, seen)                                            # the irreversible effect, released at commit
                confs[key] = conf
                confs_all[key] = {conf} if conf is not None else set()
                s.put(BOOK_NS, key, {"date_used": seen, "text": text}); _, t_write, w_write = s.last_stamp()
                rec.emit(agent="flight_agent", read_set=[DATE_CELL], read_values={DATE_CELL: seen}, read_time=t_read,
                         write_set=[f"trip/bookings/{key}"], write_values={f"trip/bookings/{key}": seen},
                         write_time=t_write, experiment="ledger-world", mode=mode, session=k, regenerations=regenerations,
                         offset_ms=a.offset_ms, revise=revise, pinned_seconds=round(w_write - w_read, 4), booking_text=text,
                         wall_read_ms=ms(w_read), wall_commit_ms=ms(w_write), world_conf=conf,
                         observed_read_set=(s.reads_snapshot() if hasattr(s, "reads_snapshot") else None))
                first_release.set()
                if uses_ledger and ledger is not None:
                    def generate_replacement(new_date):
                        return client.complete("You are a flight-booking agent. Draft a ONE-sentence flight reservation "
                                               "request. Include the trip date verbatim in ISO format (YYYY-MM-DD).",
                                               f"Trip date: {new_date}. Route: LHR to ISB, economy, one passenger. "
                                               f"This REPLACES an earlier reservation.",
                                               mock_reply=f"Please reserve one economy seat LHR-ISB for {new_date} (replaces earlier).")

                    def emit_compensation(_key, new_date, text2, new_conf, cancelled):
                        s.put(BOOK_NS, _key, {"date_used": new_date if new_conf is not None else s.get(BOOK_NS, _key).value["date_used"], "text": text2})
                        _, t_w2, w_w2 = s.last_stamp()
                        rec.emit(agent="compensator", read_set=[DATE_CELL], read_values={DATE_CELL: new_date},
                                 read_time=t_w2 - 1 if t_w2 > 0 else 0, write_set=[f"trip/bookings/{_key}"],
                                 write_values={f"trip/bookings/{_key}": new_date if new_conf is not None else "FAILED"}, write_time=t_w2,
                                 experiment="ledger-world", mode=mode, session=k, compensation=True, offset_ms=a.offset_ms,
                                 booking_text=text2, wall_commit_ms=ms(w_w2), cancel_ok=cancelled, rebook_ok=new_conf is not None,
                                 compensator=a.compensator)

                    def compensate_latest(new_date, _key=key):
                        # the first run's compensator: ONE tracked confirmation; the model call sits between cancel and rebook
                        old_conf = confs.get(_key); cancelled = None
                        if mode == "ledger":                                          # withdraw the stale effect first
                            cancelled = world.cancel(old_conf) if old_conf is not None else False
                        text2 = generate_replacement(new_date)
                        new_conf = world.book(k, new_date, kind="rebooking")
                        ok = new_conf is not None and (cancelled is not False or mode == "ledger_norollback")
                        if new_conf is not None:
                            confs[_key] = new_conf
                        emit_compensation(_key, new_date, text2, new_conf, cancelled)
                        if not ok:
                            raise RuntimeError("compensation failed")                  # the ledger keeps the obligation open

                    def compensate_all(new_date, _key=key):
                        # replacement first (no world mutation yet), then cancel EVERY active stale confirmation, then rebook
                        text2 = generate_replacement(new_date)
                        cancelled: list[bool] = []
                        if mode == "ledger":
                            for c in sorted(confs_all.get(_key, set())):
                                ok_c = world.cancel(c)
                                cancelled.append(ok_c)
                                if ok_c:
                                    confs_all[_key].discard(c)
                        new_conf = world.book(k, new_date, kind="rebooking")
                        if new_conf is not None:
                            confs[_key] = new_conf; confs_all.setdefault(_key, set()).add(new_conf)
                        all_cancelled = all(cancelled) if mode == "ledger" else True
                        ok = new_conf is not None and all_cancelled
                        emit_compensation(_key, new_date, text2, new_conf, (all(cancelled) if cancelled else None) if mode == "ledger" else None)
                        if not ok:
                            raise RuntimeError("compensation failed")                  # the ledger keeps the obligation open; a retry re-cancels every active stale confirmation

                    compensate = compensate_all if a.compensator == "all" else compensate_latest
                    ledger.register(key, {DATE_CELL: seen}, compensate)
                    cur_item = s.get(TRIP_NS, "date"); cur2 = cur_item.value["date"] if cur_item else NULL
                    if cur2 != seen:
                        ledger.superseded(DATE_CELL, cur2)
                flight_committed.set()
                return {"booking_text": text, "date_used": seen, "regenerations": regenerations}

        def date_node(state, runtime):
            s = runtime.store
            flight_read_done.wait(); time.sleep(a.offset_ms / 1000.0)
            if not revise:
                return {"new_date": None}
            for r_i in range(a.revisions):
                if r_i > 0:
                    time.sleep(a.second_gap_ms / 1000.0)
                item = s.get(TRIP_NS, "date"); _, t_read, w_dread = s.last_stamp()
                old = item.value["date"] if item else NULL
                fb = (date.fromisoformat(old) + timedelta(days=7)).isoformat() if old != NULL else "2026-06-21"
                reply = client.complete("You are the user's assistant. The user wants to move the trip one week later. "
                                        "Reply with the new date only, ISO format YYYY-MM-DD.",
                                        f"Current trip date: {old}.", max_tokens=16, mock_reply=fb, mock_latency=0.05)
                new = H.parse_iso(reply); fallback = new is None or new == old
                if fallback: new = fb
                s.put(TRIP_NS, "date", {"date": new}); _, t_write, w_dwrite = s.last_stamp()
                rec.emit(agent="date_agent", read_set=[DATE_CELL], read_values={DATE_CELL: old}, read_time=t_read,
                         write_set=[DATE_CELL], write_values={DATE_CELL: new}, write_time=t_write,
                         experiment="ledger-world", mode=mode, session=k, offset_ms=a.offset_ms, revision=r_i,
                         model_fallback=fallback, wall_read_ms=ms(w_dread), wall_commit_ms=ms(w_dwrite))
            return {"new_date": new}

        def consumer():
            """a downstream reader: reads the world once, a random delay after the first release"""
            first_release.wait()
            delay = srng.uniform(0, a.consumer_max_ms) / 1000.0
            time.sleep(delay)
            act = world.active(k)
            consumer_state.update({"delay_ms": round(delay * 1000.0, 1), "saw": sorted(b["date"] for b in act),
                                   "at_ms": ms(time.perf_counter())})

        ga = StateGraph(H.FlightState); ga.add_node("book", flight_node); ga.add_edge(START, "book"); ga.add_edge("book", END)
        gb = StateGraph(H.DateState);   gb.add_node("update", date_node); gb.add_edge(START, "update"); gb.add_edge("update", END)
        return ga.compile(store=store), gb.compile(store=store), consumer

    rng = random.Random(a.seed)
    revise_of = [rng.random() < a.p_revise for _ in range(a.n)]
    cells: dict[str, list] = {m: [] for m in modes}
    for k in range(a.n):
        arms = list(modes)
        if a.interleave:
            random.Random(a.seed * 1_000_003 + k).shuffle(arms)
        for mode in arms:
            srng = random.Random(a.seed * 7_919 + k)                     # the same world luck for every arm of a session
            world = World(srng, a.p_cancel_fail, a.p_rebook_fail)
            clock = H.Clock(); first = len(rec.records)
            def on_register(key, cell, new_value, _k=k, _mode=mode):
                rec.emit(agent="ledger", read_set=[], read_values={}, read_time=0, write_set=[], write_values={},
                         write_time=clock.now(), experiment="ledger-world", mode=_mode, session=_k, offset_ms=a.offset_ms,
                         obligation_for=f"trip/bookings/booking-{_k}", superseded_cell=cell, superseding_value=new_value)
            ledger = FallibleLedger(P.BasisLedger, on_register) if mode in ("ledger", "ledger_norollback") else None
            store = P.observed_store(H, clock, ledger)
            store.put(TRIP_NS, "date", {"date": "2026-06-14"}); _, t_seed, _ = store.last_stamp()
            rec.emit(agent="seed", read_set=[], read_values={}, read_time=0, write_set=[DATE_CELL],
                     write_values={DATE_CELL: "2026-06-14"}, write_time=t_seed, experiment="ledger-world",
                     mode=mode, session=k, offset_ms=a.offset_ms, seed=True)
            ev = [threading.Event() for _ in range(3)]; consumer_state: dict[str, Any] = {}
            ga, gb, consumer = build(store, ev, mode, k, revise_of[k], ledger, world, srng, consumer_state)
            out: dict[str, Any] = {}
            errors: list[BaseException] = []
            def guarded(fn):
                # a thread that dies (a provider error after every retry, a bug) sets every event so that the peers
                # blocked on it return, and records the error; the run then stops with it instead of hanging forever
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
            tc = threading.Thread(target=guarded(consumer))
            ta.start(); tb.start(); tc.start(); ta.join(); tb.join(); tc.join()
            if errors or "a" not in out or "b" not in out:
                rec.close()
                raise SystemExit(f"session {k} ({mode}) failed: {errors[0]!r}; the receipt {a.out} was not written -- "
                                 f"re-run this model (the runner redoes a model whose receipt is missing)" if errors else
                                 f"session {k} ({mode}): an agent thread returned nothing; receipt not written")
            # let the ledger finish any compensation that the last revision triggered (it runs in the date agent's thread)
            h = rec.records[first:]
            final = store.get(TRIP_NS, "date").value["date"]
            booking = store.get(BOOK_NS, f"booking-{k}").value
            active = world.active(k)
            world_wrong = sum(1 for b in active if b["date"] != final)
            obl_failed = 0
            if ledger is not None:
                with ledger.lock:
                    obl_failed = sum(1 for e in ledger.effects.values() if e["obligation"] and not e["discharged"])
            cells[mode].append({
                "session": k, "revise": revise_of[k], "a1": bool(H.a1_witnesses(h)), "a7": P.a7_fires(h),
                "booking_matches_final": booking["date_used"] == final, "final": final,
                "world_active": [b["date"] for b in active], "world_wrong": world_wrong, "double_booked": len(active) >= 2,
                "consumer": consumer_state, "consumer_saw_stale": bool(consumer_state.get("saw")) and consumer_state["saw"] != [final],
                "consumer_saw_none": consumer_state.get("saw") == [], "world_none": len(active) == 0,
                "obligation_retries": ledger.retries if ledger else 0,
                "regenerations": out["a"].get("regenerations", 0),
                "obligations_registered": ledger.registered if ledger else 0,
                "obligations_discharged": ledger.discharged if ledger else 0, "obligations_failed": obl_failed,
                "world_log": world.log})
            print(f"session {k:3d} {mode:17s} final={final} active={[b['date'] for b in active]} consumer_saw={consumer_state.get('saw')} "
                  f"obl={ledger.registered if ledger else 0}/{ledger.discharged if ledger else 0}")
    result = {"provider": a.provider, "model": a.model, "n": a.n, "p_revise": a.p_revise, "seed": a.seed, "offset_ms": a.offset_ms,
              "revisions": a.revisions, "p_cancel_fail": a.p_cancel_fail, "p_rebook_fail": a.p_rebook_fail,
              "consumer_max_ms": a.consumer_max_ms, "interleaved": bool(a.interleave), "compensator": a.compensator, "cells": []}
    for mode, sessions in cells.items():
        n = len(sessions)
        cell = {"mode": mode, "n": n, "revised": sum(s["revise"] for s in sessions),
                "a1": sum(s["a1"] for s in sessions), "a7": sum(s["a7"] for s in sessions),
                "store_wrong": sum(not s["booking_matches_final"] for s in sessions),
                "world_wrong_sessions": sum(1 for s in sessions if s["world_wrong"]),
                "world_wrong_bookings": sum(s["world_wrong"] for s in sessions),
                "double_booked": sum(s["double_booked"] for s in sessions),
                "consumer_saw_stale": sum(s["consumer_saw_stale"] for s in sessions),
                "consumer_saw_none": sum(s["consumer_saw_none"] for s in sessions),
                "world_none": sum(s["world_none"] for s in sessions),
                "obligation_retries": sum(s["obligation_retries"] for s in sessions),
                "obligations_registered": sum(s["obligations_registered"] for s in sessions),
                "obligations_discharged": sum(s["obligations_discharged"] for s in sessions),
                "obligations_failed": sum(s["obligations_failed"] for s in sessions),
                "regenerations": sum(s["regenerations"] for s in sessions),
                "sessions": sessions}
        for key in ("store_wrong", "world_wrong_sessions", "double_booked", "consumer_saw_stale", "consumer_saw_none", "world_none"):
            cell[key + "_ci"] = list(H.clopper_pearson(cell[key], n))
        result["cells"].append(cell)
        print(f"{mode:17s} n={n} A1={cell['a1']} R={cell['a7']} store!=final={cell['store_wrong']} world-wrong={cell['world_wrong_sessions']} "
              f"none={cell['world_none']} double={cell['double_booked']} consumer-stale={cell['consumer_saw_stale']} consumer-none={cell['consumer_saw_none']} "
              f"obl reg/disch/open={cell['obligations_registered']}/{cell['obligations_discharged']}/{cell['obligations_failed']} retries={cell['obligation_retries']}")
    json.dump(result, open(a.out, "w"), indent=1); rec.close()
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
