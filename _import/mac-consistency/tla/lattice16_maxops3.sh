#!/usr/bin/env bash
# =====================================================================
# lattice16_maxops3.sh -- all sixteen NoA3 points of the matrix, at
# MaxOps=3 with Cells={c1}.
#
# WHY THIS EXISTS.  lattice16.sh checks all 64 points at MaxOps=2.
# Guarded.tla guards commit with Len(log) < MaxOps, so two operations is
# the entire universe of those runs.  A transitive cascade -- root
# aborted, dependent, dependent-of-dependent -- needs three, so at
# MaxOps=2 the G3 guard's Closure() never adds anything beyond the direct
# predecessor and A3's characteristic case is never reached.
#
# WHY Cells={c1} IS SOUND HERE.  Anomalies.tla defines (round 23,
# 2026-09-15: A3 is an externalized dependent of an aborted operation)
#     CausalCascade(h) == \E j, p : h[j].externalized
#                                /\ p \in h[j].preds
#                                /\ h[p].aborted
# which ranges over externalization and abort flags and predecessor sets
# and never over cells.  Restricting to one cell cannot remove a CausalCascade witness,
# and it cuts the state space enough that MaxOps=3 closes exhaustively.
# (At Cells={c1,c2}, MaxOps=3 does not close: 8.37M distinct states after
# four minutes on one worker, still growing at depth 8.)  The restriction
# is NOT sound for NoA1, NoA2 or NoA6, whose predicates do range over
# cells, tools or write order.  Do not reuse this configuration there.
#
#   ./lattice16_maxops3.sh                          fetches tla2tools.jar
#   TLA_TOOLS=/path/tla2tools.jar ./lattice16_maxops3.sh
#   TLC_HEAP=4g TLC_WORKERS=4 ./lattice16_maxops3.sh
#
# Expect eight SAFE (G3=TRUE) and eight WITNESS (G3=FALSE).  Refuses to
# report success on any mismatch, like lattice16.sh.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

JAR="${TLA_TOOLS:-tla2tools.jar}"
if [ ! -f "$JAR" ]; then
  echo "  tla2tools.jar not present; fetching the pinned release"
  for tag in v1.7.4 v1.8.0 v1.7.3; do
    if curl -fsSL -o tla2tools.jar \
         "https://github.com/tlaplus/tlaplus/releases/download/$tag/tla2tools.jar" 2>/dev/null \
       && [ "$(stat -c%s tla2tools.jar 2>/dev/null || stat -f%z tla2tools.jar)" -gt 1000000 ]; then
      echo "  fetched tla2tools.jar ($tag)"
      JAR=tla2tools.jar
      break
    fi
    rm -f tla2tools.jar
  done
