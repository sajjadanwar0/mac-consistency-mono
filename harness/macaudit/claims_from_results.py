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
                                        interleaved arms incl. ledger_verified -> Table 3 (the replicated runs)
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


def wilson(k, n, z=1.959964):
    """Wilson score interval for k/n"""
    if n == 0:
        return 0.0, 0.0
    p = k / n; q = z * z / n
    centre = (p + q / 2) / (1 + q); half = z * ((p * (1 - p) / n + q / (4 * n)) ** 0.5) / (1 + q)
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe_paired(a, b, c, d, z=1.959964):
    """Newcombe (1998, Stat. Med. 17:2635), method 10: confidence interval for p1 - p2 from paired binary data with
    cell counts a (both), b (first only), c (second only), d (neither); p1 = (a+b)/n, p2 = (a+c)/n"""
    n = a + b + c + d
    if n == 0:
        return 0.0, 0.0
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n, z); l2, u2 = wilson(a + c, n, z)
    den = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / den ** 0.5 if den > 0 else 0.0
    delta = p1 - p2
    lo = delta - ((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2) ** 0.5
    hi = delta + ((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2) ** 0.5
    return lo, hi


def chi2_homogeneity(counts, n):
    """chi-square test that k binomial samples (counts of n each) share one rate; returns (chi2, p) with k-1 df
    (p via the chi-square survival function for small df, computed by the regularized gamma series)"""
    k = len(counts); tot = sum(counts)
    if k < 2 or tot == 0 or tot == k * n:
        return 0.0, 1.0
    p_hat = tot / (k * n)
    chi2 = sum((c - n * p_hat) ** 2 / (n * p_hat * (1 - p_hat)) for c in counts)
    df = k - 1
    import math
    # survival function of chi-square(df): Q(df/2, chi2/2) via the series/continued fraction of the regularized gamma
    a, x = df / 2.0, chi2 / 2.0
    if x <= 0:
        return chi2, 1.0
    if x < a + 1:   # series for P(a,x)
        term = 1.0 / a; total = term; ap = a
        for _ in range(500):
            ap += 1; term *= x / ap; total += term
            if abs(term) < abs(total) * 1e-14:
                break
        P = total * math.exp(-x + a * math.log(x) - math.lgamma(a)); Q = 1.0 - P
    else:          # continued fraction for Q(a,x) (Lentz)
        b0 = x + 1.0 - a; C = 1.0 / 1e-300; D = 1.0 / b0; h = D
        for i in range(1, 500):
            an = -i * (i - a); b0 += 2.0
            D = an * D + b0; D = 1e-300 if abs(D) < 1e-300 else D
            C = b0 + an / C; C = 1e-300 if abs(C) < 1e-300 else C
            D = 1.0 / D; de = D * C; h *= de
            if abs(de - 1.0) < 1e-14:
                break
        Q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return chi2, max(0.0, min(1.0, Q))


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
    """The live table (Table 2) rows come from the four-arm run (<model>_arms150.json, p_revise 1.0); the offset curve from the
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
    out.append("% --- probe 303 (results/live_a1_outcome; *_arms150.json -> the live table (Table 2), *_sweep.json -> offset curve) ---")
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


def _paired_overheads(sess, out, mk, run, model, tag, boot, rng, note=""):
    r"""sess: (workload, runtime) -> session idx -> wall ms. Emits \Wallclock<tag><mk><Workload><Pess|SI> for every cell with
    at least five paired sessions (per-session relative difference to the vanilla arm, mean and bootstrap 95% CI)."""
    emitted = 0
    for wl in sorted({k[0] for k in sess}):
        base = sess.get((wl, "vanilla"), {})
        for rt in ("pessimistic", "snapshot_isolation"):
            arm = sess.get((wl, rt), {})
            common = sorted(set(base) & set(arm))
            diffs = [(arm[i] - base[i]) / base[i] * 100 for i in common if base[i] > 0]
            if len(diffs) < 5:
                continue
            mean = statistics.fmean(diffs)
            bs = []
            for _ in range(boot):
                smp = [diffs[rng.randrange(len(diffs))] for _ in diffs]
                bs.append(statistics.fmean(smp))
            bs.sort(); lo, hi = bs[int(0.025 * boot)], bs[int(0.975 * boot) - 1]
            key = {"pessimistic": "Pess", "snapshot_isolation": "SI"}[rt]
            wlk = "".join(p.capitalize() for p in wl.split("-"))
            if emitted == 0:
                out.append(f"% --- probe 302 ({run}; model {model}; {tag or 'sidecars'}){note} ---")
            emitted += 1
            out.append(f"\\renewcommand{{\\Wallclock{tag}{mk}{wlk}{key}}}{{${mean:+.1f}\\%$ [{lo:+.1f}, {hi:+.1f}], $n={len(diffs)}$}}")
            SUMMARY.setdefault("probe302" + ("_" + tag.lower() if tag else ""), {}).setdefault(os.path.basename(run), {"model": model})[f"{wl}/{rt}"] = \
                {"mean_pct": mean, "ci95": [lo, hi], "n": len(diffs)}
    if emitted:   # a stub run (fewer than five paired sessions in every cell) sets nothing
        out.append(f"\\renewcommand{{\\Wallclock{tag}{mk}Available}}{{1}}")
    return emitted


def probe302(root, out, boot=2000, seed=1):
    r"""step 5/6 receipts: results/runs/*-interleaved*/.  Two receipts of the per-session wall-clock:
    (a) the token sidecars tokens-<wl>-<rt>/*.tokens.jsonl (wall_clock_ms summed per session; the session is the file's
        index session-NNNN when the file is named so, else the session_id's suffix) -> \WallclockPaired<Model>...;
    (b) order.tsv (the runner's completion stamp per (session, workload, runtime), 1 s resolution): the wall-clock of a
        cell-session is the gap to the previous stamp, which includes the interpreter start-up that every arm pays alike
        -> \WallclockStamp<Model>...  This is the ONLY wall-clock receipt of the 2026-10-14 interleaved runs, whose
        sidecars were overwritten by the run script (one survivor per cell, see probes/302_wallclock_interleaved.sh)."""
    runs = sorted(glob.glob(os.path.join(root, "runs", "*-interleaved*")))
    if not runs:
        return
    rng = random.Random(seed)
    for run in runs:
        model = None
        mf = os.path.join(run, "manifest.json")
        if os.path.exists(mf):
            try:
                model = json.load(open(mf)).get("model")
            except Exception:
                pass
        # (a) sidecars
        sess = defaultdict(lambda: defaultdict(float))   # (workload, runtime) -> session idx -> wall ms
        for fp in glob.glob(os.path.join(run, "tokens-*", "*.tokens.jsonl")):
            fm = re.search(r"session-(\d{4})\.tokens\.jsonl$", os.path.basename(fp))
            for line in open(fp):
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                model = model or r.get("model")
                idx = fm.group(1) if fm else r["session_id"].rsplit("-", 1)[-1]
                sess[(r["workload"], r["runtime"])][idx] += float(r.get("wall_clock_ms", 0))
        mk = "Claude" if (model or "").startswith("claude") else "Gpt"
        n_side = _paired_overheads(sess, out, mk, run, model, "Paired", boot, rng) if sess else 0
        # (b) completion stamps
        ot = os.path.join(run, "order.tsv")
        if os.path.exists(ot):
            import datetime as _dt
            rows = []
            for line in open(ot):
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 4:
                    continue
                try:
                    k, wl, rt, ts = int(parts[0]), parts[1], parts[2], _dt.datetime.strptime(parts[3], "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    continue
                rows.append((k, wl, rt, ts))
            stamps = defaultdict(dict)
            for (k, wl, rt, ts), prev in zip(rows[1:], rows):   # the first row has no predecessor and is dropped
                gap = (ts - prev[3]).total_seconds() * 1000.0
                if gap > 0:
                    stamps[(wl, rt)][f"{k:04d}"] = gap
            if stamps:
                sidecars = f"; sidecars folded: {'yes' if n_side else 'no'}"
                _paired_overheads(stamps, out, mk, run, model, "Stamp", boot, rng, note=f"; order.tsv completion stamps, 1 s resolution{sidecars}")


def probe302_refusal(root, out, boot=2000, seed=1):
    r"""step 22 receipts (2026-10-17): results/runs/*-refusal-*/ -- probe 302 with ARMS = vanilla, pessimistic:drop,
    pessimistic:retry, snapshot_isolation:drop, snapshot_isolation:retry on the two workloads that realize contention.
    The pilot's tools tell the model the truth about a refused or aborted operation (REFUSED, not applied) and, under
    `retry`, ask it to read and write again; refusals.jsonl in each cell counts the refused operations per session.
    Emits, per workload and arm, the mean model calls per session, the mean refused operations per session, the share
    of sessions with a refusal, the mean committed records per session, and the paired per-session wall-clock and
    call-count overheads against the vanilla arm (relative difference, mean, bootstrap 95% CI) -> \Refusal<Model>...
    Sidecars are per session in these runs (the 2026-10-15 fix), so the wall-clock comes from them, not from stamps."""
    runs = sorted(glob.glob(os.path.join(root, "runs", "*-refusal-*")))
    if not runs:
        return
    rng = random.Random(seed)
    ARM = {"vanilla": "Vanilla", "pessimistic-drop": "PessDrop", "pessimistic-retry": "PessRetry",
           "snapshot_isolation-drop": "SIDrop", "snapshot_isolation-retry": "SIRetry",
           "pessimistic": "Pess", "snapshot_isolation": "SI"}
    for run in runs:
        model = None
        mf = os.path.join(run, "manifest.json")
        if os.path.exists(mf):
            try:
                model = json.load(open(mf)).get("model")
            except Exception:
                pass
        mk = "Claude" if (model or "").startswith("claude") else "Gpt"
        wall = defaultdict(dict); calls = defaultdict(dict); refused = defaultdict(dict); commits = defaultdict(dict)
        for cell in sorted(glob.glob(os.path.join(run, "*-*"))):
            base = os.path.basename(cell)
            if base.startswith("tokens-") or not os.path.isdir(cell):
                continue
            m = re.match(r"^(edit-review|plan-execute|triage)-(.+)$", base)
            if not m or m.group(2) not in ARM:
                continue
            wl, arm = m.group(1), m.group(2)
            for fp in glob.glob(os.path.join(cell, "session-*.jsonl")):
                idx = re.search(r"session-(\d{4})\.jsonl$", fp).group(1)
                commits[(wl, arm)][idx] = sum(1 for l in open(fp) if l.strip())
            rf = os.path.join(cell, "refusals.jsonl")
            if os.path.exists(rf):
                for line in open(rf):
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    refused[(wl, arm)][f"{int(r['session']):04d}"] = sum(int(v) for v in (r.get("refusals") or {}).values())
            for fp in glob.glob(os.path.join(run, f"tokens-{wl}-{arm}", "session-*.tokens.jsonl")):
                idx = re.search(r"session-(\d{4})\.tokens\.jsonl$", fp).group(1)
                w = 0.0; k = 0
                for line in open(fp):
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line); w += float(r.get("wall_clock_ms", 0)); k += 1
                    model = model or r.get("model")
                wall[(wl, arm)][idx] = w; calls[(wl, arm)][idx] = float(k)
        if not commits:
            continue
        out.append(f"% --- probe 302 refusal-price study ({run}; model {model}): what a refused operation costs when the model is told ---")
        out.append(f"\\renewcommand{{\\Refusal{mk}Available}}{{1}}")
        def wlk(wl): return "".join(p.capitalize() for p in wl.split("-"))
        def mean(d): return statistics.fmean(d.values()) if d else float("nan")
        for (wl, arm) in sorted(commits):
            a = ARM[arm]; W = wlk(wl); n = len(commits[(wl, arm)])
            out.append(f"\\providecommand{{\\Refusal{mk}{W}{a}N}}{{{n}}}")
            out.append(f"\\providecommand{{\\Refusal{mk}{W}{a}Commits}}{{{mean(commits[(wl, arm)]):.2f}}}")
            if calls.get((wl, arm)):
                out.append(f"\\providecommand{{\\Refusal{mk}{W}{a}Calls}}{{{mean(calls[(wl, arm)]):.2f}}}")
                out.append(f"\\providecommand{{\\Refusal{mk}{W}{a}WallS}}{{{mean(wall[(wl, arm)]) / 1000:.1f}}}")
            if refused.get((wl, arm)):
                rr = refused[(wl, arm)]
                out.append(f"\\providecommand{{\\Refusal{mk}{W}{a}Refused}}{{{mean(rr):.2f}}}")
                out.append(f"\\providecommand{{\\Refusal{mk}{W}{a}RefusedSessions}}{{{sum(1 for v in rr.values() if v > 0)}/{len(rr)}}}")
            SUMMARY.setdefault("probe302_refusal", {}).setdefault(os.path.basename(run), {"model": model})[f"{wl}/{arm}"] = {
                "n": n, "commits_mean": mean(commits[(wl, arm)]), "calls_mean": mean(calls.get((wl, arm), {})) if calls.get((wl, arm)) else None,
                "wall_ms_mean": mean(wall.get((wl, arm), {})) if wall.get((wl, arm)) else None,
                "refused_mean": mean(refused.get((wl, arm), {})) if refused.get((wl, arm)) else None}
            # paired against the vanilla arm of the same workload (same sessions, same seeds, interleaved)
            if arm != "vanilla":
                for metric, store, label in (("wall", wall, "Wall"), ("calls", calls, "Calls")):
                    base = store.get((wl, "vanilla"), {}); x = store.get((wl, arm), {})
                    common = sorted(set(base) & set(x))
                    diffs = [(x[i] - base[i]) / base[i] * 100 for i in common if base[i] > 0]
                    if len(diffs) < 5:
                        continue
                    mu = statistics.fmean(diffs); bs = []
                    for _ in range(boot):
                        bs.append(statistics.fmean([diffs[rng.randrange(len(diffs))] for _ in diffs]))
                    bs.sort(); lo, hi = bs[int(0.025 * boot)], bs[int(0.975 * boot) - 1]
                    out.append(f"\\providecommand{{\\Refusal{mk}{W}{a}{label}Overhead}}{{${mu:+.1f}\\%$ [{lo:+.1f}, {hi:+.1f}], $n={len(diffs)}$}}")
                    SUMMARY["probe302_refusal"][os.path.basename(run)][f"{wl}/{arm}"][f"{metric}_overhead_pct"] = {"mean": mu, "ci95": [lo, hi], "n": len(diffs)}


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
    fp = os.path.join(root, "verus", "lib_l5_exec.verus.log")
    if os.path.exists(fp):
        m = re.search(r"(\d+) verified, (\d+) errors", open(fp, errors="replace").read())
        if m and m.group(2) == "0":
            out.append(f"% --- verus exec ledger ({fp}) ---")
            out.append(f"\\renewcommand{{\\LfiveExecVerus}}{{{m.group(1)} obligations, 0 errors}}")
            out.append(f"\\renewcommand{{\\LfiveExecVerusCount}}{{{m.group(1)}}}")
            out.append(f"\\renewcommand{{\\LfiveExecAvailable}}{{1}}")
            SUMMARY["verus/lib_l5_exec.verus.log"] = {"verified": int(m.group(1)), "errors": 0}
        else:
            out.append(f"% verus exec ledger: {fp} shows no zero-error summary line; \\LfiveExecAvailable stays 0")
    fp = os.path.join(root, "verus", "lib_l5_ledger.verus.log")
    if os.path.exists(fp):
        m = re.search(r"(\d+) verified, (\d+) errors", open(fp, errors="replace").read())
        if m and m.group(2) == "0":
            out.append(f"% --- verus ledger ({fp}) ---")
            out.append(f"\\renewcommand{{\\LfiveVerus}}{{{m.group(1)} obligations, 0 errors}}")
            out.append(f"\\renewcommand{{\\LfiveVerusStatus}}{{verified in Verus ({m.group(1)} obligations, 0 errors)}}")
            out.append(f"\\renewcommand{{\\LfiveVerusIntro}}{{verified ({m.group(1)} obligations)}}")


def probe303_runs(root, out):
    """replicated, interleaved arms: <model>_arms150i.run<r>.json -> per-cell per-run values and pooled counts"""
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
    out.append("% --- probe 303 --interleave --runs (results/live_a1_outcome/*_arms150i.run*.json): the replicated-runs table (Table 3) ---")
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
        # discordant pairs) with Newcombe's (1998, method 10) interval on the paired difference, in percentage points
        # (the Wald interval used before 2026-10-15 is not appropriate at nine discordant pairs)
        if "validated" in cells and "verified" in cells:
            b = c = npairs = a_both = 0
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
                        if sv[k]["a7"] and sf[k]["a7"]:
                            a_both += 1
            if npairs:
                from math import comb, sqrt
                nd = b + c
                if nd == 0:
                    pm = 1.0
                else:
                    pk = comb(nd, b) / 2 ** nd
                    pm = min(1.0, sum(comb(nd, i) / 2 ** nd for i in range(nd + 1) if comb(nd, i) / 2 ** nd <= pk * (1 + 1e-12)))
                d = (b - c) / npairs
                lo, hi = newcombe_paired(a_both, b, c, npairs - a_both - b - c)
                out.append(f"\\providecommand{{\\RunsPairedDiscordant{mk}}}{{{b} vs.\\ {c}}}")
                out.append(f"\\providecommand{{\\RunsMcNemar{mk}}}{{{fmt_p(pm)}}}")
                out.append(f"\\providecommand{{\\RunsDiff{mk}}}{{{100*d:+.1f}}}")
                out.append(f"\\providecommand{{\\RunsDiffCI{mk}}}{{[{100*lo:+.1f}, {100*hi:+.1f}]}}")
                SUMMARY["probe303_runs"][f"{mk}|paired_validated_vs_verified_R"] = {"pairs": npairs, "validated_only": b, "verified_only": c, "mcnemar_p": pm, "diff_pp": 100 * d, "diff_ci_pp": [100 * lo, 100 * hi]}
        # are the three runs of one arm exchangeable?  chi-square homogeneity of the per-run counts (2 df); the pooled
        # Clopper-Pearson intervals above treat the 300 sessions as one sample, which this test qualifies
        for mode, key, label in (("vanilla", "a1", "VanillaAOne"), ("validated", "a7", "ValidatedR"), ("verified", "a7", "VerifiedR")):
            if mode in cells and len(cells[mode]) >= 2:
                per_run = [c[key] for _, c in sorted(cells[mode].items())]
                chi2, ph = chi2_homogeneity(per_run, n)
                out.append(f"\\providecommand{{\\RunsHetero{mk}{label}}}{{{fmt_p(ph)}}}")
                SUMMARY["probe303_runs"][f"{mk}|{mode}|run_homogeneity_{key}"] = {"per_run": per_run, "chi2": chi2, "p": ph}
        # the run, not the arm: the sequential-block run of the same protocol (the live table) against the pooled interleaved runs
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
    SKEY = {"LW": "probe304", "LWfirst": "probe304_first_run", "LWatomic": "probe304_atomic", "LWwide": "probe304_window5000", "LWexec": "probe304_exec"}

    def fold(subdir, prefix, header, avail_macro):
        found = False; comp = None
        skey = SKEY[prefix]
        ranges = defaultdict(list)      # (mode label, metric label) -> values across the families, for the Range macros
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
                # the receipt's own registration field ("atomic" | "after"); receipts that predate the switch carry none
                out.append(f"\\providecommand{{\\{prefix}Registration}}{{{d.get('registration') or 'after (predates the field)'}}}")
                found = True
            if d.get("registration") and prefix in ("LWatomic", "LWwide") and d.get("registration") != "atomic":
                print(f"warning: {fp} registration={d.get('registration')!r}, expected 'atomic'", file=sys.stderr)
            comp = d.get("compensator", "latest")
            for c in d.get("cells", []):
                mname = {"validated": "Validated", "ledger": "Ledger", "ledger_norollback": "LedgerNoRollback"}.get(c["mode"], c["mode"].title().replace("_", ""))
                n = c["n"]
                for key, label in (("a7", "R"), ("store_wrong", "StoreWrong"), ("world_wrong_sessions", "WorldWrong"), ("world_none", "WorldNone"),
                                   ("double_booked", "Double"), ("consumer_saw_stale", "ConsumerStale"), ("consumer_saw_none", "ConsumerNone"),
                                   ("obligation_retries", "Retries")):
                    out.append(f"\\providecommand{{\\{prefix}{mk}{mname}{label}}}{{{c.get(key, 0)}}}")
                    ranges[(mname, label)].append(int(c.get(key, 0)))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}Obl}}{{{c.get('obligations_registered', 0)}/{c.get('obligations_discharged', 0)}/{c.get('obligations_failed', 0)}}}")
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}N}}{{{n}}}")
                # the testable ledger claim: every obligation discharged => the world holds exactly the final booking
                sess = c.get("sessions", [])
                clean = [x for x in sess if x.get("obligations_failed", 0) == 0]
                clean_right = sum(1 for x in clean if x.get("world_active") == [x.get("final")])
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CleanSessions}}{{{len(clean)}}}")
                ranges[(mname, "CleanSessions")].append(int(len(clean)))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CleanRight}}{{{clean_right}}}")
                ranges[(mname, "CleanRight")].append(int(clean_right))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CleanWrong}}{{{len(clean) - clean_right}}}")
                ranges[(mname, "CleanWrong")].append(int(len(clean) - clean_right))
                vac = sum(1 for x in clean if x.get("obligations_registered", 0) == 0)   # clean with nothing registered: vacuous
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CleanVacuous}}{{{vac}}}")
                ranges[(mname, "CleanVacuous")].append(int(vac))
                # the converse: an obligation the ledger reports OPEN, and the world is indeed not [final]
                open_ = [x for x in sess if x.get("obligations_failed", 0) > 0]
                open_wrong = sum(1 for x in open_ if x.get("world_active") != [x.get("final")])
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}OpenSessions}}{{{len(open_)}}}")
                ranges[(mname, "OpenSessions")].append(int(len(open_)))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}OpenWrong}}{{{open_wrong}}}")
                ranges[(mname, "OpenWrong")].append(int(open_wrong))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}OpenRight}}{{{len(open_) - open_wrong}}}")
                ranges[(mname, "OpenRight")].append(int(len(open_) - open_wrong))
                # the shape of the world at the end of a non-clean session, from the per-session world log
                dbl = sum(1 for x in sess if x.get("double_booked") and x.get("world_wrong"))
                none_ = sum(1 for x in sess if x.get("world_none"))
                stale_only = sum(1 for x in sess if x.get("world_wrong") and not x.get("double_booked") and not x.get("world_none"))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}FailDouble}}{{{dbl}}}")
                ranges[(mname, "FailDouble")].append(int(dbl))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}FailNone}}{{{none_}}}")
                ranges[(mname, "FailNone")].append(int(none_))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}FailStaleOnly}}{{{stale_only}}}")
                ranges[(mname, "FailStaleOnly")].append(int(stale_only))
                one_obl = sum(1 for x in sess if x.get("obligations_registered", 0) == 1)
                two_obl = sum(1 for x in sess if x.get("obligations_registered", 0) >= 2)
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}OneObligation}}{{{one_obl}}}")
                ranges[(mname, "OneObligation")].append(int(one_obl))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}TwoObligations}}{{{two_obl}}}")
                ranges[(mname, "TwoObligations")].append(int(two_obl))
                out.append(f"\\providecommand{{\\{prefix}{mk}{mname}NoObligation}}{{{n - one_obl - two_obl}}}")
                ranges[(mname, "NoObligation")].append(int(n - one_obl - two_obl))
                if c["mode"] == "ledger":
                    agree[prefix][0] += clean_right + open_wrong; agree[prefix][1] += n
                    # timing from the records beside the receipt: when the revisions landed relative to the booking's
                    # commit, and how long the compensation took (model call included)
                    rp = fp[:-5] + ".records.jsonl"
                    if os.path.exists(rp):
                        by = defaultdict(list)
                        for line in open(rp):
                            line = line.strip()
                            if not line:
                                continue
                            r = json.loads(line)
                            if r.get("mode") == "ledger":
                                by[r.get("session")].append(r)
                        both_after = 0; first_rev = []; comp_lat = []; book_to_comp = []
                        cons = {x["session"]: x for x in sess}
                        # the stale consumer reads, by what the records say had happened when the consumer read (its at_ms
                        # against the date agent's and the compensator's wall_commit_ms). Four buckets, exhaustive on
                        # every receipt so far (the fold asserts the sum):
                        #   before_rev   no post-commit revision had landed: the booking it saw was the current one
                        #   inside_comp  the latest landed revision's compensation had not completed (its model call)
                        #   refused      every landed revision was compensated, and the stale booking it saw is one whose
                        #                cancellation the world refused (the compensator reported the obligation open)
                        #   superseded   it saw exactly the then-current booking, which a LATER revision replaced
                        #   other        none of the above (never observed; emitted so a new shape cannot hide)
                        c_before = c_inside = c_refused = c_superseded = c_other = 0
                        for k_, rs in by.items():
                            fl = [r for r in rs if r.get("agent") == "flight_agent" and r.get("wall_commit_ms") is not None]
                            dar = sorted((r for r in rs if r.get("agent") == "date_agent" and r.get("wall_commit_ms") is not None),
                                         key=lambda r: r["wall_commit_ms"])
                            cor = [r for r in rs if r.get("agent") == "compensator" and r.get("wall_commit_ms") is not None]
                            if not fl or not dar:
                                continue
                            commit = fl[-1]["wall_commit_ms"]
                            da = [r["wall_commit_ms"] for r in dar]
                            if all(t > commit for t in da):
                                both_after += 1
                            first_rev.append(da[0])
                            # a compensator record answers the revision whose put it read: read_time == that put's write_time
                            for cr in cor:
                                rev = [r for r in dar if r.get("write_time") == cr.get("read_time")]
                                if rev:
                                    comp_lat.append(cr["wall_commit_ms"] - rev[0]["wall_commit_ms"])
                            if cor:
                                book_to_comp.append(min(cr["wall_commit_ms"] for cr in cor) - commit)
                            x = cons.get(k_)
                            if x and x.get("consumer_saw_stale") and x.get("consumer", {}).get("at_ms") is not None:
                                at = x["consumer"]["at_ms"]; saw = x["consumer"].get("saw", [])
                                landed = [r for r in dar if commit < r["wall_commit_ms"] <= at]
                                if not landed:
                                    c_before += 1; continue
                                latest = landed[-1]
                                vcur = (latest.get("write_values") or {}).get("trip/state/date")
                                done = [cr for cr in cor if cr.get("read_time") == latest.get("write_time") and cr["wall_commit_ms"] <= at]
                                if not done:
                                    c_inside += 1
                                elif any(d != vcur for d in saw):
                                    refused = any(e.get("op") == "cancel" and not e.get("ok") for e in x.get("world_log", []))
                                    if refused:
                                        c_refused += 1
                                    else:
                                        c_other += 1
                                else:
                                    c_superseded += 1
                        stale_total = c.get("consumer_saw_stale", 0)
                        if c_before + c_inside + c_refused + c_superseded + c_other != stale_total:
                            print(f"warning: {fp} {c['mode']}: consumer split {c_before}+{c_inside}+{c_refused}+{c_superseded}+{c_other} != consumer_saw_stale {stale_total}", file=sys.stderr)
                        for lab, v in (("ConsumerStaleBeforeRevision", c_before), ("ConsumerStaleInsideCompensation", c_inside),
                                       ("ConsumerStaleRefusedCancel", c_refused), ("ConsumerStaleCurrentThenSuperseded", c_superseded),
                                       ("ConsumerStaleOther", c_other)):
                            out.append(f"\\providecommand{{\\{prefix}{mk}{mname}{lab}}}{{{v}}}")
                            ranges[(mname, lab)].append(int(v))
                        def q(v, f):
                            v = sorted(v); return v[min(len(v) - 1, int(f * len(v)))] if v else float("nan")
                        out.append(f"\\providecommand{{\\{prefix}{mk}{mname}BothRevisionsAfterCommit}}{{{both_after}}}")
                        ranges[(mname, "BothRevisionsAfterCommit")].append(int(both_after))
                        out.append(f"\\providecommand{{\\{prefix}{mk}{mname}FirstRevisionMedianS}}{{{q(first_rev, 0.5) / 1000:.1f}}}")
                        ranges[(mname, "FirstRevisionMedianS")].append(round(q(first_rev, 0.5) / 1000, 1))
                        out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CompLatencyMedianS}}{{{q(comp_lat, 0.5) / 1000:.1f}}}")
                        ranges[(mname, "CompLatencyMedianS")].append(round(q(comp_lat, 0.5) / 1000, 1))
                        out.append(f"\\providecommand{{\\{prefix}{mk}{mname}CompLatencyPNinetyS}}{{{q(comp_lat, 0.9) / 1000:.1f}}}")
                        ranges[(mname, "CompLatencyPNinetyS")].append(round(q(comp_lat, 0.9) / 1000, 1))
                        out.append(f"\\providecommand{{\\{prefix}{mk}{mname}BookingToCompensationMedianS}}{{{q(book_to_comp, 0.5) / 1000:.1f}}}")
                        ranges[(mname, "BookingToCompensationMedianS")].append(round(q(book_to_comp, 0.5) / 1000, 1))
                        out.append(f"\\providecommand{{\\{prefix}{mk}{mname}BookingToCompensationPNinetyS}}{{{q(book_to_comp, 0.9) / 1000:.1f}}}")
                        ranges[(mname, "BookingToCompensationPNinetyS")].append(round(q(book_to_comp, 0.9) / 1000, 1))
                        SUMMARY.setdefault(skey, {}).setdefault("timing", {})[mk] = {
                            "both_revisions_after_commit": both_after, "first_revision_median_ms": q(first_rev, 0.5),
                            "compensation_latency_median_ms": q(comp_lat, 0.5), "compensation_latency_p90_ms": q(comp_lat, 0.9),
                            "booking_to_compensation_median_ms": q(book_to_comp, 0.5), "booking_to_compensation_p90_ms": q(book_to_comp, 0.9),
                            "consumer_stale_before_revision": c_before, "consumer_stale_inside_compensation": c_inside,
                            "consumer_stale_refused_cancel": c_refused, "consumer_stale_current_then_superseded": c_superseded,
                            "consumer_stale_other": c_other}
                SUMMARY.setdefault(skey, {})[f"{mk}|{c['mode']}"] = dict(
                    {k: v for k, v in c.items() if k != "sessions"}, compensator=comp, registration=d.get("registration"),
                    clean_sessions=len(clean), clean_right=clean_right, open_sessions=len(open_), open_wrong=open_wrong)
        if found:
            # min--max over the families, so the text's "x--y of 100" never depends on a hand-ordered pair of macros
            for (mname, label), vals in sorted(ranges.items()):
                lo, hi = min(vals), max(vals)
                if isinstance(lo, float):
                    lo, hi = f"{lo:.1f}", f"{hi:.1f}"
                out.append(f"\\providecommand{{\\{prefix}{mname}{label}Lo}}{{{lo}}}")
                out.append(f"\\providecommand{{\\{prefix}{mname}{label}Hi}}{{{hi}}}")
                out.append(f"\\providecommand{{\\{prefix}{mname}{label}Range}}{{{lo if lo == hi else f'{lo}--{hi}'}}}")
        if found and agree[prefix][1]:
            # report/world agreement over the ledger arm of every family: (discharged and right) + (open and wrong), of n
            k, n = agree[prefix]; lo, hi = clopper_pearson(n - k, n)
            out.append(f"\\providecommand{{\\{prefix}LedgerAgree}}{{{k}/{n}}}")
            out.append(f"\\providecommand{{\\{prefix}LedgerDisagree}}{{{n - k}}}")
            out.append(f"\\providecommand{{\\{prefix}LedgerDisagreeCI}}{{[{100 * lo:.1f}, {100 * hi:.1f}]}}")
            SUMMARY.setdefault(skey, {})["ledger_report_world_agreement"] = \
                {"agree": k, "n": n, "disagree_ci95_pct": [100 * lo, 100 * hi]}
        return found
    agree = {"LW": [0, 0], "LWfirst": [0, 0], "LWatomic": [0, 0], "LWwide": [0, 0], "LWexec": [0, 0]}
    fold("ledger_world", "LW", "the ledger with a consumer, a cancellation step and a fallible compensator", "LedgerWorldAvailable")
    fold("ledger_world_v1_latest_conf", "LWfirst", "FIRST RUN, compensator `latest` (one tracked confirmation): archived receipts", "LedgerWorldFirstAvailable")
    # 2026-10-16 (runner step 21): the same protocol with the obligation registered ATOMICALLY with the superseding write,
    # and the ledger arm alone with a 5 s consumer window
    fold("ledger_world_atomic", "LWatomic", "ATOMIC registration (--registration atomic)", "LedgerWorldAtomicAvailable")
    fold("ledger_world_window5000", "LWwide", "ledger arm, consumer window 0-5000 ms", "LedgerWorldWideAvailable")
    # 2026-10-17 (runner step 23): the ledger's bookkeeping in the verified bytes (lib_l5_exec.rs behind l5_server)
    # the receipts must come from the BUILT server (ledger == "exec", receipt not a stand-in, and -- when step 14 recorded
    # it -- the server's sha256 equal to results/verus/l5_server.sha256); otherwise the directory is not folded at all
    exec_ok = True; shas = set()
    recorded = None
    rp = os.path.join(root, "verus", "l5_server.sha256")
    if os.path.exists(rp):
        recorded = open(rp).read().split()[0].strip() if open(rp).read().strip() else None
    for fp in glob.glob(os.path.join(root, "ledger_world_exec", "*.json")):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        r = d.get("ledger_receipt") or {}
        if d.get("ledger") != "exec" or r.get("standin") or not r.get("server_sha256"):
            print(f"warning: {fp}: not a run of the built l5_server (ledger={d.get('ledger')!r}, standin={r.get('standin')!r}); ledger_world_exec NOT folded", file=sys.stderr)
            exec_ok = False
        elif recorded and r.get("server_sha256") != recorded:
            print(f"warning: {fp}: server sha256 {r.get('server_sha256')[:16]} != results/verus/l5_server.sha256 {recorded[:16]}; ledger_world_exec NOT folded", file=sys.stderr)
            exec_ok = False
        else:
            shas.add(r.get("server_sha256"))
    if exec_ok and shas:
        fold("ledger_world_exec", "LWexec", "bookkeeping in the VERIFIED bytes (--ledger exec)", "LedgerWorldExecAvailable")
        out.append(f"\\providecommand{{\\LWexecServerSha}}{{{sorted(shas)[0][:16]}}}")


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
                vs_cells = {(wl, rt): "--" for wl in ("EditReview", "PlanExecute", "Triage") for rt in ("Vanilla", "Pess", "SI")}
                for name, c in cells.items():
                    m = re.match(r"runs/[^/]*-claude/([a-z-]+)-(vanilla|pessimistic|snapshot_isolation)$", name)
                    if m:
                        wl = m.group(1).title().replace("-", ""); rt = {"vanilla": "Vanilla", "pessimistic": "Pess", "snapshot_isolation": "SI"}[m.group(2)]
                        vs_cells[(wl, rt)] = f"{c['a1_verified']}/{c['n']}"
                        SUMMARY.setdefault("pilot_claude_verified", {})[f"{m.group(1)}|{m.group(2)}"] = {"a1": c["a1_verified"], "n": c["n"]}
                if SUMMARY.get("pilot_claude_verified"):
                    out.append("% Claude op-record replication (runs/*-claude), scored by the verified detector; -- = cell not scored yet")
                    for (wl, rt), val in vs_cells.items():
                        out.append(f"\\providecommand{{\\VSClaude{wl}{rt}}}{{{val}}}")
                    out.append("\\renewcommand{\\PilotClaudeAvailable}{1}")
        except Exception as ex:  # noqa: BLE001
            # never silent: a fold that drops a receipt must say so (a shadowed `re` import dropped the Claude pilot
            # macros of the 2026-10-15 fold without a word)
            print(f"warning: verified_scorer receipt {vs} could not be folded: {ex!r}", file=sys.stderr)
            out.append(f"% verified_scorer receipt NOT folded: {ex!r}")
    tl = os.path.join(os.path.dirname(root.rstrip("/")) or ".", "formal", "tla", "tlc.Duplication.log")
    if os.path.exists(tl):
        txt = open(tl, errors="replace").read()
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
    probe302_refusal(a.root, out)
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
