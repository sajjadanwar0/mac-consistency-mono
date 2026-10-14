#!/usr/bin/env bash
# check_duplication.sh -- TLC on Duplication.tla: (1) without an idempotency guard the deployed
# interrupt shape reaches a duplicate emission (AtMostOnce VIOLATED, witness printed), (2) the
# two emissions differ in their argument when the value was revised during the gate
# (NoDivergentDuplicate VIOLATED), (3) with the guard (Dedup = TRUE) AtMostOnce and
# OneEffectPerDoneNode hold exhaustively.  Exit 1 on any unexpected verdict.
#   ./check_duplication.sh [path/to/tla2tools.jar]
set -uo pipefail
J="${1:-${TLA_TOOLS:-../../tools/tla2tools.jar}}"
run() { # run <cfg> <expect: SAFE|VIOLATED> <label>
  local cfg=$1 expect=$2 label=$3 out
  out=$(java -XX:+UseParallelGC -cp "$J" tlc2.TLC -config "$cfg" -workers 1 -deadlock Duplication.tla 2>&1)
  if echo "$out" | grep -q "Invariant .* is violated"; then verdict=VIOLATED; elif echo "$out" | grep -q "Model checking completed. No error"; then verdict=SAFE; else verdict=ERROR; fi
  states=$(echo "$out" | grep -oE "[0-9,]+ distinct states found" | head -1)
  depth=$(echo "$out" | grep -cE "^State [0-9]+: ")
  printf '%-60s %-9s (expected %-8s) %s; witness depth %s\n' "$label" "$verdict" "$expect" "$states" "$depth"
  [ "$verdict" = "$expect" ] || { echo "$out" | tail -40; return 1; }
  if [ "$verdict" = VIOLATED ]; then echo "$out" | sed -n '/^Error: Invariant/,/^[0-9]* states generated/p' | grep -E "^State|emitted|cell|phase|Error" | head -40; fi
}
bad=0
run MC_Duplication_witness.cfg   VIOLATED "D reachable: effect before the gate, resume re-issues it" || bad=1
run MC_Duplication_divergent.cfg VIOLATED "the two emissions differ (revision during the gate)"      || bad=1
run MC_Duplication_dedup.cfg     SAFE     "idempotency key restores at-most-once (exhaustive)"       || bad=1
[ $bad = 0 ] && echo "OK: Duplication.tla verdicts as expected" || { echo "FAIL"; exit 1; }
