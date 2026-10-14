#!/usr/bin/env python3
"""wallclock_table.py -- the real-store wall-clock table of the cost study (main paper Sec. 6.7),
regenerated from its receipt results/python_loose/realstore_wallclock.json (probe 141,
realstore_metrics.py --check, run 20260913T0150Z and its Claude replication).  Prints a LaTeX
table body for the supplement (Appendix O) so that every wall-clock figure the main text quotes has a
visible receipt: per-cell mean/median seconds and model calls per session, the per-session overhead
vs. vanilla with its bootstrap 95% CI and Holm-corrected permutation p, whether the cell is outside the
run's null band (plan-execute drift), and for gpt-4o the per-sound-commit overhead.

    python3 harness/macaudit/wallclock_table.py --receipt results/python_loose/realstore_wallclock.json --tex
"""
from __future__ import annotations
import argparse, json, sys

ORDER = [("edit-review", "edit-review"), ("plan-execute", "plan-execute"), ("triage", "triage")]
RT = [("vanilla", "vanilla"), ("pessimistic", "pessimistic"), ("snapshot_isolation", "SI")]


def pct(x):
    return f"{100 * x:+.1f}\\%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", default="results/python_loose/realstore_wallclock.json")
    ap.add_argument("--tex", action="store_true")
    a = ap.parse_args()
    d = json.load(open(a.receipt))
    out = []
    for model in ("gpt-4o", "claude-sonnet-4-5"):
        r = d["runs"].get(model)
        if not r:
            continue
        nb = r["null_band"]["value"]
        out.append(f"% --- {model}: null band {100*nb:.1f}% ({r['null_band']['basis']}) ---")
        out.append("\\midrule")
        out.append(f"\\multicolumn{{8}}{{@{{}}l}}{{\\emph{{{model}}}; null band (plan-execute drift) ${100*nb:.1f}\\%$}} \\\\")
        for wl, wln in ORDER:
            for rt, rtn in RT:
                c = r["cells"].get(f"{wl}-{rt}")
                if not c:
                    continue
                o = r["overheads"].get(f"{wl}-{rt}")
                if o is None:
                    out.append(f"{wln} & {rtn} & {c['mean']:.2f} & {c['median']:.2f} & {c['calls_per_session']:.2f} & --- & --- & --- \\\\")
                else:
                    lo, hi = o["ci95"]
                    band = "outside" if o["outside_null_band"] else "inside"
                    ps = f"{pct(o['per_sound_commit'])} [{100*o['per_sound_commit_ci95'][0]:+.1f}, {100*o['per_sound_commit_ci95'][1]:+.1f}]" if "per_sound_commit" in o else "---"
                    out.append(f"{wln} & {rtn} & {c['mean']:.2f} & {c['median']:.2f} & {c['calls_per_session']:.2f} & {pct(o['per_session'])} [{100*lo:+.1f}, {100*hi:+.1f}], $p_{{\\mathrm{{Holm}}}}={o['p_holm']:.3f}$, {band} & {ps} \\\\")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
