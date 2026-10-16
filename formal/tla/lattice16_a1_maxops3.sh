#!/usr/bin/env bash
# =====================================================================
# lattice16_a1_maxops3.sh -- the sixteen NoA1 points of the matrix at
# MaxOps=3, Values={v1,v2}, Cells={c1,c2}: the bounds at which the
# SUPERSESSION class of A1 (a non-NULL stale read; supplement S L) is
# reachable in the unguarded runtime.
#
# WHY THIS EXISTS.  lattice16.sh (MaxOps=2, one value) and lattice16_v2.sh
# (MaxOps=2, two values) establish G1's safety where the only reachable
# A1 witness is the cold-start (NULL-read) one; the live study's witnesses
# are supersessions, which need a seeding write, a superseding write and
# the reader's commit -- three log entries.  Until this script ran, the
# safety half had not been checked at a bound where that class exists.
#
# Expect eight SAFE (G1=TRUE, exhaustive) and eight WITNESS (G1=FALSE).
#   ./lattice16_a1_maxops3.sh                     # TLA_TOOLS=... TLC_HEAP=5g TLC_WORKERS=2 TLC_TIMEOUT=7200
# Writes lattice16_a1_maxops3_results.{tsv,json}; exits non-zero on any
# mismatch or timeout, like lattice16.sh.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
JAR="${TLA_TOOLS:-}"
if [ -z "$JAR" ]; then for c in ../../tools/tla2tools.jar tla2tools.jar "$HOME/tla2tools.jar"; do [ -f "$c" ] && { JAR="$c"; break; }; done; fi
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found (TLA_TOOLS=...)" >&2; exit 1; }
JAR="$(cd "$(dirname "$JAR")" && pwd)/$(basename "$JAR")"     # TLC runs inside the runs directory
HEAP="${TLC_HEAP:-5g}"; WORKERS="${TLC_WORKERS:-auto}"; TMO="${TLC_TIMEOUT:-7200}"
ONLY="${ONLY:-}"   # optional: run one tag only (ONLY=class: only the witness-class pair, appended to the results)
# CELLS=1 restricts the universe to Cells={c1}: the supersession witness (seed write, superseding write, reader's
# commit on ONE cell) is reachable there and the exhaustive G1=TRUE runs close; at Cells={c1,c2} the same runs
# passed 70M distinct states in 25 minutes on two cores without closing (2026-10-15; log committed as
# lattice16_a1_maxops3_c2_attempt.log), so the two-cell universe is left to a longer run (CELLS=2).  A one-cell
# safety verdict covers the one-cell universe only; the paper says so.
CELLS="${CELLS:-1}"
SUFFIX="M3V2C$CELLS"
D="lattice16_a1_maxops3_c${CELLS}_runs"; mkdir -p "$D" && cp Memory.tla Anomalies.tla "$D"/
OUT="lattice16_a1_maxops3_c${CELLS}_results"
[ -n "$ONLY" ] || : > "$OUT.tsv"
for g1 in FALSE TRUE; do for g2 in FALSE TRUE; do for g3 in FALSE TRUE; do for g6 in FALSE TRUE; do
  tag="G1${g1:0:1}_G2${g2:0:1}_G3${g3:0:1}_G6${g6:0:1}_NoA1_$SUFFIX"
  [ -z "$ONLY" ] || [ "$ONLY" = "$tag" ] || continue
  python3 mkcfg.py $g1 $g2 $g3 $g6 NoA1 | sed 's/Values = {v1}/Values = {v1, v2}/; s/MaxOps = 2/MaxOps = 3/' > "$D/$tag.cfg"
  [ "$CELLS" = 1 ] && sed -i 's/Cells = {c1, c2}/Cells = {c1}/' "$D/$tag.cfg"
  grep -q "Values = {v1, v2}" "$D/$tag.cfg" && grep -q "MaxOps = 3" "$D/$tag.cfg" || { echo "FAIL: cfg not widened" >&2; exit 1; }
  if [ "$CELLS" = 1 ]; then grep -q "Cells = {c1}" "$D/$tag.cfg" || { echo "FAIL: cfg not restricted to one cell" >&2; exit 1; }; fi
  cp Guarded.tla "$D/$tag.tla"; sed -i "s/MODULE Guarded/MODULE $tag/" "$D/$tag.tla"
  t0=$(date +%s)
  ( cd "$D" && timeout "$TMO" java -XX:+UseParallelGC -Xmx"$HEAP" -cp "$JAR" tlc2.TLC -workers "$WORKERS" -deadlock \
      -config "$tag.cfg" "$tag.tla" > "$tag.log" 2>&1 ) || true
  secs=$(( $(date +%s) - t0 ))
  if grep -q "No error has been found" "$D/$tag.log"; then out=SAFE
  elif grep -q "is violated" "$D/$tag.log"; then out=WITNESS
  else out=TIMEOUT_OR_ERROR; fi
  exp=$([ "$g1" = TRUE ] && echo SAFE || echo WITNESS)
  states=$( { grep -oE "[0-9,]+ distinct states found" "$D/$tag.log" || true; } | tail -1 | tr -d ',' | cut -d' ' -f1)
  depth=$( { grep -oE "depth of the complete state graph search is [0-9]+" "$D/$tag.log" || true; } | { grep -oE "[0-9]+$" || true; } | tail -1)
  ok=$([ "$out" = "$exp" ] && echo ok || echo MISMATCH)
  printf "%s\t%s\t%s\t%s\tNoA1\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$g1" "$g2" "$g3" "$g6" "$exp" "$out" "${states:-?}" "${depth:-?}" "$secs" "$ok" "$tag" >> "$OUT.tsv"
  echo "$tag expected=$exp got=$out states=${states:-?} depth=${depth:-?} ${secs}s $ok"
  rm -rf "$D/states"
