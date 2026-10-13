#!/usr/bin/env bash
# reproduce.sh -- single-command audit of the mac-consistency monorepo, in the
# style of resume-contract/reproduce.sh.  Every stage re-derives a published
# figure from COMMITTED data and diffs it against CLAIMS.json; a stage whose
# tool is absent SKIPS and says so (exit code reflects only stages that ran,
# unless --strict, in which case a skipped stage is a failure).
#
#   ./reproduce.sh                 all stages
#   ./reproduce.sh --formal-only   [1] TLC  [2] TLAPS  [3] Verus
#   ./reproduce.sh --data-only     [4] rescoring gates (python only, offline)
#   ./reproduce.sh --strict        skips are failures (CI / pre-submission)
#
# Stages
#   [1] TLC      anomaly witnesses (violations), MC_A0_vacuous (holds), the 15
#                CommitOrder verdicts, the 64-point lattice16 matrix (+16 at MaxOps=3),
#                the 160-run lattice32 matrix over Guarded5.tla (A7 / G7)
#   [2] TLAPS    Hierarchy 15 / A1LowerBound 28 / CommitOrder 60 obligations
#   [3] Verus    verus_count.sh against the PINNED build; per-file counts vs CLAIMS.json
#   [4] Data     check_tables.sh (Def-1 rescoring of every published cell),
#                predicate_matrix_a1.py --strict (three transcriptions agree),
#                outcome_rescore.py --check (booking-outcome table), a7_rescore.py --check (R column),
#                hypothesis_gates.py --check (Lemma 1 / value-uniqueness / FP shape / provenance recall),
#                claims_from_results.py (probe receipts -> paper/claims_results.tex),
#                claims_gate.py (no prose figure contradicts CLAIMS.json)
#   [5] Rust     cargo test --workspace; examples l2_measure / l4_measure (seeded) diffed
#                against the committed text receipts results/l2_measure.txt, results/l4_measure.txt
#   [6] Census   langgraph_census.py --check / --selftest; langgraph_static.py --selftest
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
STRICT=0; FORMAL_ONLY=0; DATA_ONLY=0
for a in "$@"; do case "$a" in --strict) STRICT=1;; --formal-only) FORMAL_ONLY=1;; --data-only) DATA_ONLY=1;; esac; done
FAIL=0; SKIP=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL=$((FAIL+1)); }
skip() { printf '  \033[33mskip\033[0m  %s\n' "$*"; SKIP=$((SKIP+1)); [ "$STRICT" = 1 ] && FAIL=$((FAIL+1)); }
hdr()  { printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }
mkdir -p "$ROOT/tools"   # logs of every stage land here (git-ignored)
JAR="${TLA_TOOLS:-$ROOT/tools/tla2tools.jar}"
if [ ! -f "$JAR" ] && [ "$DATA_ONLY" = 0 ]; then
  curl -sSL -o "$JAR" https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar || true
fi
CLAIMS="$ROOT/CLAIMS.json"
[ -f "$CLAIMS" ] || { echo "FAIL: CLAIMS.json missing (python3 harness/macaudit/claims_gate.py --init)"; exit 1; }
cget() { python3 - "$1" <<'PY'
import json,sys; d=json.load(open("CLAIMS.json"))
for k in sys.argv[1].split("."): d=d[k]
print(d)
PY
}
export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-}"
export TLA_TOOLS="$JAR"

