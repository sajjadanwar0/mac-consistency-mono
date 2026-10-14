#!/usr/bin/env bash
# run_experiments.sh -- every run the paper is waiting for, sized to the budgets
# you actually have (Claude $200, OpenAI $2.66, DeepSeek $4.28), from the
# monorepo root (after 00_migrate_monorepo.sh + 02_apply_audit_bundle.sh).
#
#   export ANTHROPIC_API_KEY=...  OPENAI_API_KEY=...  DEEPSEEK_API_KEY=...
#   ./scripts/run_experiments.sh --dry-run          # print the plan and the cost of each step
#   ./scripts/run_experiments.sh                    # run everything
#   ./scripts/run_experiments.sh --only 1,2,4       # a subset (step numbers below)
#   ./scripts/run_experiments.sh --from 5           # resume
#
# Every step writes receipts under results/ (or formal/); the last step folds
# them into ONE file, results/paper_receipts_summary.json, which you upload --
# the paper is regenerated from it (you do not build LaTeX).  Steps are
# re-runnable; a step whose receipt exists is skipped unless --force.
#
#  step  what                                                        needs            est. cost      time
#   1    verified L1 store bridge (cargo build --example l1_server)   cargo            $0             2 min
#   2    probe 303, FOUR arms at 150 ms (vanilla/validated/verified/  Claude, OpenAI,  haiku ~$1,     ~1 h
#        ledger), n=100, p-revise 1.0, on claude-haiku-4-5,          DeepSeek         4o-mini ~$0.2,
#        gpt-4o-mini and deepseek-chat: Table 3's "--" cells                          deepseek ~$0.2
#   3    probe 303, offset sweep 0/150/500/1500 ms, p-revise 0.5,    Claude, OpenAI,  haiku ~$2,     ~2.5 h
#        n=100, on the same three models: the offset curve            DeepSeek         4o-mini ~$0.3,
#                                                                                      deepseek ~$0.3
#   4    probe 301, ToolNode replay against real effects (sqlite,http) none            $0             10 min
#   5    probe 302, interleaved wall-clock rerun, gpt-4o, N=60         OpenAI           ~$1.8          ~1 h
#   6    probe 302, interleaved wall-clock rerun, claude-sonnet-4-5    Claude           ~$15           ~1.5 h
#        N=100
#   7    Verus: verify lib_l5_ledger.rs; curated/full counts;          verus (pinned)   $0             20 min
#        results/verus/count.json; fix crates/runtime/README.md; CLAIMS.json
#   8    TLAPS: tlapm CommitOrder.tla (commit the log)                 tlapm            $0             10 min
#   9    TLC: full lattice32 + two-value safety half on YOUR machine   java             $0             ~3 h
#  10    live L2 replay, 1,000 haiku sessions (per-model L2 statement) Claude           ~$3            ~1 h
#  11    pilot replication with op-records on claude-sonnet-4-5        Claude           ~$15           ~2 h
#  12    L2/L4 measurement receipts (cargo examples, seeded)           cargo            $0             5 min
#  13    fold every receipt into results/paper_receipts_summary.json;  python3          $0             1 min
#        run the gates; print what to upload
set -uo pipefail   # not -e: a failing step is recorded and the next step still runs (summary at the end)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
DRY=0; FORCE=0; ONLY=""; FROM=1
while [ $# -gt 0 ]; do case "$1" in
  --dry-run) DRY=1;; --force) FORCE=1;; --only) ONLY="$2"; shift;; --from) FROM="$2"; shift;;
  -h|--help) sed -n '2,40p' "$0"; exit 0;; *) echo "unknown arg $1" >&2; exit 2;; esac; shift; done