done; done; done; done
# The witness CLASS: NoA1 fires on cold-start (NULL-read) witnesses too, so one more pair of runs decides whether the
# supersession class -- a non-NULL stale read superseded by a different non-NULL value -- is reachable in this universe
# without G1 (expected: violated) and excluded with it (expected: safe).  The invariant is appended to the per-run copy
# of Guarded.tla; Guarded.tla itself is untouched.
if [ -z "$ONLY" ] || [ "$ONLY" = class ]; then     # ONLY=class: just this pair, appended to the existing results
  for g1 in FALSE TRUE; do
    tag="G1${g1:0:1}_G2F_G3F_G6F_NoA1NonNull_$SUFFIX"
    python3 mkcfg.py $g1 FALSE FALSE FALSE NoA1NonNull | sed 's/Values = {v1}/Values = {v1, v2}/; s/MaxOps = 2/MaxOps = 3/' > "$D/$tag.cfg"
    [ "$CELLS" = 1 ] && sed -i 's/Cells = {c1, c2}/Cells = {c1}/' "$D/$tag.cfg"
    cp Guarded.tla "$D/$tag.tla"; sed -i "s/MODULE Guarded/MODULE $tag/" "$D/$tag.tla"
    python3 - "$D/$tag.tla" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
extra = """
(* the supersession class of StaleGeneration: the stale read observed a real value, not the initial sentinel *)
StaleGenerationNonNull(h) ==
    \\E i, j \\in 1..Len(h) :
        /\\ i # j
        /\\ h[i].agent # h[j].agent
        /\\ \\E c \\in h[i].read_set \\cap h[j].write_set :
            /\\ h[i].read_time  < h[j].write_time
            /\\ h[j].write_time < h[i].write_time
            /\\ h[i].read_values[c] # h[j].write_values[c]
            /\\ h[i].read_values[c] # NULL
NoA1NonNull == ~StaleGenerationNonNull(log)
"""
i = s.rfind("\n====") + 1          # the module's closing line, as a whole line
open(p, "w").write(s[:i] + extra + s[i:])
PY
    t0=$(date +%s)
    ( cd "$D" && timeout "$TMO" java -XX:+UseParallelGC -Xmx"$HEAP" -cp "$JAR" tlc2.TLC -workers "$WORKERS" -deadlock \
        -config "$tag.cfg" "$tag.tla" > "$tag.log" 2>&1 ) || true
    secs=$(( $(date +%s) - t0 ))
    if grep -q "No error has been found" "$D/$tag.log"; then out=SAFE
    elif grep -q "is violated" "$D/$tag.log"; then out=WITNESS
    else out=TIMEOUT_OR_ERROR; fi
    exp=$([ "$g1" = TRUE ] && echo SAFE || echo WITNESS)
    states=$( { grep -oE "[0-9,]+ distinct states found" "$D/$tag.log" || true; } | tail -1 | tr -d ',' | cut -d' ' -f1)
    depth=$( { grep -oE "depth of the complete state graph search is [0-9]+" "$D/$tag.log" || true; } | { grep -oE "[0-9]+$" || true; } | tail -1)
    ok=$([ "$out" = "$exp" ] && echo ok || echo MISMATCH)
    printf "%s\tFALSE\tFALSE\tFALSE\tNoA1NonNull\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$g1" "$exp" "$out" "${states:-?}" "${depth:-?}" "$secs" "$ok" "$tag" >> "$OUT.tsv"
    echo "$tag expected=$exp got=$out states=${states:-?} depth=${depth:-?} ${secs}s $ok"
    rm -rf "$D/states"
  done
fi
CELLS="$CELLS" OUT="$OUT" python3 - <<'PY'
import json, os
cells = os.environ["CELLS"]; out = os.environ["OUT"]
rows=[l.rstrip('\n').split('\t') for l in open(out + '.tsv')]
res=[dict(zip(["G1","G2","G3","G6","invariant","expected","result","distinct_states","depth","seconds","ok","tag"],r)) for r in rows]
bad=[r for r in res if r["ok"]!="ok"]
json.dump({"runs":res,"n_runs":len(res),"mismatches":len(bad),
           "constants":f"Agents={{a1,a2}}, Cells={'{c1}' if cells == '1' else '{c1,c2}'}, Values={{v1,v2}}, Tools={{t1}}, MaxOps=3, AllowSkew=FALSE, symmetry on Agents and Cells; current Guarded.tla",
           "why":"the bounds at which the supersession (non-NULL read) class of A1 is reachable (supplement S L); the NoA1 half of the matrix re-checked there"},
          open(out + '.json','w'),indent=1)
print(f"{len(res)} runs, {len(bad)} mismatches/timeouts -> {out}.json")
import sys; sys.exit(1 if bad else 0)
PY
