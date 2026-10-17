"""exec_ledger.py -- the basis ledger of probes 303/304 with its BOOKKEEPING in the verified bytes (2026-10-17).

`ExecLedger` has the interface of probe 304's FallibleLedger (register / mark / discharge / superseded, the counters
registered / discharged / failed / retries, and `effects` with "obligation" / "discharged" per key), but every decision
that the paper's Section 5.5 attributes to the ledger -- which effects a superseding write obliges, what a compensator's
report does to an obligation, what is open -- is taken by `l5_exec::L5Ledger` (crates/verus-detector/src/lib_l5_exec.rs,
byte-identical in crates/runtime/src/l5_exec.rs) behind `examples/l5_server.rs`, one JSON object per line on stdio.

What stays in Python, and is listed as such in the paper's trust base: this bridge; the interning of the probe's cell
and value strings to the indices the verified code takes; the store hook that calls `mark` INSIDE the store lock (so the
registration is atomic with the write) and `discharge` outside it; and the compensator (a model call and the world).

The Rust bridge (l5_server.rs) checks the verified preconditions (`report` needs id < len and an unsaturated attempt
counter) and answers an error instead of calling the erased-precondition code; this side propagates that error as an
exception, and cross-checks every reply against its own shadow of the obligation bits: a disagreement raises.
"""
from __future__ import annotations
import hashlib, json, os, subprocess, threading
from pathlib import Path


def find_server(root: str | os.PathLike | None = None) -> str | None:
    """target/release/examples/l5_server under the repo root (or L5_SERVER), else None"""
    env = os.environ.get("L5_SERVER")
    if env and os.path.isfile(env):
        return env
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    for cand in (root / "target" / "release" / "examples" / "l5_server", root / "target" / "debug" / "examples" / "l5_server"):
        if cand.is_file():
            return str(cand)
    return None


class ExecLedger:
    def __init__(self, server: str, on_register=None):
        self.server = server
        with open(server, "rb") as fh:
            self.server_sha256 = hashlib.sha256(fh.read()).hexdigest()
        self.proc = subprocess.Popen([server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.lock = threading.Lock()              # the bridge is one channel: one request in flight at a time
        self.effects: dict = {}                   # key -> {"basis": {cell: value}, "compensate", "obligation", "discharged", "id"}
        self.ids: dict = {}                       # id -> key
        self.cells: dict = {}; self.values: dict = {}    # interning: string -> small int
        self.registered = 0; self.discharged = 0; self.failed = 0; self.retries = 0
        self.on_register = on_register
        self.calls = 0
        r = self._call({"op": "new"})
        if not r.get("ok"):
            raise RuntimeError(f"l5_server did not start: {r}")

    # -- the channel -------------------------------------------------------------------------------------------------
    def _call(self, req: dict) -> dict:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(req) + "\n"); self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("l5_server closed the channel")
        self.calls += 1
        r = json.loads(line)
        if "error" in r:
            raise RuntimeError(f"l5_server refused {req}: {r['error']}")
        return r

    def _intern(self, table: dict, s) -> int:
        if s not in table:
            table[s] = len(table)
        return table[s]

    def close(self):
        try:
            with self.lock:
                self._call({"op": "quit"})
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    # -- the ledger interface (probe 304's FallibleLedger) -----------------------------------------------------------
    def register(self, key, basis: dict, compensate):
        """an effect is out on `basis` ({cell: value}; the probe's bookings depend on the date cell alone)"""
        if len(basis) != 1:
            raise ValueError("the exec ledger carries one basis cell per effect (lib_l5_exec.rs); the probe registers one")
        (cell, value), = basis.items()
        with self.lock:
            r = self._call({"op": "register", "cell": self._intern(self.cells, cell), "basis": self._intern(self.values, value)})
            self.effects[key] = {"basis": dict(basis), "compensate": compensate, "obligation": False, "discharged": False, "id": int(r["id"])}
            self.ids[int(r["id"])] = key

    def mark(self, cell, new_value):
        """REGISTRATION ONLY, called inside the store lock by the atomic ledgered store: the verified `mark` decides which
        effects this write obliges (fresh) and which open obligations it retries; the Python shadow is cross-checked"""
        todo = []
        with self.lock:
            r = self._call({"op": "mark", "cell": self._intern(self.cells, cell), "value": self._intern(self.values, new_value)})
            fresh = [int(i) for i in r["fresh"]]; retried = [int(i) for i in r["retried"]]
            # cross-check against the shadow: the verified decision must coincide with the dictionary's view
            expect_fresh = sorted(e["id"] for e in self.effects.values() if cell in e["basis"] and e["basis"][cell] != new_value and not e["obligation"])
            expect_retry = sorted(e["id"] for e in self.effects.values() if cell in e["basis"] and e["basis"][cell] != new_value and e["obligation"])
            if sorted(fresh) != expect_fresh or sorted(retried) != expect_retry:
                raise RuntimeError(f"exec ledger and shadow disagree on mark({cell}, {new_value}): {fresh}/{retried} vs {expect_fresh}/{expect_retry}")
            for i in fresh:
                e = self.effects[self.ids[i]]; e["obligation"] = True; self.registered += 1; todo.append((self.ids[i], e))
            for i in retried:
                e = self.effects[self.ids[i]]; self.retries += 1; todo.append((self.ids[i], e))
        return todo

    def discharge(self, todo, cell, new_value, t=None):
        """the registration record (stamped with the superseding put's stamp t), the compensation, and the verified
        `report` of its verdict -- outside the store lock, in the superseding writer's thread"""
        for key, e in todo:
            if self.on_register is not None:
                self.on_register(key, cell, new_value, t=t)
            ok = True
            try:
                e["compensate"](new_value)
            except Exception as ex:  # noqa: BLE001  -- the world refused: the obligation stays open
                ok = False; e["error"] = str(ex)
            with self.lock:
                r = self._call({"op": "report", "id": e["id"], "value": self._intern(self.values, new_value), "ok": ok})
                if ok:
                    e["discharged"] = True; self.discharged += 1
                    e["basis"][cell] = new_value; e["obligation"] = False
                else:
                    self.failed += 1; e["discharged"] = False
                if bool(r["obligation"]) != bool(e["obligation"]):
                    raise RuntimeError(f"exec ledger and shadow disagree after report(id={e['id']}, ok={ok}): {r} vs obligation={e['obligation']}")

    def superseded(self, cell, new_value):
        self.discharge(self.mark(cell, new_value), cell, new_value)

    def open_ids(self) -> list[int]:
        with self.lock:
            return [int(i) for i in self._call({"op": "open"})["open"]]

    def receipt(self) -> dict:
        return {"ledger": "exec", "server": os.path.relpath(self.server), "server_sha256": self.server_sha256, "bridge_calls": self.calls}
