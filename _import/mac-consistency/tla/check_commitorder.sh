#!/usr/bin/env bash
# check_commitorder.sh -- TLC-check every claim CommitOrder.tla rests on, and
# that Memory.tla satisfies the theorem's hypotheses (2026-09-19 round 38).
#
#   ./check_commitorder.sh [path/to/tla2tools.jar]
#
# TLAPS proves the theorem (tlapm CommitOrder.tla: 60 obligations). TLC pins
# down what it SAYS: non-vacuity, that each hypothesis works, that the converse
# fails, that the relational definitions are Memory.tla's CHOOSE-based ones and
# a literal serial replay, and that StaleGeneration also fires on histories
# serializable in another order. Exit 0 only if every verdict is the expected one.
set -euo pipefail
JAR="${1:-${TLA_TOOLS:-$HOME/tla2tools.jar}}"
[ -f "$JAR" ] || { echo "FAIL: tla2tools.jar not found at $JAR" >&2; exit 1; }
[ -f MC_CommitOrder.tla ] && [ -f MC_CommitOrder_Memory.tla ] || { echo "FAIL: run in the tla/ directory holding MC_CommitOrder.tla" >&2; exit 1; }
command -v java >/dev/null || { echo "FAIL: java not on PATH" >&2; exit 1; }
JAR="$(cd "$(dirname "$JAR")" && pwd)/$(basename "$JAR")"

# Scratch lives OUTSIDE the repository; per-claim logs stay in tla/ as co_<claim>.log (*.log is ignored).
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

run() { # run <module> <cfg body> <claim> <expected> -> prints one line; returns 1 on mismatch
  local mod=$1 body=$2 claim=$3 want=$4 got
  mkdir -p "$WORK/$claim"; cp ./*.tla "$WORK/$claim"/
  printf '%s\nINVARIANT %s\n' "$body" "$claim" > "$WORK/$claim/$mod.cfg"
  ( cd "$WORK/$claim" && java -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers auto -deadlock -config "$mod.cfg" "$mod.tla" ) > "co_$claim.log" 2>&1 || true
  if grep -q 'Model checking completed. No error has been found' "co_$claim.log"; then got=HOLDS
  elif grep -q "Invariant $claim is violated" "co_$claim.log"; then got=VIOLATED
  else got="ERROR(see co_$claim.log)"; fi
  states="$(grep -oE '[0-9]+ distinct states found' "co_$claim.log" | tail -1 | grep -oE '^[0-9]+' || true)"
  printf '  %-28s expected %-9s got %-9s %s distinct states\n' "$claim" "$want" "$got" "${states:-?}"
  [ "$got" = "$want" ]
}

PROJ='SPECIFICATION Spec
CONSTANTS
    Agents = {a1, a2}
    Cells  = {c1}
    Values = {v1}
    NULL   = "NULL"
    MaxLen = 3'
MEM='SPECIFICATION Spec
CONSTANTS
  Agents = {a1, a2}
  Cells = {c1}
  Values = {v1}
  Tools = {t1}
  ExternalCells = {}
  NULL = NULL
  MaxOps = 3
CONSTANT AllowSkew = FALSE'

bad=0
echo "all histories of length <= 3 over the seven-field projection:"
for c in Theorem:HOLDS NotVacuous:VIOLATED Converse:VIOLATED DropAgentsDoNotOverlap:VIOLATED DropStoreAxiom:VIOLATED \
         CosIsSerialReplay:HOLDS CosMatchesChoose:HOLDS StoreAxiomMatchesChoose:HOLDS A1IsAValidationFailure:HOLDS \
         ValidationIsNoStronger:VIOLATED LostUpdateIsA1:HOLDS A1OnlyOnNonSerializable:VIOLATED; do
  run MC_CommitOrder "$PROJ" "${c%%:*}" "${c##*:}" || bad=$((bad+1))
done
echo "every reachable history of Memory.tla (MaxOps = 3, AllowSkew = FALSE):"
# one exploration serves both HOLDS claims: HypothesesAndTheoremOnMemory is their conjunction
for c in HypothesesAndTheoremOnMemory:HOLDS StrictSnapshotIsOffByOne:VIOLATED SnapshotDoesNotPreventA1:VIOLATED; do
  run MC_CommitOrder_Memory "$MEM" "${c%%:*}" "${c##*:}" || bad=$((bad+1))
done
[ "$bad" = 0 ] && echo "OK: all 15 verdicts are the expected ones" || { echo "FAIL: $bad verdict(s) differ from the expected ones" >&2; exit 1; }