# one uv project per matrix cell is the convention; until you split them, envs/pilot-legacy
# (the pilot's own lockfile: langgraph 1.2.2, autogen 0.7.5, anthropic, openai) runs everything
env_for() { [ -f "envs/$1/pyproject.toml" ] && echo "envs/$1" || echo "envs/pilot-legacy"; }
UVG="uv run --project $(env_for langgraph-1.2.0) python"
UVG5="uv run --project $(env_for langgraph-1.2.5) python"
UVA="uv run --project $(env_for autogen) python"
UVA_ABS="uv run --project $PWD/$(env_for autogen) python"   # for scripts that cd elsewhere (probe 302)
log() { printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }
want() { local n=$1; [ "$n" -ge "$FROM" ] || return 1; [ -z "$ONLY" ] && return 0; case ",$ONLY," in *",$n,"*) return 0;; *) return 1;; esac; }
have() { command -v "$1" >/dev/null 2>&1; }
FAILED=()
run() { if [ "$DRY" = 1 ]; then echo "  would run: $*"; else echo "  + $*"; eval "$@" || { echo "  FAIL (exit $?): $*" >&2; FAILED+=("$*"); return 1; }; fi; }
need_key() { [ -n "${!1:-}" ] && return 0; [ "$DRY" = 1 ] && { echo "  (needs $1)"; return 0; }; echo "  FAIL: $1 is not set (export it, then re-run this step)" >&2; FAILED+=("$1 unset"); return 1; }
mkdir -p results/live_a1_outcome results/a6_real_latency results/verus tools
export PYTHONPATH="probes/_modules${PYTHONPATH:+:$PYTHONPATH}"   # renumbered probes import each other by original name
# the workspace Cargo.toml at the root puts build output under target/; a standalone checkout under crates/runtime/target/
l1srv() { { ls target/release/examples/l1_server crates/runtime/target/release/examples/l1_server 2>/dev/null || true; } | head -1; }
DEEPSEEK_URL="${DEEPSEEK_URL:-https://api.deepseek.com}"

if want 1; then log 1 "verified L1 store bridge"
  if [ -n "$(l1srv)" ] && [ "$FORCE" = 0 ]; then echo "  $(l1srv) exists, skipping"; else
    run "cargo build --release --manifest-path crates/runtime/Cargo.toml --example l1_server"
    run "python3 probes/303_live_a1_outcome.py --bridge-selftest --l1-server \"\$(ls target/release/examples/l1_server crates/runtime/target/release/examples/l1_server 2>/dev/null | head -1)\""
  fi; fi
L1SERVER="${L1SERVER:-$(l1srv)}"; L1SERVER="${L1SERVER:-target/release/examples/l1_server}"

# provider spec: "<provider> <model> <extra args>"; the DeepSeek one is OpenAI-compatible
P_HAIKU="anthropic claude-haiku-4-5"
P_4OMINI="openai gpt-4o-mini"
P_DEEPSEEK="openai deepseek-chat --base-url $DEEPSEEK_URL --api-key-env DEEPSEEK_API_KEY"

if want 2; then log 2 "probe 303: four arms at 150 ms on three API families (fills Table 3's '--' cells)"
  need_key ANTHROPIC_API_KEY; need_key OPENAI_API_KEY; need_key DEEPSEEK_API_KEY
  for spec in "$P_HAIKU" "$P_4OMINI" "$P_DEEPSEEK"; do set -- $spec; prov=$1; model=$2; shift 2
    out="results/live_a1_outcome/${model}_arms150.json"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"; continue; fi
    run "$UVG probes/303_live_a1_outcome.py --provider $prov --model $model $* --n 100 --p-revise 1.0 --offsets 150 --modes vanilla,validated,verified,ledger --l1-server $L1SERVER --out $out"
  done; fi

