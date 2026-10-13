#!/usr/bin/env python3
"""303_l1_server_mock.py -- a PROTOCOL mock of crates/runtime/examples/l1_server.rs,
for testing the VerifiedBridge client of probe 303 without a Rust toolchain.

It is NOT the verified store: it re-implements begin/commit in Python with the
same observable semantics (backward validation of the snapshot's read set
against commit times) so that the bridge's framing, interning and locking can
be exercised.  Any measurement must use the Rust binary; this file exists so
that `python3 probes/303_live_a1_outcome.py --bridge-selftest` can run anywhere.
"""
import json, sys

versions = []        # (cell, commit_time, value)
clock = 0
snaps = {}
trace = []
next_snap = 1
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    op = req.get("op")
    if op == "begin":
        rv = []
        for c in req.get("cells", []):
            best = (0, 0)
            for (vc, vt, vv) in versions:
                if vc == c and vt >= best[0]:
                    best = (vt, vv)
            rv.append([c, best[1]])
        sid = next_snap; next_snap += 1
        snaps[sid] = {"agent": req.get("agent", 0), "read_time": clock, "cells": list(req.get("cells", []))}
        print(json.dumps({"snap": sid, "read_time": clock, "read_values": rv}), flush=True)
    elif op == "commit":
        snap = snaps.pop(req.get("snap"), None)
        if snap is None:
            print(json.dumps({"error": "unknown snapshot"}), flush=True); continue
        rt = snap["read_time"]
        fresh = all(not (vc in snap["cells"] and vt > rt) for (vc, vt, vv) in versions)
        if rt > clock or not fresh:
            print(json.dumps({"ok": False, "time": clock}), flush=True); continue
        clock += 1
        writes = [(int(c), int(v)) for c, v in req.get("writes", [])]
        for c, v in writes:
            versions.append((c, clock, v))
        trace.append({"agent": snap["agent"], "read_cells": snap["cells"], "read_time": rt,
                      "write_cells": [c for c, _ in writes], "write_time": clock})
        print(json.dumps({"ok": True, "time": clock}), flush=True)
    elif op == "clock":
        print(json.dumps({"time": clock}), flush=True)
    elif op == "trace":
        print(json.dumps({"trace": trace}), flush=True)
    elif op == "quit":
        print(json.dumps({"bye": True}), flush=True); break
    else:
        print(json.dumps({"error": f"unknown op {op}"}), flush=True)
