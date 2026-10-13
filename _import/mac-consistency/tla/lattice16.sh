#!/usr/bin/env bash
# lattice16.sh — TLC check that ONE parameterized runtime (Guarded.tla)
# realizes all 16 points of the Boolean lattice 2^{A1,A2,A3,A6}:
# for every guard set S, each anomaly in S is unreachable (exhaustive) and
# each anomaly not in S has a witness trace.  64 TLC runs; writes
# lattice16_results.json and exits non-zero unless every run matches
# expectation.  Usage: ./lattice16.sh [path/to/tla2tools.jar]
set -euo pipefail
JAR="${1:-${TLA_TOOLS:-$HOME/tla2tools.jar}}"
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found at $JAR" >&2; exit 1; }
[ -f Guarded.tla ] && [ -f Memory.tla ] && [ -f Anomalies.tla ] || { echo "FAIL: run in the tla/ directory holding Guarded.tla, Memory.tla, Anomalies.tla" >&2; exit 1; }
mkdir -p lattice16_runs && cp Memory.tla Anomalies.tla lattice16_runs/
: > lattice16_results.tsv
for g1 in FALSE TRUE; do for g2 in FALSE TRUE; do for g3 in FALSE TRUE; do for g6 in FALSE TRUE; do
  for inv in NoA1 NoA2 NoA3 NoA6; do
    case $inv in NoA1) g=$g1;; NoA2) g=$g2;; NoA3) g=$g3;; NoA6) g=$g6;; esac
    tag="G1${g1:0:1}_G2${g2:0:1}_G3${g3:0:1}_G6${g6:0:1}_${inv}"
    python3 mkcfg.py $g1 $g2 $g3 $g6 $inv > lattice16_runs/$tag.cfg
    cp Guarded.tla lattice16_runs/$tag.tla; sed -i "s/MODULE Guarded/MODULE $tag/" lattice16_runs/$tag.tla
    ( cd lattice16_runs && timeout 900 java -XX:+UseParallelGC -Xmx6g -cp "$JAR" tlc2.TLC -workers auto -deadlock \
        -config $tag.cfg $tag.tla > $tag.log 2>&1 ) || true
    if grep -q "No error has been found" lattice16_runs/$tag.log; then out=SAFE
    elif grep -q "is violated" lattice16_runs/$tag.log; then out=WITNESS
    else out=TIMEOUT_OR_ERROR; fi
    exp=$([ "$g" = TRUE ] && echo SAFE || echo WITNESS)
    states=$(grep -oE "[0-9,]+ distinct states found" lattice16_runs/$tag.log | tail -1 | tr -d ',' | cut -d' ' -f1)
    ok=$([ "$out" = "$exp" ] && echo ok || echo MISMATCH)
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$g1" "$g2" "$g3" "$g6" "$inv" "$exp" "$out" "${states:-?}" "$ok" "$tag" >> lattice16_results.tsv
    echo "$tag expected=$exp got=$out states=${states:-?} $ok"
  done
done; done; done; done
python3 - <<'PY'
import json
rows=[l.rstrip('\n').split('\t') for l in open('lattice16_results.tsv')]
res=[dict(zip(["G1","G2","G3","G6","invariant","expected","result","distinct_states","ok","tag"],r)) for r in rows]
bad=[r for r in res if r["ok"]!="ok"]
json.dump({"runs":res,"n_runs":len(res),"mismatches":len(bad),
           "constants":"Agents={a1,a2}, Cells={c1,c2}, Values={v1}, Tools={t1}, MaxOps=2, AllowSkew=FALSE, symmetry on Agents and Cells"},
          open('lattice16_results.json','w'),indent=1)
print(f"{len(res)} runs, {len(bad)} mismatches")
raise SystemExit(1 if bad else 0)
PY