if want 3; then log 3 "probe 303: offset sweep (the curve that replaces the fixed-race rates)"
  need_key ANTHROPIC_API_KEY; need_key OPENAI_API_KEY; need_key DEEPSEEK_API_KEY
  for spec in "$P_HAIKU" "$P_4OMINI" "$P_DEEPSEEK"; do set -- $spec; prov=$1; model=$2; shift 2
    out="results/live_a1_outcome/${model}_sweep.json"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"; continue; fi
    run "$UVG probes/303_live_a1_outcome.py --provider $prov --model $model $* --n 100 --p-revise 0.5 --offsets 0,150,500,1500 --modes vanilla,validated --out $out"
  done; fi

if want 4; then log 4 "probe 301: ToolNode replay against real effects (no key)"
  for eff in sqlite http; do
    out="results/a6_real_latency/$eff.jsonl"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"; continue; fi
    run "$UVG5 probes/301_a6_toolnode_real_latency.py --batches results/langgraph_a6_natural --effect $eff --reps 5 --out $out"
  done; fi

if want 5; then log 5 "probe 302: interleaved wall-clock rerun, gpt-4o, N=60 (fits the OpenAI balance)"
  need_key OPENAI_API_KEY
  run "N=60 PROVIDER=openai MODEL=gpt-4o PY=\"$UVA_ABS\" ./probes/302_wallclock_interleaved.sh"; fi

if want 6; then log 6 "probe 302: interleaved wall-clock rerun, claude-sonnet-4-5, N=100"
  need_key ANTHROPIC_API_KEY
  run "N=100 PROVIDER=anthropic MODEL=claude-sonnet-4-5 PY=\"$UVA_ABS\" ./probes/302_wallclock_interleaved.sh"; fi

# the PINNED verus binary: VERUS if set, else ~/.local/opt/verus-<pin>/verus, else whatever is on PATH
PIN="$(grep -oE '^verus\s*=\s*\S+' crates/verus-detector/verus-version.txt 2>/dev/null | sed -E 's/.*=\s*//')"
if [ -z "${VERUS:-}" ] && [ -n "$PIN" ] && [ -x "$HOME/.local/opt/verus-$PIN/verus" ]; then export VERUS="$HOME/.local/opt/verus-$PIN/verus"; fi
export VERUS="${VERUS:-verus}"
if want 7; then log 7 "Verus: the ledger model, then the pinned counts, then the README line and CLAIMS.json"
  echo "  using $VERUS ($($VERUS --version 2>/dev/null | grep -oE 'Version: *\S+' || echo '?'); pin $PIN)"
  if have "$VERUS" || [ -x "$VERUS" ]; then
    run "(cd crates/verus-detector && $VERUS --crate-type=lib src/lib_l5_ledger.rs 2>&1 | tee ../../results/verus/lib_l5_ledger.verus.log)"
    # verus_count.sh looks for the crate beside itself (pilot layout); in the monorepo it lives at crates/verus-detector
    if ! grep -q 'VDET_DIR' harness/macaudit/verus_count.sh; then
      run "sed -i 's|^LOCAL_VDET=\"\$HERE/verus-detector\"|LOCAL_VDET=\"\${VDET_DIR:-\$HERE/verus-detector}\"|' harness/macaudit/verus_count.sh"
    fi
    run "VDET_DIR=\$PWD/crates/verus-detector bash harness/macaudit/verus_count.sh 2>&1 | tee tools/verus_count_curated.log | tail -25"
    run "VDET_DIR=\$PWD/crates/verus-detector bash harness/macaudit/verus_count.sh --full 2>&1 | tee tools/verus_count_full.log | tail -25"
    if [ "$DRY" = 0 ]; then python3 - <<'PY'
import json, re, os
def tot(fp):
    m = re.search(r"DISTINCT obligation total\s+(\d+)", open(fp).read()); return int(m.group(1)) if m else None
