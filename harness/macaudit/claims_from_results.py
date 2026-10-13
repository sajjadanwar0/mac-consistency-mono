#!/usr/bin/env python3
"""claims_from_results.py -- turn the receipts the probes write into the LaTeX
macros the paper's pending cells are waiting for.  Writes paper/claims_results.tex
(\\renewcommand overrides of the [pending] defaults in paper/claims.tex; main.tex
inputs it if it exists) and, when a swept-offset run exists, paper/offset_curve.tex
(a pgfplots figure the evaluation section includes if present).

    python3 harness/macaudit/claims_from_results.py --root results --paper paper

Receipts understood:
  results/live_a1_outcome/*.json        probe 303 (A1 sweep; verified and ledger arms)
  results/a6_real_latency/*.jsonl       probe 301 (ToolNode replay against real effects)
  results/runs/*-interleaved/           probe 302 (interleaved wall-clock rerun; token sidecars)
Nothing is overridden for a receipt that is absent, so the paper keeps printing
[pending] for exactly the runs that have not happened.
"""
from __future__ import annotations
import argparse, glob, json, os, random, statistics, sys
from collections import defaultdict

MODEL_KEY = {"gpt-4o-mini": "Gpt", "claude-haiku-4-5": "Haiku", "llama3.2": "Llama", "llama-3.2": "Llama",
             "deepseek-chat": "Deepseek", "claude-sonnet-4-5": "Sonnet"}
SUMMARY = {}   # everything the paper needs, written to results/paper_receipts_summary.json (one file to upload)


def tex_num(x):
    return f"{x:,}".replace(",", "{,}")