# ---------------------------------------------------------------- [1] TLC
if [ "$DATA_ONLY" = 0 ]; then
hdr 1 "TLC: witnesses, vacuity, CommitOrder verdicts, lattice16"
if have java && [ -f "$JAR" ]; then
  cd "$ROOT/formal/tla"
  tlc() { java -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers auto -metadir "$ROOT/tools/tlc_$1" -config "$1.cfg" "$1.tla" 2>&1; }
  for m in MC_A1 MC_A2 MC_A3 MC_A6 MC_A1_struct; do
    if tlc $m | grep -q "is violated"; then ok "$m: witness found (expect-violation)"; else bad "$m: expected a violation"; fi
  done
  if tlc MC_A0_vacuous | grep -q "No error has been found"; then ok "MC_A0_vacuous holds"; else bad "MC_A0_vacuous (run scripts/01_fix_mc_a0_vacuous.sh?)"; fi
  if ./check_commitorder.sh "$JAR" >"$ROOT/tools/commitorder.log" 2>&1; then
    n=$(grep -c 'expected' "$ROOT/tools/commitorder.log"); ok "check_commitorder.sh: $n verdicts as expected (claimed $(cget tlc.commitorder_verdicts))"
  else bad "check_commitorder.sh (see tools/commitorder.log)"; fi
  if [ "${QUICK:-0}" = 1 ]; then skip "lattice16.sh (QUICK=1); reference: lattice16_results.reference.json"
  else
    if ./lattice16.sh "$JAR" >"$ROOT/tools/lattice16.log" 2>&1; then
      if python3 - <<'PY'
import json
a=json.load(open('lattice16_results.json')); b=json.load(open('lattice16_results.reference.json'))
ra={r['tag']:(r['result'],r['distinct_states']) for r in a['runs']}; rb={r['tag']:(r['result'],r['distinct_states']) for r in b['runs']}
bad=[t for t in rb if ra.get(t,(None,None))[0]!=rb[t][0] or (rb[t][0]=='SAFE' and ra[t][1]!=rb[t][1])]
print("lattice16: 64 runs,", a['mismatches'], "mismatches;", len(bad), "cells differ from reference"); raise SystemExit(1 if bad or a['mismatches'] else 0)
PY
      then ok "lattice16: 64/64 match the committed reference (safe-run state counts identical)"; else bad "lattice16 differs from reference"; fi
    else bad "lattice16.sh failed (tools/lattice16.log)"; fi
  fi
  # --- A7 / G7: the 32-point lattice (Guarded5.tla), 160 runs (~1-2 h; QUICK=1 checks the two A7 cells only)
  if [ -f Guarded5.tla ]; then
    if [ "${QUICK:-0}" = 1 ]; then
      if ./lattice32.sh "$JAR" --only NoA7 >"$ROOT/tools/lattice32_quick.log" 2>&1; then ok "lattice32 (QUICK): the 16 NoA7 cells match (witness without G7, exhaustive with G7)"; else bad "lattice32 --only NoA7 (tools/lattice32_quick.log)"; fi
    elif ./lattice32.sh "$JAR" >"$ROOT/tools/lattice32.log" 2>&1; then
      if python3 - <<'PY'
import json
a=json.load(open('lattice32_results.json')); b=json.load(open('lattice32_results.reference.json'))
ra={r['tag']:(r['result'],r['distinct_states']) for r in a['runs']}; rb={r['tag']:(r['result'],r['distinct_states']) for r in b['runs']}
bad=[t for t in rb if ra.get(t,(None,None))[0]!=rb[t][0] or (rb[t][0]=='SAFE' and ra[t][1]!=rb[t][1])]
print("lattice32: %d runs," % a['n_runs'], a['mismatches'], "mismatches;", len(bad), "cells differ from reference"); raise SystemExit(1 if bad or a['mismatches'] or a['n_runs']!=160 else 0)
PY
      then ok "lattice32: 160/160 match the committed reference"; else bad "lattice32 differs from reference (tools/lattice32.log)"; fi
    else bad "lattice32.sh failed (tools/lattice32.log)"; fi
  else skip "Guarded5.tla not present (A7/L5 not merged yet)"; fi
  cd "$ROOT"
else skip "java / tla2tools.jar not available"; fi

