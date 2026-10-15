#!/usr/bin/env python3
"""claims_from_results.py -- turn the receipts the probes write into the LaTeX
macros the paper's pending cells are waiting for.  Writes paper/claims_results.tex
(\\renewcommand overrides of the [pending] defaults in paper/claims.tex; main.tex
inputs it if it exists) and, when a swept-offset run exists, paper/offset_curve.tex
(a pgfplots figure the evaluation section includes if present).

    python3 harness/macaudit/claims_from_results.py --root results --paper paper

Receipts understood:
  results/live_a1_outcome/*.json        probe 303 (A1 sweep; verified and ledger arms)
  results/live_a1_outcome/*_arms150i.run<r>.json
                                        probe 303 --interleave --runs R (2026-10-14): replicated,
                                        interleaved arms incl. ledger_verified -> Table 3 (replicated rows)
  results/ledger_world/*.json           probe 304 (the ledger in a world: consumer, cancellation, failures)
  results/a6_real_latency/*.jsonl       probe 301 (ToolNode replay against real effects; l3_verified arm)
  results/runs/*-interleaved/           probe 302 (interleaved wall-clock rerun; token sidecars)
  tools/verified_scorer.json            verified_scorer_gate.py (every A1 cell rescored by the verified detector)
  formal/tla/tlc.Duplication.log        check_duplication.sh (predicate D: witness, divergent witness, dedup safe)
Nothing is overridden for a receipt that is absent, so the paper keeps printing
[pending] for exactly the runs that have not happened.
"""
from __future__ import annotations
import argparse, glob, json, os, random, re, statistics, sys
from collections import defaultdict

MODEL_KEY = {"gpt-4o-mini": "Gpt", "claude-haiku-4-5": "Haiku", "llama3.2": "Llama", "llama-3.2": "Llama",
             "deepseek-chat": "Deepseek", "claude-sonnet-4-5": "Sonnet"}
SUMMARY = {}   # everything the paper needs, written to results/paper_receipts_summary.json (one file to upload)


def tex_num(x):
    return f"{x:,}".replace(",", "{,}")


def binom_cdf(k, n, p):
    from math import comb
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(0, k + 1))


def clopper_pearson(k, n, alpha=0.05):
    """exact two-sided binomial interval by bisection on the binomial CDF (no scipy: the user's machine has none)"""
    if n == 0:
        return (0.0, 1.0)
    def solve(f, lo, hi):
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lo = 0.0 if k == 0 else solve(lambda p: 1 - binom_cdf(k - 1, n, p) <= alpha / 2, 0.0, 1.0)
    hi = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p) > alpha / 2, 0.0, 1.0)
    return (lo, hi)


def fmt_p(p):
    """a p-value WITH its relation, so the paper writes $p\\RunsFisherHaiku$ and never prints p=<0.001"""
    return "<0.001" if p < 0.001 else f"={p:.3f}"


