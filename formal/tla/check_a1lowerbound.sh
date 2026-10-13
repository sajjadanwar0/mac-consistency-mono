#!/usr/bin/env bash
# check_a1lowerbound.sh -- TLC-check every claim A1LowerBound.tla rests on.
#
# TLAPS proves the theorem. TLC cannot replace that proof, and does not try
# to. What it can do, and what TLAPS does not, is pin down WHAT the theorem
# says: whether its disjunction is degenerate, whether it is a one-way bound
# or an equivalence, and whether each hypothesis is doing work. Those three
# questions decide how the result should be described, and the answers below
# are machine-checked rather than asserted.
#
#   ./check_a1lowerbound.sh [path/to/tla2tools.jar]
set -euo pipefail
JAR="${1:-${TLA_TOOLS:-$HOME/tla2tools.jar}}"
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found at $JAR" >&2; exit 1; }
[ -f MC_A1LowerBound.tla ] || { echo "FAIL: run in the tla/ directory holding MC_A1LowerBound.tla" >&2; exit 1; }
command -v java >/dev/null || { echo "FAIL: java not on PATH" >&2; exit 1; }

# Scratch lives OUTSIDE the repository: tla/ has no ignore rule for a run
# directory, so writing one here would leave the tree dirty after every run.
# Per-claim logs stay in tla/ as a1lb_<claim>.log, which *.log already ignores.
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/base.cfg" <<'CFG'
SPECIFICATION Spec
CONSTANTS
    Agents  = {a1, a2}
    Cells   = {c1}
    Values  = {v1}
    NULL    = "NULL"
    MaxLen  = 2
    MaxTime = 2
CFG

# claim : expected verdict
CLAIMS="Degenerate:HOLDS
ConverseUnconditional:HOLDS
ForwardValueAgreementOnly:HOLDS
TheoremHolds:HOLDS
ConverseHolds:HOLDS
DropNonOverlapping:VIOLATED
DropMonotonic:VIOLATED"

fail=0
printf '  %-28s %-9s %-9s %s\n' claim expected got states
printf '  %s\n' "--------------------------------------------------------------"
while IFS=: read -r inv want; do
  [ -n "$inv" ] || continue
  cp "$WORK/base.cfg" "$WORK/$inv.cfg"; echo "INVARIANT $inv" >> "$WORK/$inv.cfg"
  cp MC_A1LowerBound.tla "$WORK/M_$inv.tla"
  sed -i "s/MODULE MC_A1LowerBound/MODULE M_$inv/" "$WORK/M_$inv.tla"
  out=$( (cd "$WORK" && timeout 900 java -XX:+UseSerialGC -Xmx2000m -cp "$JAR" \
            tlc2.TLC -workers 1 -deadlock -config "$inv.cfg" "M_$inv.tla" 2>&1) || true )
  st=$( (printf '%s' "$out" | grep -oE '[0-9]+ distinct states found' || true) | tail -1 | cut -d' ' -f1)
  if   printf '%s' "$out" | grep -q 'No error has been found'; then got=HOLDS
  elif printf '%s' "$out" | grep -q 'is violated'; then got=VIOLATED
  else got=ERROR; fi
  printf '  %-28s %-9s %-9s %s\n' "$inv" "$want" "$got" "${st:-?}"
  [ "$got" = "$want" ] || fail=1
  printf '%s' "$out" > "a1lb_$inv.log"
done <<< "$CLAIMS"

echo
if [ "$fail" -ne 0 ]; then
  echo "FAIL: at least one claim did not match its expected verdict" >&2
  exit 1
fi
cat <<'TXT'
  All seven match. What they establish, together:

    ReadSetLock(h,i) => ValueAgreement(h,i) holds unconditionally, so the
    disjunction A1Mechanism == ReadSetLock \/ ValueAgreement is degenerate:
    it is ValueAgreement alone.

    The implication runs BOTH ways, so the result is an equivalence and not
    a lower bound -- and the two directions carry different hypotheses. The
    converse needs neither NonOverlappingAgent nor MonotonicOp. The forward
    direction needs both, and dropping either yields a counterexample: in
    each case one agent conflicting with ITSELF, which StaleGeneration
    excludes by requiring distinct agents.

    So the content of A1LowerBound.tla is a same-agent exclusion lemma,
    stated as an equivalence with asymmetric hypotheses.
TXT
