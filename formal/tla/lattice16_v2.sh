#!/usr/bin/env bash
# lattice16_v2.sh -- the SAFETY half of lattice16 at Values = {v1, v2} on the
# CURRENT Guarded.tla (G3 = output commit).  32 TLC runs (for each guard set S,
# each anomaly in S must be unreachable, exhaustively); the witness half needs
# no re-run because widening Values only adds behaviours.  Writes
# lattice16_v2_results.{tsv,json}; exits non-zero on any non-SAFE run.
# Usage: ./lattice16_v2.sh [path/to/tla2tools.jar]
set -euo pipefail
JAR="${1:-${TLA_TOOLS:-$HOME/tla2tools.jar}}"
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found at $JAR" >&2; exit 1; }
[ -f Guarded.tla ] && [ -f Memory.tla ] && [ -f Anomalies.tla ] || { echo "FAIL: run in tla/" >&2; exit 1; }
mkdir -p lattice16_v2_runs && cp Memory.tla Anomalies.tla lattice16_v2_runs/
: > lattice16_v2_results.tsv
for g1 in FALSE TRUE; do for g2 in FALSE TRUE; do for g3 in FALSE TRUE; do for g6 in FALSE TRUE; do
  for inv in NoA1 NoA2 NoA3 NoA6; do
    case $inv in NoA1) g=$g1;; NoA2) g=$g2;; NoA3) g=$g3;; NoA6) g=$g6;; esac
    [ "$g" = TRUE ] || continue                      # safety half only
    tag="G1${g1:0:1}_G2${g2:0:1}_G3${g3:0:1}_G6${g6:0:1}_${inv}_v2"
    python3 mkcfg.py $g1 $g2 $g3 $g6 $inv | sed 's/Values = {v1}/Values = {v1, v2}/' > lattice16_v2_runs/$tag.cfg
    grep -q "Values = {v1, v2}" lattice16_v2_runs/$tag.cfg || { echo "FAIL: value domain not widened" >&2; exit 1; }
    cp Guarded.tla lattice16_v2_runs/$tag.tla; sed -i "s/MODULE Guarded/MODULE $tag/" lattice16_v2_runs/$tag.tla
    ( cd lattice16_v2_runs && timeout 3600 java -XX:+UseParallelGC -Xmx6g -cp "$JAR" tlc2.TLC -workers auto -deadlock \
        -metadir "states_$tag" -config $tag.cfg $tag.tla > $tag.log 2>&1 ) || true
    if grep -q "No error has been found" lattice16_v2_runs/$tag.log; then out=SAFE
    elif grep -q "is violated" lattice16_v2_runs/$tag.log; then out=WITNESS
    else out=TIMEOUT_OR_ERROR; fi
    states=$(grep -oE "[0-9,]+ distinct states found" lattice16_v2_runs/$tag.log | tail -1 | tr -d ',' | cut -d' ' -f1)
    ok=$([ "$out" = SAFE ] && echo ok || echo MISMATCH)
    printf "%s\t%s\t%s\t%s\t%s\tSAFE\t%s\t%s\t%s\t%s\n" "$g1" "$g2" "$g3" "$g6" "$inv" "$out" "${states:-?}" "$ok" "$tag" >> lattice16_v2_results.tsv
    echo "$tag expected=SAFE got=$out states=${states:-?} $ok"
    rm -rf "lattice16_v2_runs/states_$tag"
  done
done; done; done; done
python3 - <<'PY'
import json
rows=[l.rstrip('\n').split('\t') for l in open('lattice16_v2_results.tsv')]
res=[dict(zip(["G1","G2","G3","G6","invariant","expected","result","distinct_states","ok","tag"],r)) for r in rows]
bad=[r for r in res if r["ok"]!="ok"]
json.dump({"runs":res,"n_runs":len(res),"mismatches":len(bad),
           "constants":"Agents={a1,a2}, Cells={c1,c2}, Values={v1,v2}, Tools={t1}, MaxOps=2, AllowSkew=FALSE, symmetry on Agents and Cells; current Guarded.tla (G3 = output commit)"},
          open('lattice16_v2_results.json','w'), indent=1)
print(f"{len(res)} runs, {len(bad)} mismatches")
raise SystemExit(1 if bad else 0)
PY