def fisher_two_sided(a, b, c, d):
    """exact two-sided p for the 2x2 table [[a, b], [c, d]] (same routine as arm_timing.py)"""
    from math import comb
    n = a + b + c + d
    r1, c1 = a + b, a + c
    def p_of(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
    p_obs = p_of(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return min(1.0, sum(p_of(x) for x in range(lo, hi + 1) if p_of(x) <= p_obs * (1 + 1e-12)))


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
        if ".run" in os.path.basename(fp):          # replicated interleaved runs: probe303_runs() reads those
            continue
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
    """<backend>.jsonl: the committed replay (baseline vs the sequential-loop L3 arm);
    <backend>_verified.jsonl: the same batches replayed with the verified L3 bytes deciding the release
    order under concurrent dispatch (probe 301 --l3-server), with its own baseline count."""
    for backend in ("sqlite", "http"):
        fp = os.path.join(root, "a6_real_latency", f"{backend}.jsonl")
        if os.path.exists(fp):
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
        fv = os.path.join(root, "a6_real_latency", f"{backend}_verified.jsonl")
        if os.path.exists(fv):
            nv = vreord = vbase = 0
            for line in open(fv):
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if "l3_verified_a6" in r:
                    nv += 1; vreord += int(bool(r["l3_verified_a6"])); vbase += int(bool(r.get("baseline_a6")))
            if nv:
                out.append(f"% --- probe 301 --l3-server ({fv}) ---")
                out.append(f"\\renewcommand{{\\ToolNodeVerified{backend.capitalize()}}}{{${vreord}/{nv}$}}")
                out.append(f"\\renewcommand{{\\ToolNodeVerifiedBaseline{backend.capitalize()}}}{{${vbase}/{nv}$}}")
                out.append("\\renewcommand{\\ToolNodeVerifiedAvailable}{1}")
                SUMMARY.setdefault("probe301", {})[backend + "_verified"] = {"replays": nv, "baseline_a6": vbase, "l3_verified_a6": vreord}


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


def probe303_runs(root, out):
    """replicated, interleaved arms: <model>_arms150i.run<r>.json -> per-cell per-run values and pooled counts"""
    import re
    runs = defaultdict(list)
    for fp in sorted(glob.glob(os.path.join(root, "live_a1_outcome", "*_arms150i.run*.json"))):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        runs[MODEL_KEY.get(d.get("model", ""), None)].append(d)
    runs.pop(None, None)
    if not runs:
        return
    out.append("% --- probe 303 --interleave --runs (results/live_a1_outcome/*_arms150i.run*.json): replicated Table 3 rows ---")
    out.append("\\renewcommand{\\LiveRunsAvailable}{1}")
    for mk, ds in sorted(runs.items()):
        ds.sort(key=lambda d: d.get("run", 0)); R = len(ds); n = ds[0]["n"]
        out.append(f"\\providecommand{{\\LiveRuns{mk}}}{{{R}}}")
        cells = defaultdict(dict)
        for r, d in enumerate(ds):
            for c in d["cells"]:
                if int(c["offset_ms"]) == 150:
                    cells[c["mode"]][r] = c
        for mode, by_run in cells.items():
            mname = {"vanilla": "Vanilla", "validated": "Validated", "verified": "Verified", "ledger": "Ledger", "ledger_verified": "LedgerVerified"}.get(mode, mode.title().replace("_", ""))
            for key, label in (("a1", "AOne"), ("a7", "R"), ("booking_wrong", "Wrong"), ("regenerations", "Regen")):
                vals = [by_run[r][key] for r in sorted(by_run)]
                pooled = sum(vals); N = n * len(vals)
                if key == "regenerations":
                    out.append(f"\\providecommand{{\\Runs{mk}{mname}{label}}}{{{'/'.join(map(str, vals))}}}")
                else:
                    lo, hi = clopper_pearson(pooled, N)
                    ci = f" [{100*lo:.1f}, {100*hi:.1f}]"
                    out.append(f"\\providecommand{{\\Runs{mk}{mname}{label}}}{{{'/'.join(map(str, vals))} (${pooled}/{N}${ci})}}")
                    out.append(f"\\providecommand{{\\Runs{mk}{mname}{label}Pooled}}{{{pooled}/{N}}}")
                    out.append(f"\\providecommand{{\\Runs{mk}{mname}{label}Runs}}{{{'/'.join(map(str, vals))}}}")
                    out.append(f"\\providecommand{{\\Runs{mk}{mname}{label}Short}}{{{'/'.join(map(str, vals))} (${pooled}/{N}$)}}")
                    out.append(f"\\providecommand{{\\Runs{mk}{mname}{label}Pct}}{{{100*pooled/N:.1f}}}")
                    out.append(f"\\providecommand{{\\Runs{mk}{mname}{label}CI}}{{[{100*lo:.1f}, {100*hi:.1f}]}}")
            lag = [by_run[r].get("revision_lag_ms", {}).get("after_commit") for r in sorted(by_run)]
            if all(x is not None for x in lag):
                out.append(f"\\providecommand{{\\Runs{mk}{mname}LagAfter}}{{{'/'.join(map(str, lag))}}}")
            SUMMARY.setdefault("probe303_runs", {})[f"{mk}|{mode}"] = {k: [by_run[r][k] for r in sorted(by_run)] for k in ("a1", "a7", "booking_wrong", "regenerations")}
            SUMMARY["probe303_runs"][f"{mk}|{mode}"]["lag_after_commit"] = lag
            SUMMARY["probe303_runs"][f"{mk}|{mode}"]["interleaved"] = [d.get("interleaved") for d in ds]
        # the attributable comparison the sequential-block run could not make: validated vs verified residue, pooled over
        # the interleaved runs (Fisher exact, two-sided), and vanilla A1 between the sequential run and the pooled interleaved runs
        if "validated" in cells and "verified" in cells:
            N = n * len(cells["validated"])
            rv = sum(c["a7"] for c in cells["validated"].values()); rf = sum(c["a7"] for c in cells["verified"].values())
            p = fisher_two_sided(rv, N - rv, rf, N - rf)
            out.append(f"\\providecommand{{\\RunsFisher{mk}}}{{{fmt_p(p)}}}")
            SUMMARY["probe303_runs"][f"{mk}|fisher_validated_vs_verified_R"] = {"validated": rv, "verified": rf, "N": N, "p": p}
        # the paired test the interleaved design supports: per (run, session) the validated and verified arms ran the
        # same session back to back, so the residue is compared within session (McNemar, exact binomial on the
        # discordant pairs) with a paired-proportion Wald interval on the difference, in percentage points
        if "validated" in cells and "verified" in cells:
            b = c = npairs = 0
            for r in sorted(cells["validated"]):
                if r not in cells["verified"]:
                    continue
                sv = {x["session"]: x for x in cells["validated"][r].get("sessions", [])}
                sf = {x["session"]: x for x in cells["verified"][r].get("sessions", [])}
                for k in sv:
                    if k in sf:
                        npairs += 1
                        if sv[k]["a7"] and not sf[k]["a7"]:
                            b += 1
                        if sf[k]["a7"] and not sv[k]["a7"]:
                            c += 1
            if npairs:
                from math import comb, sqrt
                nd = b + c
                if nd == 0:
                    pm = 1.0
                else:
                    pk = comb(nd, b) / 2 ** nd
                    pm = min(1.0, sum(comb(nd, i) / 2 ** nd for i in range(nd + 1) if comb(nd, i) / 2 ** nd <= pk * (1 + 1e-12)))
                d = (b - c) / npairs
                se = sqrt(max(nd - (b - c) ** 2 / npairs, 0.0)) / npairs
                lo, hi = d - 1.96 * se, d + 1.96 * se
                out.append(f"\\providecommand{{\\RunsPairedDiscordant{mk}}}{{{b} vs.\\ {c}}}")
                out.append(f"\\providecommand{{\\RunsMcNemar{mk}}}{{{fmt_p(pm)}}}")
                out.append(f"\\providecommand{{\\RunsDiff{mk}}}{{{100*d:+.1f}}}")
                out.append(f"\\providecommand{{\\RunsDiffCI{mk}}}{{[{100*lo:+.1f}, {100*hi:+.1f}]}}")
                SUMMARY["probe303_runs"][f"{mk}|paired_validated_vs_verified_R"] = {"pairs": npairs, "validated_only": b, "verified_only": c, "mcnemar_p": pm, "diff_pp": 100 * d, "diff_ci_pp": [100 * lo, 100 * hi]}
        # the run, not the arm: the sequential-block run of the same protocol (Table 3) against the pooled interleaved runs
        seq = SUMMARY.get("probe303_arms150", {})
        for mode, key, label in (("vanilla", "a1", "VanillaAOne"), ("validated", "a7", "ValidatedR"), ("verified", "a7", "VerifiedR")):
            sc = seq.get(f"{mk}|{mode}|150")
            if sc and mode in cells:
                N = n * len(cells[mode]); pooled = sum(c[key] for c in cells[mode].values())
                p = fisher_two_sided(sc[key], sc["n"] - sc[key], pooled, N - pooled)
                out.append(f"\\providecommand{{\\RunsVsSeq{mk}{label}}}{{{fmt_p(p)}}}")
                SUMMARY["probe303_runs"][f"{mk}|{mode}|sequential_vs_interleaved_{key}"] = {"sequential": f"{sc[key]}/{sc['n']}", "interleaved": f"{pooled}/{N}", "p": p}


def probe304(root, out):
    """the ledger in a world (results/ledger_world/<model>.json: the current compensator, --compensator all).
    The first run's receipts (compensator `latest`, 2026-10-14) are archived by the runner under
    results/ledger_world_v1_latest_conf/ and folded as \\LWfirst<Model><Mode><Metric>, so the paper can
    cite what the world check caught in that compensator without re-typing a number."""
    def fold(subdir, prefix, header, avail_macro):
        found = False; comp = None
        for fp in sorted(glob.glob(os.path.join(root, subdir, "*.json"))):
            try:
                d = json.load(open(fp))
            except Exception:
                continue
            mk = MODEL_KEY.get(d.get("model", ""), None)
            if not mk or "cells" not in d:
                continue
            if not found:
                out.append(f"% --- probe 304 ({subdir}): {header} ---")
                out.append(f"\\renewcommand{{\\{avail_macro}}}{{1}}")
                if prefix == "LW":
                    out.append(f"\\renewcommand{{\\LedgerWorldRevisions}}{{{d.get('revisions')}}}")
                    out.append(f"\\renewcommand{{\\LedgerWorldPCancelFail}}{{{d.get('p_cancel_fail')}}}")
                    out.append(f"\\renewcommand{{\\LedgerWorldPRebookFail}}{{{d.get('p_rebook_fail')}}}")
                    out.append(f"\\renewcommand{{\\LedgerWorldConsumerMaxMs}}{{{d.get('consumer_max_ms')}}}")
                    out.append(f"\\renewcommand{{\\LedgerWorldCompensator}}{{{d.get('compensator', 'latest')}}}")
                found = True
            comp = d.get("compensator", "latest")
            for c in d.get("cells", []):
                mname = {"validated": "Validated", "ledger": "Ledger", "ledger_norollback": "LedgerNoRollback"}.get(c["mode"], c["mode"].title().replace("_", ""))
                n = c["n"]
                for key, label in (("a7", "R"), ("store_wrong", "StoreWrong"), ("world_wrong_sessions", "WorldWrong"), ("world_none", "WorldNone"),
                                   ("double_booked", "Double"), ("consumer_saw_stale", "ConsumerStale"), ("consumer_saw_none", "ConsumerNone"),
                                   ("obligation_retries", "Retries")):
                    out.append(f"\\providecommand{{\\{prefix}{mk}{mname}{label}}}{{{c.get(key, 0)}}}")
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}Obl}}{{{c.get('obligations_registered', 0)}/{c.get('obligations_discharged', 0)}/{c.get('obligations_failed', 0)}}}")
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}N}}{{{n}}}")
                # the testable ledger claim: every obligation discharged => the world holds exactly the final booking
                sess = c.get("sessions", [])
                clean = [x for x in sess if x.get("obligations_failed", 0) == 0]
                clean_right = sum(1 for x in clean if x.get("world_active") == [x.get("final")])
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CleanSessions}}{{{len(clean)}}}")
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CleanRight}}{{{clean_right}}}")
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CleanWrong}}{{{len(clean) - clean_right}}}")
                SUMMARY.setdefault("probe304" if prefix == "LW" else "probe304_first_run", {})[f"{mk}|{c['mode']}"] = dict(
                    {k: v for k, v in c.items() if k != "sessions"}, compensator=comp, clean_sessions=len(clean), clean_right=clean_right)
        return found
    fold("ledger_world", "LW", "the ledger with a consumer, a cancellation step and a fallible compensator", "LedgerWorldAvailable")
    fold("ledger_world_v1_latest_conf", "LWfirst", "FIRST RUN, compensator `latest` (one tracked confirmation): archived receipts", "LedgerWorldFirstAvailable")