fi
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found and could not be fetched; set TLA_TOOLS" >&2; exit 1; }
# 2026-09-15 round 23: java runs inside $OUT, so the jar path must not be
# relative. OVERRULED: -cp "../$JAR", which broke the documented
# TLA_TOOLS=/path/tla2tools.jar form ("Could not find or load main class").
case "$JAR" in /*) ;; *) JAR="$PWD/$JAR" ;; esac
command -v java >/dev/null || { echo "FAIL: java not on PATH" >&2; exit 1; }

HEAP="${TLC_HEAP:-3g}"
WORKERS="${TLC_WORKERS:-1}"
OUT=lattice16_maxops3_runs
RESULTS=lattice16_maxops3_results.json
# 2026-09-15 round 23: a cached verdict is reused only for the model that
# produced it. If Memory.tla, Anomalies.tla, Guarded.tla or mkcfg.py differ
# from the copies kept in $OUT, the run tree is cleared first; before this,
# a changed model (round 23 retargeted A3) resumed on the old verdicts.
if [ -d "$OUT" ] && ! { cmp -s Memory.tla "$OUT/Memory.tla" \
                      && cmp -s Anomalies.tla "$OUT/Anomalies.tla" \
                      && cmp -s Guarded.tla "$OUT/Guarded.model.tla" \
                      && cmp -s mkcfg.py "$OUT/mkcfg.model.py"; }; then
  echo "  model differs from the one that produced $OUT; clearing it"
  rm -rf "$OUT"
fi
mkdir -p "$OUT"
cp -f Memory.tla Anomalies.tla "$OUT/"
cp -f Guarded.tla "$OUT/Guarded.model.tla"
cp -f mkcfg.py "$OUT/mkcfg.model.py"

mismatch=0
n_safe=0
n_wit=0
printf '[\n' > "$RESULTS"
first=1

for g1 in FALSE TRUE; do
for g2 in FALSE TRUE; do
for g3 in FALSE TRUE; do
for g6 in FALSE TRUE; do
  inv=NoA3
  tag="M3_G1${g1:0:1}_G2${g2:0:1}_G3${g3:0:1}_G6${g6:0:1}_${inv}"
  python3 mkcfg.py "$g1" "$g2" "$g3" "$g6" "$inv" \
    | sed -e 's/MaxOps = 2/MaxOps = 3/' \
          -e 's/Cells = {c1, c2}/Cells = {c1}/' \
          -e 's/Cells = {c1,c2}/Cells = {c1}/' > "$OUT/$tag.cfg"
  grep -q 'MaxOps = 3'  "$OUT/$tag.cfg" || { echo "FAIL: $tag.cfg did not take MaxOps=3" >&2; exit 1; }
  grep -q 'Cells = {c1}' "$OUT/$tag.cfg" || { echo "FAIL: $tag.cfg did not take Cells={c1}" >&2; exit 1; }
  cp -f Guarded.tla "$OUT/$tag.tla"
  sed -i.bak "s/MODULE Guarded/MODULE $tag/" "$OUT/$tag.tla" && rm -f "$OUT/$tag.tla.bak"

  # Resumable: a point whose log already carries a verdict is not re-run,
  # so an interrupted sweep continues instead of restarting. Delete
  # lattice16_maxops3_runs/ to force a clean sweep.
  if ! grep -qE 'No error has been found|is violated' "$OUT/$tag.log" 2>/dev/null; then
    ( cd "$OUT" && java -Xmx"$HEAP" -cp "$JAR" tlc2.TLC \
        -workers "$WORKERS" -deadlock -config "$tag.cfg" "$tag.tla" > "$tag.log" 2>&1 ) || true
  fi

  if   grep -q 'No error has been found' "$OUT/$tag.log"; then got=SAFE;    n_safe=$((n_safe+1))
  elif grep -q 'is violated'             "$OUT/$tag.log"; then got=WITNESS; n_wit=$((n_wit+1))
  else got=INCOMPLETE; fi
  [ "$g3" = TRUE ] && want=SAFE || want=WITNESS
  states=$(grep -oE '[0-9,]+ distinct states found' "$OUT/$tag.log" | tail -1 | tr -d ',' | cut -d' ' -f1)
  queue=$(grep -oE '[0-9,]+ states left on queue' "$OUT/$tag.log" | tail -1 | tr -d ',' | cut -d' ' -f1)
  [ "$got" = "$want" ] && ok=ok || { ok=MISMATCH; mismatch=1; }
  printf '  %-32s expected=%-8s got=%-10s states=%-10s queue=%-8s %s\n' \
    "$tag" "$want" "$got" "${states:-?}" "${queue:-?}" "$ok"
  [ $first -eq 1 ] || printf ',\n' >> "$RESULTS"
  first=0
  printf '  {"tag":"%s","invariant":"%s","expected":"%s","result":"%s","distinct_states":%s,"queue_left":%s,"MaxOps":3,"Cells":1}' \
    "$tag" "$inv" "$want" "$got" "${states:-0}" "${queue:-0}" >> "$RESULTS"
done; done; done; done

printf '\n]\n' >> "$RESULTS"
echo
echo "  $n_safe SAFE, $n_wit WITNESS, of 16"
if [ "$mismatch" -ne 0 ] || [ "$n_safe" -ne 8 ] || [ "$n_wit" -ne 8 ]; then
  echo "FAIL: expected 8 SAFE and 8 WITNESS with no mismatch; see $OUT/*.log"
  exit 1
fi
echo "OK: all sixteen NoA3 points match at MaxOps=3, Cells={c1}; results in $RESULTS"
