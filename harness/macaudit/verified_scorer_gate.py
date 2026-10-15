#!/usr/bin/env python3
"""verified_scorer_gate.py -- score EVERY published A1 cell with the analyser binary
whose A1 verdict is the verified detector (crates/analyser -> detect_a1_verified ->
detect_a1_exec, byte-identical to lib_detect_a1_exec.rs), and check the counts
against (a) the expectations the manuscript asserts (results/expected.json, the
probe-303 receipts) and (b) the Python Definition-1 implementation used by
rescore_cells.py.  Writes tools/verified_scorer.json; exits non-zero on any
disagreement.  This is the receipt behind "the published A1 cells were rescored by
the verified detector executing".

    cargo build --release -p mac-analyser
    python3 harness/macaudit/verified_scorer_gate.py --analyser target/release/analyser --root results
"""
from __future__ import annotations
import argparse, glob, json, os, subprocess, sys, tempfile
from collections import defaultdict

NULL = "NULL"


def agent(r): return r.get("agent", r.get("agent_id"))


def def1(h) -> bool:
    for i, ri in enumerate(h):
        for j, rj in enumerate(h):
            if i == j or agent(ri) == agent(rj):
                continue
            for c in ri.get("read_set", []):
                if c not in rj.get("write_set", []):
                    continue
                if not (ri["read_time"] < rj["write_time"] < ri["write_time"]):
                    continue
                rv = ri.get("read_values", {}).get(c); wv = rj.get("write_values", {}).get(c)
                if (NULL if rv is None else rv) != (NULL if wv is None else wv):
                    return True
    return False


def load(fp):
    out = []
    for line in open(fp):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def run_analyser(binary, fp):
    p = subprocess.run([binary, "--json", "--strict", fp], capture_output=True, text=True)
    if p.returncode == 3:
        return None, "verified detector and port DISAGREE: " + p.stderr.strip()
    if p.returncode != 0:
        return None, f"analyser exit {p.returncode}: {p.stderr.strip()[:200]}"
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]), None
    except Exception as e:  # noqa: BLE001
        return None, f"bad analyser output: {e}"