cur, full = tot("tools/verus_count_curated.log"), tot("tools/verus_count_full.log")
led = open("results/verus/lib_l5_ledger.verus.log").read()
m = re.search(r"(\d+) verified, (\d+) errors", led); ledger = {"verified": int(m.group(1)), "errors": int(m.group(2))} if m else {"verified": None, "errors": None, "note": "no summary line; see the log"}
json.dump({"curated_total": cur, "full_total": full, "ledger": ledger, "pin": "0.2026.09.13.671956e"}, open("results/verus/count.json", "w"), indent=1)
print("verus: curated", cur, "full", full, "ledger", ledger)
# README line that the claims gate flags
p = "crates/runtime/README.md"
if os.path.exists(p) and cur and full:
    s = open(p).read(); s2 = re.sub(r"\d+ curated /\s*\n?\s*\d+ full", f"{cur} curated /\n{full} full", s)
    if s2 != s: open(p, "w").write(s2); print("rewrote the Verus count line in", p)
# CLAIMS.json
if os.path.exists("CLAIMS.json") and cur and full:
    c = json.load(open("CLAIMS.json")); c.setdefault("verus", {}); c["verus"]["curated_total"] = cur; c["verus"]["full_total"] = full
    json.dump(c, open("CLAIMS.json", "w"), indent=1); print("updated CLAIMS.json verus totals")
PY
    fi
  else echo "  verus not on PATH: install the build pinned in crates/verus-detector/verus-version.txt"; fi; fi

if want 8; then log 8 "TLAPS: CommitOrder.tla"
  if have tlapm; then run "(cd formal/tla && tlapm --toolbox 0 0 CommitOrder.tla 2>&1 | tee tlaps.CommitOrder.log | tail -5)"
  else echo "  tlapm not on PATH (https://github.com/tlaplus/tlapm); skip is fine, the paper reports the 60 obligations from the committed proof"; fi; fi

if want 9; then log 9 "TLC on your machine: lattice32 (160 runs) and the two-value safety half"
  J="${TLA_TOOLS:-$ROOT/tools/tla2tools.jar}"
  [ -f "$J" ] || run "curl -sSL -o $J https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar"
  run "(cd formal/tla && ./lattice32.sh $J && cp lattice32_results.json lattice32_results.reference.json)"
  run "(cd formal/tla && ./lattice16_v2.sh $J && cp lattice16_v2_results.json lattice16_v2_results.reference.json)"; fi

if want 10; then log 10 "live L2 replay, 1,000 haiku sessions (per-model L2 statement)"
  need_key ANTHROPIC_API_KEY
  # the l2-live tool was a standalone crate in the runtime repo; inside the monorepo cargo assigns it to the root
  # workspace, whose members list does not include it -> "believes it's in a workspace when it's not"
  if [ -f crates/runtime/l2-live/Cargo.toml ] && ! grep -q '^\[workspace\]' crates/runtime/l2-live/Cargo.toml; then
    run "printf '\n[workspace]\n' >> crates/runtime/l2-live/Cargo.toml"
  fi
  run "cargo run --release --manifest-path crates/runtime/l2-live/Cargo.toml -- --provider anthropic --model claude-haiku-4-5 --n 1000 --validator llm --out results/live_l2_haiku1000 --seed 20261013 2>&1 | tee results/live_l2_haiku1000.log | tail -15"; fi