def probe303(root, out, fig):
    files = sorted(glob.glob(os.path.join(root, "live_a1_outcome", "*.json")))
    cells = defaultdict(dict)   # (modelkey, mode, offset) -> cell
    for fp in files:
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        mk = MODEL_KEY.get(d.get("model", ""), None)
        if not mk:
            continue
        for c in d.get("cells", []):
            cells[(mk, c["mode"], int(c["offset_ms"]))] = c
    if not cells:
        return
    out.append("% --- probe 303 (results/live_a1_outcome) ---")
    SUMMARY["probe303_cells"] = {f"{k[0]}|{k[1]}|{k[2]}": {kk: vv for kk, vv in c.items() if kk != "sessions"} for k, c in cells.items()}
    # DeepSeek (and any other new family) gets all four arms as fresh rows; the three paper families only the two new arms
    for mk in ("Deepseek", "Sonnet"):
        for mode, name in (("vanilla", "LiveVanilla"), ("validated", "LiveValidated")):
            c = cells.get((mk, mode, 150))
            if not c:
                continue
            n = c["n"]; lo, hi = c.get("a1_ci", [None, None])
            ci = f" [{100*lo:.1f}, {100*hi:.1f}]" if lo is not None else ""
            out.append(f"\\renewcommand{{\\{name}{mk}AOne}}{{${c['a1']}/{n}${ci}}}")
            out.append(f"\\renewcommand{{\\{name}{mk}R}}{{${c.get('a7', 0)}$}}")
            out.append(f"\\renewcommand{{\\{name}{mk}Wrong}}{{${c['booking_wrong']}/{n}$}}")
            out.append(f"\\renewcommand{{\\{name}{mk}Regen}}{{{c['regenerations']}}}")
    for mk in ("Gpt", "Haiku", "Llama", "Deepseek", "Sonnet"):
        for mode, name in (("verified", "LiveVerified"), ("ledger", "LiveLedger")):
            c = cells.get((mk, mode, 150))
            if not c:
                continue
            n = c["n"]
            out.append(f"\\renewcommand{{\\{name}{mk}AOne}}{{${c['a1']}/{n}$}}")
            out.append(f"\\renewcommand{{\\{name}{mk}R}}{{${c.get('a7', 0)}$}}")
            lo, hi = c.get("booking_wrong_ci", [None, None])
            ci = f" [{100*lo:.1f}, {100*hi:.1f}]" if lo is not None else ""
            out.append(f"\\renewcommand{{\\{name}{mk}Wrong}}{{${c['booking_wrong']}/{n}${ci}}}")
            if mode == "ledger":
                out.append(f"\\renewcommand{{\\{name}{mk}Regen}}{{{c['regenerations']}$+${c.get('compensation_generations', 0)} "
                           f"({c.get('obligations_registered', 0)}/{c.get('obligations_discharged', 0)} obl.)}}")
            else:
                out.append(f"\\renewcommand{{\\{name}{mk}Regen}}{{{c['regenerations']}}}")
    # a one-line summary for the intro / limitations macros
    v = [cells.get((mk, "verified", 150)) for mk in ("Gpt", "Haiku")]
    if all(v):
        out.append("\\renewcommand{\\LiveVerifiedOutcome}{" + "; ".join(
            f"{mk.lower()}: $A_1={c['a1']}/{c['n']}$, booking $\\neq$ final ${c['booking_wrong']}/{c['n']}$" for mk, c in zip(("gpt-4o-mini", "haiku"), v)) + "}")
    l = [cells.get((mk, "ledger", 150)) for mk in ("Gpt", "Haiku")]
    if all(l):
        out.append("\\renewcommand{\\LfiveLiveOutcome}{" + "; ".join(
            f"{mk.lower()}: booking $\\neq$ final ${c['booking_wrong']}/{c['n']}$, {c.get('obligations_registered',0)} obligations registered, "
            f"{c.get('obligations_discharged',0)} discharged, {c.get('compensation_generations',0)} compensation generations" for mk, c in zip(("gpt-4o-mini", "haiku"), l)) + "}")
    # swept offsets -> pgfplots figure
    offsets = sorted({k[2] for k in cells})
    if len(offsets) >= 3:
        lines = [r"\begin{figure}[t]", r"\centering", r"\begin{tikzpicture}",
                 r"\begin{axis}[width=\columnwidth, height=4.2cm, xmode=log, log basis x=10, xlabel={date-agent start offset (ms; 0 drawn at 1)},",
                 r"  ylabel={sessions of 100}, ymin=0, ymax=100, legend style={font=\scriptsize, at={(0.5,1.02)}, anchor=south, legend columns=3}, tick label style={font=\scriptsize}, label style={font=\scriptsize}]"]
        for mk, mname in (("Gpt", "gpt-4o-mini"), ("Haiku", "claude-haiku-4-5")):
            for mode, metric, label in (("vanilla", "a1", "$A_1$"), ("vanilla", "booking_wrong", "booking$\\neq$final"), ("validated", "booking_wrong", "$L_1$ residue")):
                pts = [(max(o, 1), cells[(mk, mode, o)][metric]) for o in offsets if (mk, mode, o) in cells]
                if len(pts) >= 2:
                    lines.append(r"\addplot+[mark=*] coordinates {" + " ".join(f"({x},{y})" for x, y in pts) + "};")
                    lines.append(r"\addlegendentry{" + f"{mname} {label}" + "}")
        lines += [r"\end{axis}", r"\end{tikzpicture}",
                  r"\caption{Probe 303: the live \A1 rate and the outcome as a function of the date agent's start offset (revision probability $0.5$; $n=100$ per cell).}",
                  r"\label{fig:offset}", r"\end{figure}"]
        open(fig, "w").write("\n".join(lines) + "\n")
        out.append("\\renewcommand{\\OffsetCurveAvailable}{1}")


def probe301(root, out):
    for backend in ("sqlite", "http"):
        fp = os.path.join(root, "a6_real_latency", f"{backend}.jsonl")
        if not os.path.exists(fp):
            continue
        n = reord = 0
        for line in open(fp):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line); n += 1; reord += int(bool(r.get("baseline_a6")))
        if n:
            out.append(f"% --- probe 301 ({fp}) ---")
            out.append(f"\\renewcommand{{\\ToolNodeReal{backend.capitalize()}}}{{${reord}/{n}$}}")
            SUMMARY.setdefault("probe301", {})[backend] = {"replays": n, "baseline_a6": reord}