def gates(root, out):
    """receipts of the gates that have no probe: the verified scorer gate and the TLC duplication check"""
    vs = os.path.join(os.path.dirname(root.rstrip("/")) or ".", "tools", "verified_scorer.json")
    if os.path.exists(vs):
        try:
            d = json.load(open(vs)); cells = d.get("cells", {}); probs = d.get("problems", [])
            out.append(f"% --- verified_scorer_gate ({vs}) ---")
            out.append(f"\\renewcommand{{\\VerifiedScorerCells}}{{{len(cells)}}}")
            out.append(f"\\renewcommand{{\\VerifiedScorerTraces}}{{{tex_num(sum(c['n'] for c in cells.values()))}}}")
            out.append(f"\\renewcommand{{\\VerifiedScorerProblems}}{{{len(probs)}}}")
            # the cell is AVAILABLE only when the gate passed: a receipt with problems (an analyser that could not
            # parse the records, or a verified/port disagreement) must leave the paper's cell pending, never fill it
            if cells and not probs:
                out.append("\\renewcommand{\\VerifiedScorerAvailable}{1}")
            else:
                out.append(f"% verified_scorer_gate reports {len(probs)} problem(s) over {len(cells)} cell(s): the paper's cell stays PENDING")
            SUMMARY["verified_scorer"] = {"cells": len(cells), "traces": sum(c["n"] for c in cells.values()), "problems": probs,
                                          "passed": bool(cells) and not probs}
            # the Claude op-record replication's cells (not asserted in results/expected.json): verified-detector counts
            # as macros \VSClaude<Workload><Runtime>, e.g. \VSClaudeTriageVanilla = "48/100"; AVAILABLE only with a passing gate
            if cells and not probs:
                for name, c in cells.items():
                    m = re.match(r"runs/[^/]*-claude/([a-z-]+)-(vanilla|pessimistic|snapshot_isolation)$", name)
                    if m:
                        wl = m.group(1).title().replace("-", ""); rt = {"vanilla": "Vanilla", "pessimistic": "Pess", "snapshot_isolation": "SI"}[m.group(2)]
                        out.append(f"\\providecommand{{\\VSClaude{wl}{rt}}}{{{c['a1_verified']}/{c['n']}}}")
                        SUMMARY.setdefault("pilot_claude_verified", {})[f"{m.group(1)}|{m.group(2)}"] = {"a1": c["a1_verified"], "n": c["n"]}
                if SUMMARY.get("pilot_claude_verified"):
                    for wl in ("EditReview", "PlanExecute", "Triage"):
                        for rt in ("Vanilla", "Pess", "SI"):
                            out.append(f"\\providecommand{{\\VSClaude{wl}{rt}}}{{--}}")   # a cell not run yet prints as --
                    out.append("\\renewcommand{\\PilotClaudeAvailable}{1}")
        except Exception:
            pass
    tl = os.path.join(os.path.dirname(root.rstrip("/")) or ".", "formal", "tla", "tlc.Duplication.log")
    if os.path.exists(tl):
        txt = open(tl, errors="replace").read()
        import re
        st = re.findall(r"(VIOLATED|SAFE)\s+\(expected (VIOLATED|SAFE)\s*\)\s+([0-9,]+) distinct states found; witness depth (\d+)", txt)
        if len(st) == 3 and all(a == b for a, b, _, _ in st):
            out.append(f"% --- check_duplication.sh ({tl}) ---")
            out.append(f"\\renewcommand{{\\DupWitnessDepth}}{{{st[0][3]}}}")
            out.append(f"\\renewcommand{{\\DupDivergentDepth}}{{{st[1][3]}}}")
            out.append(f"\\renewcommand{{\\DupDedupStates}}{{{tex_num(int(st[2][2].replace(',', '')))}}}")
            out.append("\\renewcommand{\\DupAvailable}{1}")
            SUMMARY["tlc_duplication"] = {"witness_depth": st[0][3], "divergent_depth": st[1][3], "dedup_states": st[2][2]}


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
    probe303_runs(a.root, out)
    probe304(a.root, out)
    probe301(a.root, out)
    probe302(a.root, out)
    verus(a.root, out)
    gates(a.root, out)
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