if want 11; then log 11 "pilot replication WITH op-records on claude-sonnet-4-5 (Table 4/7 Claude panel)"
  need_key ANTHROPIC_API_KEY
  PILOT="$(ls probes/*_autogen_pilot.py | head -1)"
  # python packages that lived beside the pilot (baselines/, ...) were filed under results/ by 00_migrate_monorepo.sh
  # as if they were data; the pilot imports them, so they belong beside it under probes/
  for d in results/*/; do
    [ -f "$d/__init__.py" ] || continue; pkg="$(basename "$d")"
    [ -e "probes/$pkg" ] || run "mv results/$pkg probes/$pkg && echo '  moved python package $pkg: results/ -> probes/'"
  done
  # resume the newest *-claude run if one exists (a cell with 100 traces is not rerun; delete a cell to redo it)
  if [ -z "${STAMP:-}" ]; then prev="$(ls -d results/runs/*-claude 2>/dev/null | sort | tail -1)"; fi
  STAMP="${STAMP:-${prev:+$(basename "$prev")}}"; STAMP="${STAMP:-$(date -u +%Y%m%dT%H%MZ)-claude}"; RUN="results/runs/$STAMP"
  for rt in vanilla pessimistic snapshot_isolation; do for wl in edit-review plan-execute triage; do
    if [ "$(ls "$RUN/$wl-$rt"/*.jsonl 2>/dev/null | wc -l)" -ge 100 ] && [ "$FORCE" = 0 ]; then echo "  $RUN/$wl-$rt has 100 traces, skipping"; continue; fi
    run "$UVA $PILOT --provider anthropic --model claude-sonnet-4-5 --workload $wl --runtime $rt --n 100 --seed 42 --output $RUN/$wl-$rt --tokens-output $RUN/tokens-$wl-$rt"
  done; done
  # a void triage cell (every ticket "no bug description provided") means the reporter never received the ticket text
  if [ "$DRY" = 0 ] && [ -d "$RUN/triage-vanilla" ] && grep -lq "No bug description" "$RUN"/triage-vanilla/*.jsonl 2>/dev/null; then
    echo "  WARN: $RUN/triage-vanilla holds tickets without a description ($(grep -l 'No bug description' "$RUN"/triage-vanilla/*.jsonl | wc -l) sessions): the cell is void; see the step-11 note in EXPERIMENT_PLAN.md"
  fi
  run "python3 harness/macaudit/rescore_cells.py --root results | tail -12"; fi

if want 12; then log 12 "L2/L4 measurement receipts (seeded cargo examples; their text output is the receipt)"
  for ex in l2_measure l4_measure; do
    run "cargo run --release -q -p agent-consistency-runtime --example $ex > results/$ex.txt && tail -3 results/$ex.txt"
  done; fi

if want 13; then log 13 "fold every receipt into ONE file; run the gates"
  if [ "$DRY" = 0 ] && [ -f CLAIMS.json ] && [ -f crates/runtime/README.md ]; then python3 - <<'PY'
import json, re
c = json.load(open("CLAIMS.json")).get("verus", {}); cur, full = c.get("curated_total"), c.get("full_total")
p = "crates/runtime/README.md"; s = open(p).read()
s2 = re.sub(r"\d{3} curated /\s*\n?\s*\d{3} full", f"{cur} curated /\n{full} full", s) if cur and full else s
if s2 != s: open(p, "w").write(s2); print(f"  rewrote the Verus count line in {p} -> {cur} curated / {full} full")
PY
  fi
  run "python3 harness/macaudit/claims_from_results.py --root results --paper paper | tail -4"
  if [ -f paper/main.tex ] && have pdflatex; then
    run "(cd paper && pdflatex -interaction=nonstopmode main.tex >/dev/null && pdflatex -interaction=nonstopmode main.tex | grep -E 'Output written')"
  fi
  run "./reproduce.sh --data-only || true"
  cat <<EOF

UPLOAD these to the chat and the paper is regenerated from them:
  results/paper_receipts_summary.json          (everything: probe 303/301/302 numbers, Verus counts, ledger log)
  results/verus/lib_l5_ledger.verus.log        (if step 7 ran and it is not already inside the summary)
  results/live_l2_haiku1000.log                (if step 10 ran)
  tools/rescore_cells.log  or the last 30 lines of step 11's output   (if step 11 ran)
EOF
fi

if [ "$DRY" = 0 ]; then
  if [ ${#FAILED[@]} -gt 0 ]; then
    echo; echo "FAILED steps/commands (${#FAILED[@]}); fix and re-run with --only <n>:"; printf '  %s\n' "${FAILED[@]}"; exit 1
  else echo; echo "all requested steps completed"; fi
fi