def probe303_traces(root):
    """one trace per (model, mode, offset, session) from the probe-303 records; the sweep file holds
    several offsets per session, each run opening with its own seed record"""
    for fp in sorted(glob.glob(os.path.join(root, "live_a1_outcome", "*.records.jsonl"))):
        model = os.path.basename(fp).replace(".records.jsonl", "")   # e.g. claude-haiku-4-5_arms150
        groups = defaultdict(list)
        for r in load(fp):
            groups[(r.get("mode"), r.get("session"))].append(r)
        for (mode, sess), g in groups.items():
            runs, cur = [], []
            for r in g:                      # a seed record opens a new run of the session
                if r.get("seed") and cur:
                    runs.append(cur); cur = []
                cur.append(r)
            if cur:
                runs.append(cur)
            for k, run in enumerate(runs):
                # the offset is carried by the flight record (older receipts) or by every record (newer ones)
                off = next((r["offset_ms"] for r in run if "offset_ms" in r), None)
                yield f"{model}/{mode}/{off}ms", f"{sess}.{k}", run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyser", default="target/release/analyser")
    ap.add_argument("--root", default="results")
    ap.add_argument("--out", default="tools/verified_scorer.json")
    a = ap.parse_args()
    if not os.path.exists(a.analyser):
        print(f"FAIL: {a.analyser} not found (cargo build --release -p mac-analyser)"); return 2
    bad = []; cells = {}
    tmp = tempfile.mkdtemp(prefix="vsg_")

    def score_files(name, files, expect=None):
        n = v = py = 0; same_agent = 0
        for fp in files:
            res, err = run_analyser(a.analyser, fp)
            if err:
                bad.append(f"{name}: {os.path.basename(fp)}: {err}"); continue
            n += 1; v += bool(res["a1_verified"]); py += def1(load(fp)); same_agent += res.get("a1_same_agent_pairs", 0)
        cells[name] = {"n": n, "a1_verified": v, "a1_def1_python": py, "same_agent_pairs": same_agent, "expected": expect}
        flag = ""
        if v != py:
            flag = "  <-- verified != Definition-1 python"; bad.append(f"{name}: verified {v} vs python {py}")
        if expect is not None and v != expect:
            flag += "  <-- verified != manuscript"; bad.append(f"{name}: verified {v} vs expected {expect}")
        print(f"{name:58s} n={n:4d} verified={v:4d} def1-python={py:4d} expected={expect if expect is not None else '-':>4}{flag}")

    # (1) the pilot cells the manuscript asserts (results/expected.json)
    exp = json.load(open(os.path.join(a.root, "expected.json")))
    asserted = set()
    for stamp, run in exp.get("runs", {}).items():
        for cell, want in run.get("cells", {}).items():
            files = sorted(glob.glob(os.path.join(a.root, "runs", stamp, cell, "*.jsonl")))
            if files:
                asserted.add((stamp, cell))
                score_files(f"runs/{stamp}/{cell}", files, want.get("a1"))
    # (1b) every other pilot cell under results/runs/ (e.g. the Claude op-record replication, whose counts the
    # manuscript does not assert yet): scored and reported, the verified/Definition-1 agreement still gated
    for cell_dir in sorted(glob.glob(os.path.join(a.root, "runs", "*", "*-*"))):
        if not os.path.isdir(cell_dir) or os.path.basename(cell_dir).startswith((".", "tokens-")):
            continue
        stamp, cell = os.path.basename(os.path.dirname(cell_dir)), os.path.basename(cell_dir)
        if (stamp, cell) in asserted:
            continue
        files = sorted(glob.glob(os.path.join(cell_dir, "*.jsonl")))
        if files:
            score_files(f"runs/{stamp}/{cell}", files, None)
    # (2) the September live study: per-session files
    for m in sorted(glob.glob(os.path.join(a.root, "live_a1_*"))):
        if os.path.basename(m) in ("live_a1_mock", "live_a1_outcome"):
            continue
        for mode in ["store_vanilla", "store_validated", "store_sequential", "superstep"]:
            files = sorted(glob.glob(os.path.join(m, "sessions", f"{mode}_*.jsonl")))
            if files:
                want = None
                try:
                    r = json.load(open(os.path.join(m, "results.json")))
                    want = r["store"][mode.replace("store_", "")]["a1_fires"] if mode.startswith("store_") else r["superstep"]["a1_completion_clock"]["fires"]
                except Exception:
                    pass
                score_files(f"{os.path.basename(m)}/{mode}", files, want)
    # (3) probe 303 (October four-arm run and the offset sweep): split into per-trace temp files
    by_cell = defaultdict(list)
    for cell, sess, run in probe303_traces(a.root):
        fp = os.path.join(tmp, f"{cell.replace('/', '_')}_{sess}.jsonl")
        with open(fp, "w") as f:
            for r in run:
                f.write(json.dumps(r) + "\n")
        by_cell[cell].append(fp)
    receipts = {}
    for fp in glob.glob(os.path.join(a.root, "live_a1_outcome", "*.json")):
        try:
            d = json.load(open(fp))
            for c in d.get("cells", []):
                receipts[f"{os.path.basename(fp)[:-5]}/{c['mode']}/{c['offset_ms']}ms"] = c["a1"]
        except Exception:
            pass
    for cell in sorted(by_cell):
        score_files(cell, sorted(by_cell[cell]), receipts.get(cell))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"analyser": a.analyser, "cells": cells, "problems": bad}, open(a.out, "w"), indent=1)
    print(f"\n{len(cells)} cells scored by the verified detector; {len(bad)} problem(s); receipt {a.out}")
    for b in bad:
        print("PROBLEM", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
