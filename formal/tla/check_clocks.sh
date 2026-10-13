#!/usr/bin/env bash
# check_clocks.sh -- is A_1 an anomaly, or an artifact of the logical clock?
#
# Section 5.13 reports the same live sessions at 42/100, 72/100 and 26/100
# under the completion clock and 0/100 under the barrier clock, while the
# summarizer commits on a superseded plan in every session. Read as three
# competing measurements that is a contradiction. It is not: the three stand
# in a strict relationship, and this script checks it.
#
#   ./check_clocks.sh [path/to/tla2tools.jar]
set -euo pipefail
JAR="${1:-${TLA_TOOLS:-$HOME/tla2tools.jar}}"
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found at $JAR" >&2; exit 1; }
[ -f MC_ClockSensitivity.tla ] || { echo "FAIL: run in the tla/ directory holding MC_ClockSensitivity.tla" >&2; exit 1; }
command -v java >/dev/null || { echo "FAIL: java not on PATH" >&2; exit 1; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/base.cfg" <<'CFG'
SPECIFICATION Spec
CONSTANTS
    Agents     = {a1, a2}
    Cells      = {c1}
    Values     = {v1}
    NULL       = "NULL"
    MaxLen     = 2
    MaxBarrier = 2
    MaxOrder   = 2
CFG

CLAIMS="BarrierImpliesSemantic:HOLDS
TemporalImpliesSemantic:HOLDS
TemporalNeedsRefinement:VIOLATED
SemanticImpliesTemporal:VIOLATED
OneBarrierBlindsBarrierClock:HOLDS
OneBarrierBlindsCompletionClock:VIOLATED"

fail=0
printf '  %-34s %-9s %-9s %s\n' claim expected got states
printf '  %s\n' "------------------------------------------------------------------"
while IFS=: read -r inv want; do
  [ -n "$inv" ] || continue
  cp "$WORK/base.cfg" "$WORK/$inv.cfg"; echo "INVARIANT $inv" >> "$WORK/$inv.cfg"
  cp MC_ClockSensitivity.tla "$WORK/M_$inv.tla"
  sed -i "s/MODULE MC_ClockSensitivity/MODULE M_$inv/" "$WORK/M_$inv.tla"
  out=$( (cd "$WORK" && timeout 1200 java -XX:+UseSerialGC -Xmx2000m -cp "$JAR" \
            tlc2.TLC -workers 1 -deadlock -config "$inv.cfg" "M_$inv.tla" 2>&1) || true )
  st=$( (printf '%s' "$out" | grep -oE '[0-9]+ distinct states found' || true) | tail -1 | cut -d' ' -f1)
  if   printf '%s' "$out" | grep -q 'No error has been found'; then got=HOLDS
  elif printf '%s' "$out" | grep -q 'is violated'; then got=VIOLATED
  else got=ERROR; fi
  printf '  %-34s %-9s %-9s %s\n' "$inv" "$want" "$got" "${st:-?}"
  [ "$got" = "$want" ] || fail=1
  printf '%s' "$out" > "clocks_$inv.log"
done <<< "$CLAIMS"

echo
if [ "$fail" -ne 0 ]; then
  echo "FAIL: at least one claim did not match its expected verdict" >&2
  exit 1
fi
cat <<'TXT'
  All six match. The three figures are not competing measurements:

    A_1 under the completion clock IMPLIES semantic staleness, and so does
    A_1 under the barrier clock. The 42/100 is therefore a lower bound on
    the 100/100, not a rival to it.

    The converse fails, and the counterexample is the real case: two node
    bodies that return in the same completion slot. The reader still
    committed on a value its own superstep superseded, but Definition 1's
    strict window (write_order_j < write_order_i) cannot see it. That gap
    IS the distance between 42 and 100.

    When every write lands in one barrier the barrier clock can witness
    nothing at all -- its window needs write_barrier_j < write_barrier_i,
    which one barrier makes impossible. The 0/100 is therefore definitional
    and must not be read as evidence that nothing went stale. The completion
    clock is NOT blind there, which is exactly the sensitivity observed.
TXT
