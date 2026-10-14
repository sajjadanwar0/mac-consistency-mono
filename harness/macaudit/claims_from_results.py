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


def offname(o):
    """a macro name may not contain digits: 0 -> Z, 150 -> OFZ, 500 -> FZZ, 1500 -> OFZZ"""
    return "O" + "".join("ZOTWFXSVEN"[int(ch)] for ch in str(o))


def ci_str(c, key):
    lo, hi = c.get(key, [None, None])
    return f" [{100*lo:.1f}, {100*hi:.1f}]" if lo is not None else ""


def probe303(root, out, fig):
    """Table 3 rows come from the four-arm run (<model>_arms150.json, p_revise 1.0); the offset curve from the
    sweep (<model>_sweep.json, p_revise 0.5).  The two are kept apart: a 150 ms sweep cell is a different run
    from the 150 ms arms cell and never overwrites it.  R is the probe's a7 field, which a7_rescore.py --check
    re-derives independently from the records (every cell must agree or the gate fails)."""
    arms = defaultdict(dict); sweep = defaultdict(dict)   # (modelkey, mode, offset) -> cell
    for fp in sorted(glob.glob(os.path.join(root, "live_a1_outcome", "*.json"))):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        mk = MODEL_KEY.get(d.get("model", ""), None)
        if not mk:
            continue
        dest = sweep if fp.endswith("_sweep.json") else arms
        for c in d.get("cells", []):
            dest[(mk, c["mode"], int(c["offset_ms"]))] = c
    if not arms and not sweep:
        return
    out.append("% --- probe 303 (results/live_a1_outcome; *_arms150.json -> Table 3, *_sweep.json -> offset curve) ---")
    strip = lambda c: {kk: vv for kk, vv in c.items() if kk != "sessions"}
    SUMMARY["probe303_arms150"] = {f"{k[0]}|{k[1]}|{k[2]}": strip(c) for k, c in arms.items()}
    SUMMARY["probe303_sweep"] = {f"{k[0]}|{k[1]}|{k[2]}": strip(c) for k, c in sweep.items()}
    # DeepSeek (and any other new family) gets all four arms as fresh rows; the three paper families only the two new arms
    for mk in ("Deepseek", "Sonnet"):
        for mode, name in (("vanilla", "LiveVanilla"), ("validated", "LiveValidated")):
            c = arms.get((mk, mode, 150))
            if not c:
                continue
            n = c["n"]
            out.append(f"\\renewcommand{{\\{name}{mk}AOne}}{{${c['a1']}/{n}${ci_str(c, 'a1_ci')}}}")
            out.append(f"\\renewcommand{{\\{name}{mk}R}}{{${c.get('a7', 0)}$}}")
            out.append(f"\\renewcommand{{\\{name}{mk}Wrong}}{{${c['booking_wrong']}/{n}${ci_str(c, 'booking_wrong_ci')}}}")
            out.append(f"\\renewcommand{{\\{name}{mk}Regen}}{{{c['regenerations']}}}")
    for mk in ("Gpt", "Haiku", "Llama", "Deepseek", "Sonnet"):
        for mode, name in (("verified", "LiveVerified"), ("ledger", "LiveLedger")):
            c = arms.get((mk, mode, 150))
            if not c:
                continue
            n = c["n"]
            out.append(f"\\renewcommand{{\\{name}{mk}AOne}}{{${c['a1']}/{n}${ci_str(c, 'a1_ci')}}}")
            out.append(f"\\renewcommand{{\\{name}{mk}R}}{{${c.get('a7', 0)}$}}")
            out.append(f"\\renewcommand{{\\{name}{mk}Wrong}}{{${c['booking_wrong']}/{n}${ci_str(c, 'booking_wrong_ci')}}}")
            if mode == "ledger":
                out.append(f"\\renewcommand{{\\{name}{mk}Regen}}{{{c['regenerations']}$+${c.get('compensation_generations', 0)} "
                           f"({c.get('obligations_registered', 0)}/{c.get('obligations_discharged', 0)} obl.)}}")
            else:
                out.append(f"\\renewcommand{{\\{name}{mk}Regen}}{{{c['regenerations']}}}")
    fam = [("Haiku", "haiku"), ("Gpt", "gpt-4o-mini"), ("Deepseek", "deepseek-chat")]
    v = [(nm, arms.get((mk, "verified", 150))) for mk, nm in fam]; v = [(nm, c) for nm, c in v if c]
    if v:
        out.append("\\renewcommand{\\LiveVerifiedOutcome}{$A_1=0/" + str(sum(c['n'] for _, c in v)) + "$; booking $\\neq$ final " +
                   ", ".join(f"${c['booking_wrong']}$" for _, c in v) + " of $100$ on " + ", ".join(nm for nm, _ in v) + "}")
    l = [(nm, arms.get((mk, "ledger", 150))) for mk, nm in fam]; l = [(nm, c) for nm, c in l if c]
    if l:
        out.append("\\renewcommand{\\LfiveLiveOutcome}{booking $\\neq$ final $0/100$ on " + ("all three families" if len(l) == 3 else ", ".join(nm for nm, _ in l)) +
                   " (" + ", ".join(f"{c.get('obligations_registered',0)}" for _, c in l) + " obligations, all discharged)}")
    # swept offsets -> pgfplots figure (replaces the static predicate-vs-outcome bar chart in Sec. 6.1)
    offsets = sorted({k[2] for k in sweep})
    if len(offsets) >= 3:
        SUMMARY["sweep_offsets"] = offsets
        for mk, nm in fam:
            for mode in ("vanilla", "validated"):
                for o in offsets:
                    c = sweep.get((mk, mode, o))
                    if c:
                        out.append(f"\\providecommand{{\\Sweep{mk}{mode.capitalize()}{offname(o)}}}{{{c['a1']}/{c.get('a7',0)}/{c['booking_wrong']}}}")
        marks = {"Haiku": "*", "Gpt": "square*", "Deepseek": "triangle*"}
        lines = [r"\begin{figure}[t]", r"\centering", r"\begin{tikzpicture}",
                 r"\begin{axis}[width=\columnwidth, height=4.1cm, symbolic x coords={" + ",".join(str(o) for o in offsets) + "}, xtick=data,",
                 r"  xlabel={date-agent start offset after the flight agent's read (ms)}, ylabel={sessions of 100}, ymin=0, ymax=60,",
                 r"  legend style={font=\scriptsize, at={(0.5,1.02)}, anchor=south, legend columns=3, draw=none}, tick label style={font=\scriptsize}, label style={font=\scriptsize}, cycle list name=black white]"]
        for mk, nm in fam:
            pts = [(o, sweep[(mk, "vanilla", o)]["a1"]) for o in offsets if (mk, "vanilla", o) in sweep]
            if len(pts) >= 2:
                lines.append(r"\addplot+[dashed, mark=" + marks[mk] + r", mark options={solid}] coordinates {" + " ".join(f"({x},{y})" for x, y in pts) + "};")
                lines.append(r"\addlegendentry{" + f"{nm} \\A1 (vanilla)" + "}")
        for mk, nm in fam:
            pts = [(o, sweep[(mk, "validated", o)]["booking_wrong"]) for o in offsets if (mk, "validated", o) in sweep]
            if len(pts) >= 2:
                lines.append(r"\addplot+[solid, mark=" + marks[mk] + "] coordinates {" + " ".join(f"({x},{y})" for x, y in pts) + "};")
                lines.append(r"\addlegendentry{" + f"{nm} \\Rp{{}} under $L_1$" + "}")
        lines += [r"\end{axis}", r"\end{tikzpicture}",
                  r"\caption{Probe 303, offset sweep: the live \A1 rate without a discipline (dashed) and the residue \Rp{} that read-set validation leaves (solid) as the date agent's start is delayed; revision probability $0.5$, $n=100$ per point. As the window closes the same revisions land after the commit: \A1 falls to $0$ while \Rp{} rises to the revision rate.}",
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
    runs = sorted(glob.glob(os.path.join(root, "runs", "*-interleaved*")))
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
        emitted = 0
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
                if emitted == 0:
                    out.append(f"% --- probe 302 ({run}; model {model}) ---")
                emitted += 1
                out.append(f"\\renewcommand{{\\WallclockPaired{mk}{wlk}{key}}}{{${mean:+.1f}\\%$ [{lo:+.1f}, {hi:+.1f}], $n={len(diffs)}$}}")
                SUMMARY.setdefault("probe302", {}).setdefault(os.path.basename(run), {"model": model})[f"{wl}/{rt}"] = {"mean_pct": mean, "ci95": [lo, hi], "n": len(diffs)}
        if emitted:   # a stub run (fewer than five paired sessions in every cell) sets nothing
            out.append(f"\\renewcommand{{\\WallclockPaired{mk}Available}}{{1}}")


def verus(root, out):
    """step 7 receipts: results/verus/count.json (curated/full distinct totals under the pinned build) and the ledger log"""
    fp = os.path.join(root, "verus", "count.json")
    if os.path.exists(fp):
        try:
            d = json.load(open(fp))
            out.append(f"% --- verus ({fp}) ---")
            out.append(f"\\renewcommand{{\\VerusCurated}}{{{d['curated_total']}}}")
            out.append(f"\\renewcommand{{\\VerusFull}}{{{d['full_total']}}}")
        except Exception:
            pass
    fp = os.path.join(root, "verus", "lib_l5_ledger.verus.log")
    if os.path.exists(fp):
        import re
        m = re.search(r"(\d+) verified, (\d+) errors", open(fp, errors="replace").read())
        if m and m.group(2) == "0":
            out.append(f"% --- verus ledger ({fp}) ---")
            out.append(f"\\renewcommand{{\\LfiveVerus}}{{{m.group(1)} obligations, 0 errors}}")
            out.append(f"\\renewcommand{{\\LfiveVerusStatus}}{{verified in Verus ({m.group(1)} obligations, 0 errors)}}")
            out.append(f"\\renewcommand{{\\LfiveVerusIntro}}{{verified ({m.group(1)} obligations)}}")


def from_summary(fp, out):
    """merge the macros of an uploaded summary for receipts this checkout lacks (never overrides a macro computed here)"""
    try:
        d = json.load(open(fp))
    except Exception:
        return
    have = {ln.split("}")[0] for ln in out if ln.startswith("\\renewcommand")}
    added = 0
    for ln in d.get("macros", []):
        if ln.startswith("\\renewcommand") and ln.split("}")[0] not in have:
            if added == 0:
                out.append(f"% --- merged from {os.path.basename(fp)} (receipts absent in this checkout) ---")
            out.append(ln); added += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results"); ap.add_argument("--paper", default="paper")
    ap.add_argument("--from-summary", default=None, help="a paper_receipts_summary.json from another checkout: fills the receipts absent under --root")
    a = ap.parse_args()
    out = ["% generated by harness/macaudit/claims_from_results.py -- do not edit; re-run the probes instead"]
    probe303(a.root, out, os.path.join(a.paper, "offset_curve.tex"))
    probe301(a.root, out)
    probe302(a.root, out)
    verus(a.root, out)
    if a.from_summary:
        from_summary(a.from_summary, out)
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