def probe302(root, out, boot=2000, seed=1):
    runs = sorted(glob.glob(os.path.join(root, "runs", "*-interleaved")))
    if not runs:
        return
    rng = random.Random(seed)
    for run in runs:
        sess = defaultdict(lambda: defaultdict(float))   # (workload, runtime) -> session idx -> wall ms
        model = None
        for fp in glob.glob(os.path.join(run, "tokens-*", "*.tokens.jsonl")):
            for line in open(fp):
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                model = model or r.get("model")
                idx = r["session_id"].rsplit("-", 1)[-1]
                sess[(r["workload"], r["runtime"])][idx] += float(r.get("wall_clock_ms", 0))
        if not sess:
            continue
        mk = "Claude" if (model or "").startswith("claude") else "Gpt"
        out.append(f"% --- probe 302 ({run}; model {model}) ---")
        for wl in sorted({k[0] for k in sess}):
            base = sess.get((wl, "vanilla"), {})
            for rt in ("pessimistic", "snapshot_isolation"):
                arm = sess.get((wl, rt), {})
                common = sorted(set(base) & set(arm))
                if len(common) < 5:
                    continue
                diffs = [(arm[i] - base[i]) / base[i] * 100 for i in common if base[i] > 0]
                mean = statistics.fmean(diffs)
                bs = []
                for _ in range(boot):
                    smp = [diffs[rng.randrange(len(diffs))] for _ in diffs]
                    bs.append(statistics.fmean(smp))
                bs.sort(); lo, hi = bs[int(0.025 * boot)], bs[int(0.975 * boot) - 1]
                key = {"pessimistic": "Pess", "snapshot_isolation": "SI"}[rt]
                wlk = "".join(p.capitalize() for p in wl.split("-"))
                out.append(f"\\renewcommand{{\\WallclockPaired{mk}{wlk}{key}}}{{${mean:+.1f}\\%$ [{lo:+.1f}, {hi:+.1f}], $n={len(diffs)}$}}")
                SUMMARY.setdefault("probe302", {}).setdefault(os.path.basename(run), {"model": model})[f"{wl}/{rt}"] = {"mean_pct": mean, "ci95": [lo, hi], "n": len(diffs)}
        out.append(f"\\renewcommand{{\\WallclockPaired{mk}Available}}{{1}}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results"); ap.add_argument("--paper", default="paper")
    a = ap.parse_args()
    out = ["% generated by harness/macaudit/claims_from_results.py -- do not edit; re-run the probes instead"]
    probe303(a.root, out, os.path.join(a.paper, "offset_curve.tex"))
    probe301(a.root, out)
    probe302(a.root, out)
    os.makedirs(a.paper, exist_ok=True)
    open(os.path.join(a.paper, "claims_results.tex"), "w").write("\n".join(out) + "\n")
    # formal receipts, if present, ride along in the same summary
    for extra in ("verus/count.json",):
        fp = os.path.join(a.root, extra)
        if os.path.exists(fp):
            try: SUMMARY[extra] = json.load(open(fp))
            except Exception: pass
    for extra in ("verus/lib_l5_ledger.verus.log", "../formal/tla/tlaps.CommitOrder.log", "live_l2_haiku1000/summary.txt"):
        fp = os.path.join(a.root, extra)
        if os.path.exists(fp):
            SUMMARY[extra] = open(fp, errors="replace").read()[-4000:]
    SUMMARY["macros"] = out
    sp = os.path.join(a.root, "paper_receipts_summary.json")
    json.dump(SUMMARY, open(sp, "w"), indent=1)
    print("\n".join(out))
    print(f"\nwrote {os.path.join(a.paper, 'claims_results.tex')} ({len(out)-1} overrides)")
    print(f"wrote {sp}  <- upload THIS one file; the paper is regenerated from it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
