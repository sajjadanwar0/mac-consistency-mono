#!/usr/bin/env python3
"""301_l3_server_mock.py -- protocol mock of crates/runtime/examples/l3_server.rs so that
probes/301_a6_toolnode_real_latency.py --selftest can exercise L3Bridge without a Rust
toolchain.  NOT a measurement path: the measured arm uses the verified bytes."""
import json, sys
n = 0; completed = []; emitted = []
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    req = json.loads(line); op = req.get("op")
    if op == "new":
        n = int(req["n"]); completed = [False] * n; emitted = []; print(json.dumps({"ok": True, "n": n}))
    elif op == "complete":
        i = int(req["i"])
        if i >= n: print(json.dumps({"error": f"i={i} out of range (n={n})"}))
        else:
            completed[i] = True; before = len(emitted)
            while len(emitted) < n and completed[len(emitted)]: emitted.append(len(emitted))
            print(json.dumps({"released": emitted[before:]}))
    elif op == "emitted": print(json.dumps({"emitted": emitted}))
    elif op == "quit": print(json.dumps({"bye": True})); break
    else: print(json.dumps({"error": f"unknown op {op}"}))
    sys.stdout.flush()