# ---------------------------------------------------------------- [2] TLAPS
hdr 2 "TLAPS: Hierarchy / A1LowerBound / CommitOrder"
if have tlapm; then
  cd "$ROOT/formal/tla"
  for spec in "matrix/Hierarchy.tla|tlaps.Hierarchy.tla" "A1LowerBound.tla|tlaps.A1LowerBound.tla" "CommitOrder.tla|tlaps.CommitOrder.tla"; do
    IFS='|' read -r f k <<<"$spec"; want=$(cget "$k")
    out=$(tlapm --toolbox 0 0 "$f" 2>&1); got=$(echo "$out" | grep -oE 'All [0-9]+ obligations? proved' | grep -oE '[0-9]+' | tail -1)
    if [ "$got" = "$want" ]; then ok "$f: $got obligations proved"; else bad "$f: got '${got:-none}' expected $want"; fi
  done
  cd "$ROOT"
else skip "tlapm not on PATH"; fi

# ---------------------------------------------------------------- [3] Verus
hdr 3 "Verus: pinned build, per-file counts, trust base"
if have verus || ls "$HOME"/.local/opt/*/verus >/dev/null 2>&1; then
  cd "$ROOT/crates/verus-detector"
  pin=$(grep -oE '^verus\s*=\s*\S+' verus-version.txt | sed -E 's/.*=\s*//')
  if bash "$ROOT/harness/macaudit/verus_count.sh" --full >"$ROOT/tools/verus_count.log" 2>&1; then
    tot=$(grep -oE 'DISTINCT obligation total +[0-9]+' "$ROOT/tools/verus_count.log" | grep -oE '[0-9]+' | tail -1)
    want=$(cget verus.full_total)
    if [ "$tot" = "$want" ]; then ok "verus_count.sh --full = $tot (pin $pin)"; else bad "verus_count.sh --full = ${tot:-?}, CLAIMS.json says $want"; fi
  else bad "verus_count.sh failed (tools/verus_count.log) -- is the PINNED build ($pin) installed?"; fi
  # trust base must be exactly: 2 axioms x 4 refinement files + 3 RUSTBELT stubs, no assume/admit
  ax=$(grep -lE '^\s*pub broadcast proof fn axiom_' src/*.rs | wc -l)
  eb=$(grep -cE '^\s*#\[verifier::external_body\]' src/lib_rustbelt_interface.rs)
  as=$(grep -nE '^\s*[^/]*\b(assume|admit)\(' src/*.rs | wc -l)
  if [ "$ax" = 4 ] && [ "$eb" = 3 ] && [ "$as" = 0 ]; then ok "trust base: 2 axioms in 4 refinement files, 3 RustBelt stubs, 0 assume/admit"; else bad "trust base drifted: axiom-files=$ax rustbelt-stubs=$eb assume/admit=$as"; fi
  cd "$ROOT"
else skip "verus not installed (pin: $(grep -oE '^verus\s*=\s*\S+' crates/verus-detector/verus-version.txt))"; fi
fi # DATA_ONLY

# ---------------------------------------------------------------- [4] Data gates
if [ "$FORMAL_ONLY" = 0 ]; then
hdr 4 "Rescoring gates (python3 only, offline)"
cd "$ROOT"
if python3 harness/macaudit/rescore_cells.py --root results >tools/rescore_cells.log 2>&1; then ok "rescore_cells: $(grep -oE '[0-9]+ cells' tools/rescore_cells.log | head -1) rescored under Definition 1, 0 disagreements"; else bad "rescore_cells (tools/rescore_cells.log)"; fi
if python3 harness/macaudit/predicate_matrix_a1.py --root results --strict >tools/predicate_matrix.log 2>&1; then ok "predicate_matrix_a1: TLA+/Verus/analyser transcriptions agree on every cell"; else bad "predicate_matrix_a1: transcriptions DIVERGE (tools/predicate_matrix.log)"; fi
if python3 harness/macaudit/outcome_rescore.py --root results --check >tools/outcome.log 2>&1; then ok "outcome_rescore: booking-outcome table reproduced"; else bad "outcome_rescore (tools/outcome.log)"; fi
if [ -f harness/macaudit/a7_rescore.py ]; then
  if python3 harness/macaudit/a7_rescore.py --root results --check >tools/a7.log 2>&1; then ok "a7_rescore: A1 + R = (booking != final) on every live cell (Table 3, R column)"; else bad "a7_rescore (tools/a7.log)"; fi
fi
if [ -f harness/macaudit/hypothesis_gates.py ]; then
  if python3 harness/macaudit/hypothesis_gates.py --root results --check >tools/hypotheses.log 2>&1; then ok "hypothesis_gates: $(grep -oE 'H1: [0-9]+ same-agent overlapping windows over [0-9]+ records' tools/hypotheses.log); $(grep -oE 'H3: .*' tools/hypotheses.log); $(grep -oE 'H4: .*' tools/hypotheses.log)"; else bad "hypothesis_gates: Lemma 1's hypothesis violated on committed data (tools/hypotheses.log)"; fi
fi
if [ -f harness/macaudit/claims_from_results.py ] && [ -d paper ]; then
  if python3 harness/macaudit/claims_from_results.py --root results --paper paper >tools/claims_results.log 2>&1; then ok "claims_from_results: $(tail -1 tools/claims_results.log)"; else bad "claims_from_results (tools/claims_results.log)"; fi
fi
# docs/legacy (the three pre-merge READMEs, kept verbatim under a "superseded" banner) and
# docs/audit (the review, which quotes the stale figures on purpose) are not scanned.
if python3 harness/macaudit/claims_gate.py --claims CLAIMS.json --scan README.md docs/decisions crates/*/README.md formal/*/README.md paper >tools/claims.log 2>&1; then ok "claims_gate: no prose figure contradicts CLAIMS.json"; else bad "claims_gate: $(grep -c CLAIM-MISMATCH tools/claims.log) contradicting figure(s) (tools/claims.log)"; fi

# ---------------------------------------------------------------- [5] Rust
hdr 5 "Rust: cargo test; L2/L4 measurements vs committed receipts"
if have cargo; then
  if cargo test --workspace --release -q >tools/cargo_test.log 2>&1; then ok "cargo test --workspace"; else bad "cargo test (tools/cargo_test.log)"; fi
  # the two measurement examples are seeded and print their tables as text; that text IS the receipt
  for ex in l2_measure l4_measure; do
    if cargo run --release -q -p agent-consistency-runtime --example $ex >"tools/$ex.txt" 2>/dev/null; then
      if [ -f "results/$ex.txt" ]; then
        if diff -q "tools/$ex.txt" "results/$ex.txt" >/dev/null; then ok "$ex output matches the committed receipt results/$ex.txt"; else bad "$ex output differs from results/$ex.txt (diff tools/$ex.txt results/$ex.txt)"; fi
      else skip "$ex: no committed receipt yet -- commit this run's output:  cp tools/$ex.txt results/$ex.txt"; fi
    else bad "$ex: cargo run failed (tools/$ex.txt)"; fi
  done
else skip "cargo not on PATH"; fi

# ---------------------------------------------------------------- [6] Census
hdr 6 "Census (offline checks)"
C=$(ls probes/*_langgraph_census.py 2>/dev/null | head -1); S=$(ls probes/*_langgraph_static.py 2>/dev/null | head -1)
if [ -n "$C" ]; then
  export PYTHONPATH="probes/_modules${PYTHONPATH:+:$PYTHONPATH}"   # renumbered probes import each other by original name
  if python3 "$C" --check --dir archaeology/langgraph_census >tools/census.log 2>&1 && python3 "$C" --selftest >>tools/census.log 2>&1; then ok "langgraph_census --check/--selftest"; else bad "langgraph_census (tools/census.log)"; fi
  if python3 "$S" --selftest >>tools/census.log 2>&1; then ok "langgraph_static --selftest"; else bad "langgraph_static --selftest"; fi
else skip "census probes not found"; fi
fi

printf '\n\033[1m%s\033[0m\n' "$( [ "$FAIL" = 0 ] && echo "OK: all stages that ran passed ($SKIP skipped)" || echo "FAIL: $FAIL failure(s), $SKIP skipped")"
exit $(( FAIL > 0 ))
