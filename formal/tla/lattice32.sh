#!/usr/bin/env bash
# lattice32.sh -- TLC check that ONE parameterized runtime (Guarded5.tla) realizes
# all 32 points of the Boolean lattice 2^{A1,A2,A3,A6,A7}: for every guard set S,
# each anomaly in S is unreachable (exhaustive) and each anomaly not in S has a
# witness trace.  160 TLC runs; writes lattice32_results.{tsv,json}; exit non-zero
# on any mismatch.  Usage: ./lattice32.sh [path/to/tla2tools.jar] [--only NoA7]
set -euo pipefail
JAR="${1:-${TLA_TOOLS:-$HOME/tla2tools.jar}}"; shift || true
ONLY=""; [ "${1:-}" = "--only" ] && ONLY="$2"
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found at $JAR" >&2; exit 1; }
[ -f Guarded5.tla ] && [ -f Memory.tla ] && [ -f Anomalies.tla ] || { echo "FAIL: run in tla/" >&2; exit 1; }
mkdir -p lattice32_runs && cp Memory.tla Anomalies.tla lattice32_runs/
OUT=lattice32_results${ONLY:+_$ONLY}.tsv; : > "$OUT"
for g1 in FALSE TRUE; do for g2 in FALSE TRUE; do for g3 in FALSE TRUE; do for g6 in FALSE TRUE; do for g7 in FALSE TRUE; do
  for inv in NoA1 NoA2 NoA3 NoA6 NoA7; do
    [ -n "$ONLY" ] && [ "$inv" != "$ONLY" ] && continue
    case $inv in NoA1) g=$g1;; NoA2) g=$g2;; NoA3) g=$g3;; NoA6) g=$g6;; NoA7) g=$g7;; esac
    tag="G1${g1:0:1}_G2${g2:0:1}_G3${g3:0:1}_G6${g6:0:1}_G7${g7:0:1}_${inv}"
    python3 mkcfg5.py $g1 $g2 $g3 $g6 $g7 $inv > lattice32_runs/$tag.cfg
    cp Guarded5.tla lattice32_runs/$tag.tla; sed -i "s/MODULE Guarded5/MODULE $tag/" lattice32_runs/$tag.tla
    ( cd lattice32_runs && timeout 1800 java -XX:+UseParallelGC -Xmx6g -cp "$JAR" tlc2.TLC -workers auto -deadlock \
        -metadir "states_$tag" -config $tag.cfg $tag.tla > $tag.log 2>&1 ) || true
    if grep -q "No error has been found" lattice32_runs/$tag.log; then out=SAFE
    elif grep -q "is violated" lattice32_runs/$tag.log; then out=WITNESS
    else out=TIMEOUT_OR_ERROR; fi
    exp=$([ "$g" = TRUE ] && echo SAFE || echo WITNESS)
    states=$(grep -oE "[0-9,]+ distinct states found" lattice32_runs/$tag.log | tail -1 | tr -d ',' | cut -d' ' -f1)
    ok=$([ "$out" = "$exp" ] && echo ok || echo MISMATCH)
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$g1" "$g2" "$g3" "$g6" "$g7" "$inv" "$exp" "$out" "${states:-?}" "$ok" "$tag" >> "$OUT"
    echo "$tag expected=$exp got=$out states=${states:-?} $ok"
    rm -rf "lattice32_runs/states_$tag"
  done
done; done; done; done; done
python3 - "$OUT" <<'PY'
import json, sys
f=sys.argv[1]
rows=[l.rstrip('\n').split('\t') for l in open(f)]
res=[dict(zip(["G1","G2","G3","G6","G7","invariant","expected","result","distinct_states","ok","tag"],r)) for r in rows]
bad=[r for r in res if r["ok"]!="ok"]
json.dump({"runs":res,"n_runs":len(res),"mismatches":len(bad),
           "constants":"Agents={a1,a2}, Cells={c1,c2}, Values={v1}, Tools={t1}, MaxOps=2, AllowSkew=FALSE, symmetry on Agents and Cells"},
          open(f.replace('.tsv','.json'),'w'),indent=1)
print(f"{len(res)} runs, {len(bad)} mismatches")
raise SystemExit(1 if bad else 0)
PY
