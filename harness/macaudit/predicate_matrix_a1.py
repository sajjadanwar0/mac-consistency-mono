#!/usr/bin/env python3
"""predicate_matrix_a1.py -- the Definition-1 transcription gate.

Three implementations of "A1" ship with the artifact and they are NOT the same
predicate:

  TLA+   Anomalies.tla StaleGeneration     i#j, agent_i # agent_j, window, value #
  Verus  lib_detector_equivalence.rs        i!=j, (NO agent field at all), window,
         a1_witness                         value # only when BOTH values present
  Rust   rust-analyser/src/anomalies.rs     i!=j, (no agent check), window,
         detect_a1 (what scored Tables 2/3/6) Option-compare (missing read fires)
  Python check_tables.sh, langgraph_live_a1  Definition 1 verbatim (agent check)

On the committed data all three agree on every published cell (this script
proves that), so the NUMBERS stand; the CLAIMS "scored by the verified
detector" and "restates Definition 1" do not.  Keep this gate in CI so that a
future trace with a same-agent window or a missing read value cannot be
scored three different ways.

    python3 predicate_matrix_a1.py --root results              # prints the matrix
    python3 predicate_matrix_a1.py --root results --strict     # exit 1 on ANY divergence
"""
from __future__ import annotations
import argparse, glob, json, os, sys
from collections import OrderedDict

NULL = "NULL"


def agent(r): return r.get("agent", r.get("agent_id"))


def load(fp):
    out = []
    with open(fp) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def fires(h, variant: str) -> bool:
    """variant in {'def1', 'verus', 'analyser'}"""
    for i, ri in enumerate(h):
        for j, rj in enumerate(h):
            if i == j:
                continue
            if variant == "def1" and agent(ri) == agent(rj):
                continue
            for c in ri.get("read_set", []):
                if c not in rj.get("write_set", []):
                    continue
                if not (ri["read_time"] < rj["write_time"] < ri["write_time"]):
                    continue
                rv = ri.get("read_values", {}).get(c)
                wv = rj.get("write_values", {}).get(c)
                if variant == "def1":
                    if (NULL if rv is None else rv) != (NULL if wv is None else wv):
                        return True
                elif variant == "verus":
                    if rv is not None and wv is not None and rv != wv:
                        return True
                else:  # analyser: Option != Option
                    if rv != wv:
                        return True
    return False


def cells(root: str):
    """yield (name, [jsonl files]) for every committed op-record cell"""
    # pilot runs
    for run in sorted(glob.glob(os.path.join(root, "runs", "2026*"))):
        for cell in sorted(os.listdir(run)):
            d = os.path.join(run, cell)
            if os.path.isdir(d) and not cell.startswith("tokens"):
                files = sorted(glob.glob(os.path.join(d, "*.jsonl")))
                if files:
                    yield f"runs/{os.path.basename(run)}/{cell}", files
    # live study
    for m in sorted(glob.glob(os.path.join(root, "live_a1_*"))):
        if os.path.basename(m) == "live_a1_mock":
            continue
        for mode in ["store_vanilla", "store_validated", "store_sequential", "superstep"]:
            files = sorted(glob.glob(os.path.join(m, "sessions", f"{mode}_*.jsonl")))
            if files:
                yield f"{os.path.basename(m)}/{mode}", files
    # other op-record directories, scored per file (one session per file)
    for d in ["oprecords", "dynamic_oprecords", "mast_oprecords", "production_traces", "traces"]:
        p = os.path.join(root, d)
        if os.path.isdir(p):
            files = sorted(glob.glob(os.path.join(p, "**", "*.jsonl"), recursive=True))
            if files:
                yield d, files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    print(f"{'cell':52s} {'n':>5s} {'Def1':>5s} {'Verus':>5s} {'analyser':>8s}")
    diverging = 0
    for name, files in cells(a.root):
        n = d1 = dv = da = 0
        for fp in files:
            h = load(fp)
            n += 1
            d1 += fires(h, "def1"); dv += fires(h, "verus"); da += fires(h, "analyser")
        flag = "" if d1 == dv == da else "   <-- DIVERGES"
        if flag:
            diverging += 1
        print(f"{name:52s} {n:5d} {d1:5d} {dv:5d} {da:8d}{flag}")
    print(f"cells where the three transcriptions disagree: {diverging}")
    if a.strict and diverging:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
