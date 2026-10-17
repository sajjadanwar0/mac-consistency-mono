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
#  --- added 2026-10-14 (the second hostile round: verified bytes in the scoring path, arm timing, the
#      ledger in a world, at-most-once, replication) ---
#  14    cargo: build the analyser (A1 by the VERIFIED detector) and     cargo            $0             5 min
#        l3_server; verified_bytes_gate; verified_scorer_gate over
#        EVERY published A1 cell -> tools/verified_scorer.json
#  15    probe 301 with --l3-server: ToolNode replay, real effects,     none             $0             15 min
#        third arm = verified L3 bytes deciding the release order
#  16    TLC: Duplication.tla (predicate D, witness + dedup)            java             $0             1 min
#  17    probe 303 --interleave --runs 3, five arms (vanilla, validated, Claude, OpenAI,  haiku ~$4,     ~4 h
#        verified, ledger, ledger_verified), n=100, 150 ms, on haiku,   DeepSeek         4o-mini ~$0.8,
#        gpt-4o-mini, deepseek-chat -> Table 3 replicated rows                           deepseek ~$0.8
#  18    probe 304: the ledger in a WORLD (consumer, cancellation,      Claude, OpenAI,  haiku ~$1.5,   ~1.5 h
#        fallible compensator, two revisions), n=100, three arms,       DeepSeek         4o-mini ~$0.3,
#        on the same three families                                                      deepseek ~$0.3
#  19    arm_timing + live_runs_aggregate + hypothesis_gates --tex      python3          $0             2 min
#        (claims_results.tex gets the new macros; then run 13 again)
#  20    TLC: NoA1 lattice points at MaxOps=3, two values, one cell     java             $0             ~10 min
#  21    probe 304 again: ATOMIC ledger registration (3 arms x 3        Claude, OpenAI,  haiku ~$2,     ~2.5 h
#        families) + the ledger arm with a 5 s consumer window           DeepSeek         4o-mini ~$0.5, deepseek ~$0.5
#  22    probe 302 REFUSAL-PRICE study, claude-sonnet-4-5: edit-review   Claude           ~$15-20        ~2.5 h
#        and triage, five arms interleaved per session (vanilla,
#        pessimistic:drop, pessimistic:retry, SI:drop, SI:retry), the
#        pilot's tools now telling the model REFUSED (2026-10-17); N=100
#  23    probe 304 with the ledger's BOOKKEEPING in the verified bytes  Claude, OpenAI,  haiku ~$2,     ~2.5 h
#        (lib_l5_exec.rs behind l5_server; --ledger exec), atomic,     DeepSeek,        4o-mini ~$0.5,
#        three families -> results/ledger_world_exec/                  cargo, verus (7) deepseek ~$0.5
#  24    probe 302 refusal-price CONTROL on claude-sonnet-4-5: the       Claude           ~$10           ~1.5 h
#        REFUSED result addressed to the refused agent (the step-22
#        text was broadcast unaddressed and the unrefused agent
#        repeated its last step); vanilla / pessimistic:drop /
#        pessimistic:retry / SI:drop, edit-review + triage, N=100
#  Claude-side reruns that existed before: 6 (probe 302 on sonnet, ~$15-25) and 11 (the pilot replication
#  with op-records; its triage cells are void and must be DELETED and rerun with the seeded-ticket reporter).
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
# the delivered files of 2026-10-14/15 must be in place before a step means anything: a step that runs on the previous
# version of a file reproduces the previous failure (2026-10-15: the mv block had not been run). Defined HERE, with the
# other helpers: bash resolves a function at call time, and the 2026-10-15 log shows "delivered: command not found" at
# steps 11 and 6 because the definition sat below their call sites.
delivered() { # delivered <file> <marker> <what>
  if ! grep -q -- "$2" "$1" 2>/dev/null; then
    echo "  FAIL: $1 is not the delivered version ($3 missing) -- run the mv block from the chat, then re-run" >&2
    FAILED+=("$1 not updated"); return 1
  fi
}
mkdir -p results/live_a1_outcome results/a6_real_latency results/verus tools
export PYTHONPATH="$PWD/probes/_modules${PYTHONPATH:+:$PYTHONPATH}"   # renumbered probes import each other by original name (absolute: probe 302 cds into probes/)
# the pilot's pessimistic / snapshot_isolation runtimes are `baselines.runtimes.*`: a namespace package (no __init__.py)
# that the migration filed under results/; it imports only when its PARENT directory is on sys.path (2026-10-14: the
# six Claude pessimistic/SI cells failed with ModuleNotFoundError for want of this; the pilot now also locates it itself)
BASELINES_DIR="$(find . \( -path ./.venv -o -path '*/.venv' -o -path '*/target' -o -path ./.git \) -prune -o -type d -name baselines -print 2>/dev/null | head -1)"
[ -n "$BASELINES_DIR" ] && export PYTHONPATH="$(cd "$(dirname "$BASELINES_DIR")" && pwd)${PYTHONPATH:+:$PYTHONPATH}"
# python packages that lived beside the pilot (baselines/ ...) were filed under results/ by 00_migrate_monorepo.sh
# as if they were data; the pilot imports them, so they belong beside it under probes/ (steps 5, 6, 11 need them)
pilot_packages() {
  # every top-level module the pilot imports that is neither beside it, nor an alias in probes/_modules, nor
  # installed in the env: find the package directory wherever the migration filed it and move it beside the probes
  local pilot pkg src
  pilot="$(ls probes/*_autogen_pilot.py 2>/dev/null | head -1)"; [ -n "$pilot" ] || return 0
  for pkg in $(grep -ohE '^\s*(from|import) [A-Za-z_][A-Za-z0-9_]*' "$pilot" | awk '{print $2}' | sort -u); do
    [ -e "probes/$pkg" ] || [ -e "probes/$pkg.py" ] || [ -e "probes/_modules/$pkg.py" ] && continue
    src="$(find . \( -path ./.venv -o -path '*/.venv' -o -path '*/target' -o -path ./.git -o -path ./probes \) -prune -o -type d -name "$pkg" -print 2>/dev/null | head -1)"
    if [ -n "$src" ] && [ -f "$src/__init__.py" ]; then
      run "mv $src probes/$pkg && echo '  moved python package $pkg: $src -> probes/$pkg'"
    fi
  done
}
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
  need_key OPENAI_API_KEY; pilot_packages
  st="$(ls -d results/runs/*-interleaved-gpt-4o 2>/dev/null | sort | tail -1)"; st="${st:+$(basename "$st")}"; st="${st:-$(date -u +%Y%m%dT%H%MZ)-interleaved-gpt-4o}"
  run "N=60 PROVIDER=openai MODEL=gpt-4o STAMP=$st PY=\"$UVA_ABS\" ./probes/302_wallclock_interleaved.sh"; fi

if want 6; then log 6 "probe 302: interleaved wall-clock rerun, claude-sonnet-4-5, N=100"
  need_key ANTHROPIC_API_KEY; pilot_packages
  delivered probes/103_autogen_pilot.py _locate_baselines "the baselines locator" || true
  st="$(ls -d results/runs/*-interleaved-claude-sonnet-4-5 2>/dev/null | sort | tail -1)"; st="${st:+$(basename "$st")}"; st="${st:-$(date -u +%Y%m%dT%H%MZ)-interleaved-claude-sonnet-4-5}"
  run "N=100 PROVIDER=anthropic MODEL=claude-sonnet-4-5 STAMP=$st PY=\"$UVA_ABS\" ./probes/302_wallclock_interleaved.sh"; fi

# the PINNED verus binary: VERUS if set, else ~/.local/opt/verus-<pin>/verus, else whatever is on PATH
PIN="$(grep -oE '^verus\s*=\s*\S+' crates/verus-detector/verus-version.txt 2>/dev/null | sed -E 's/.*=\s*//')"
if [ -z "${VERUS:-}" ] && [ -n "$PIN" ] && [ -x "$HOME/.local/opt/verus-$PIN/verus" ]; then export VERUS="$HOME/.local/opt/verus-$PIN/verus"; fi
export VERUS="${VERUS:-verus}"
if want 7; then log 7 "Verus: the ledger model, then the pinned counts, then the README line and CLAIMS.json"
  VVER="$($VERUS --version 2>/dev/null | grep -oE 'Version: *\S+' | sed 's/Version: *//')"; export VVER_FOR_COUNT="$VVER"
  echo "  using $VERUS (version ${VVER:-?}; pin $PIN)"
  # 2026-10-17: the step ran once with a May build found on PATH (VERUS=~/bin/verus-pinned, 0.2026.05.03): every file
  # "failed", the counts came out 160/181 and the python block below rewrote CLAIMS.json, crates/runtime/README.md and
  # results/verus/count.json with them. A version that does not match the pin is a HARD STOP, before anything is written.
  if [ -n "$PIN" ] && [ -n "$VVER" ] && [ "$VVER" != "$PIN" ]; then
    echo "  FAIL: $VERUS is Verus $VVER, the pin is $PIN. Nothing was run or written. Fix with:"
    echo "        export VERUS=\$HOME/.local/opt/verus-$PIN/verus     # then: ./scripts/run_experiments.sh --only 7"
    echo "        (if that path does not exist, install the pinned build there first; a stale VERUS in your shell profile overrides the pin)"
    FAILED+=("verus version $VVER != pin $PIN")
  elif have "$VERUS" || [ -x "$VERUS" ]; then
    run "(cd crates/verus-detector && $VERUS --crate-type=lib src/lib_l5_ledger.rs 2>&1 | tee ../../results/verus/lib_l5_ledger.verus.log)"
    # 2026-10-17: the EXEC ledger (bookkeeping behind examples/l5_server.rs, probes/304 --ledger exec); zero errors required,
    # the count is reported (pinned at "?" until this run). A failure here is a proof defect in lib_l5_exec.rs: upload the log.
    run "(cd crates/verus-detector && $VERUS --crate-type=lib src/lib_l5_exec.rs 2>&1 | tee ../../results/verus/lib_l5_exec.verus.log)"
    if [ "$DRY" = 0 ] && ! grep -qE '[0-9]+ verified, 0 errors' results/verus/lib_l5_exec.verus.log; then echo "  FAIL: lib_l5_exec.rs did not verify (see results/verus/lib_l5_exec.verus.log)"; FAILED+=("verus lib_l5_exec.rs"); fi
    # verus_count.sh looks for the crate beside itself (pilot layout); in the monorepo it lives at crates/verus-detector
    if ! grep -q 'VDET_DIR' harness/macaudit/verus_count.sh; then
      run "sed -i 's|^LOCAL_VDET=\"\$HERE/verus-detector\"|LOCAL_VDET=\"\${VDET_DIR:-\$HERE/verus-detector}\"|' harness/macaudit/verus_count.sh"
    fi
    run "VDET_DIR=\$PWD/crates/verus-detector bash harness/macaudit/verus_count.sh 2>&1 | tee tools/verus_count_curated.log | tail -25"
    run "VDET_DIR=\$PWD/crates/verus-detector bash harness/macaudit/verus_count.sh --full 2>&1 | tee tools/verus_count_full.log | tail -25"
    # the counts are folded into CLAIMS.json / README / count.json ONLY when both count runs were complete (no file failed
    # to verify, no version mismatch); a partial count must never overwrite the pinned totals
    if [ "$DRY" = 0 ] && ! grep -q "INCOMPLETE\|does not match the pin" tools/verus_count_curated.log tools/verus_count_full.log; then python3 - <<'PY'
import json, re, os
def tot(fp):
    m = re.search(r"DISTINCT obligation total\s+(\d+)", open(fp).read()); return int(m.group(1)) if m else None
cur, full = tot("tools/verus_count_curated.log"), tot("tools/verus_count_full.log")
led = open("results/verus/lib_l5_ledger.verus.log").read()
m = re.search(r"(\d+) verified, (\d+) errors", led); ledger = {"verified": int(m.group(1)), "errors": int(m.group(2))} if m else {"verified": None, "errors": None, "note": "no summary line; see the log"}
json.dump({"curated_total": cur, "full_total": full, "ledger": ledger, "pin": "0.2026.09.13.671956e",
           "verus_version": os.environ.get("VVER_FOR_COUNT", "")}, open("results/verus/count.json", "w"), indent=1)
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
    else echo "  counts NOT folded into CLAIMS.json / README / count.json: a count run was incomplete or the version did not match the pin"; fi
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
  delivered probes/103_autogen_pilot.py _locate_baselines "the baselines locator" || true
  PILOT="$(ls probes/*_autogen_pilot.py | head -1)"; pilot_packages
  # resume the newest *-claude run if one exists (a cell with 100 traces is not rerun; delete a cell to redo it)
  if [ -z "${STAMP:-}" ]; then prev="$(ls -d results/runs/*-claude 2>/dev/null | sort | tail -1)"; fi
  STAMP="${STAMP:-${prev:+$(basename "$prev")}}"; STAMP="${STAMP:-$(date -u +%Y%m%dT%H%MZ)-claude}"; RUN="results/runs/$STAMP"
  for rt in vanilla pessimistic snapshot_isolation; do for wl in edit-review plan-execute triage; do
    if [ "$(ls "$RUN/$wl-$rt"/*.jsonl 2>/dev/null | wc -l)" -ge 100 ] && [ "$FORCE" = 0 ]; then echo "  $RUN/$wl-$rt has 100 traces, skipping"; continue; fi
    run "$UVA $PILOT --provider anthropic --model claude-sonnet-4-5 --workload $wl --runtime $rt --n 100 --seed 42 --output $RUN/$wl-$rt --tokens-output $RUN/tokens-$wl-$rt"
  done; done
  # a void triage cell (every ticket "no bug description provided"): the reporter was never given a bug to report;
  # since 2026-10-14 the pilot hands it one (--seeded-tickets, default on) -- a cell recorded under the old protocol
  # is detected here and must be deleted and rerun:  rm -r "$RUN"/triage-*  then  --only 11
  for cell in "$RUN"/triage-*; do
    [ -d "$cell" ] || continue
    if [ "$DRY" = 0 ] && grep -lqi "no bug description" "$cell"/*.jsonl 2>/dev/null; then
      echo "  WARN: $cell holds tickets without a description ($(grep -li 'no bug description' "$cell"/*.jsonl | wc -l) sessions): VOID under the old protocol -- rm -r $cell and rerun --only 11"
    fi
  done
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
  # the PDFs are built by the author from the uploaded receipts; this machine only folds receipts and runs gates.
  # BUILD_PDF=1 opts in to a local pdflatex pass (never part of the default run order).
  if [ "${BUILD_PDF:-0}" = 1 ] && [ -f paper/main.tex ] && have pdflatex; then
    run "(cd paper && pdflatex -interaction=nonstopmode main.tex >/dev/null && pdflatex -interaction=nonstopmode main.tex | grep -E 'Output written')"
  fi
  run "./reproduce.sh --data-only || true"
  cat <<EOF

UPLOAD these to the chat and the paper is regenerated from them:
  results/paper_receipts_summary.json          (everything: probe 303/301/302/304 numbers, Verus counts, ledger log, gates)
  tools/verified_scorer.json  tools/verified_scorer.log  tools/arm_timing.log  tools/live_runs.log  tools/hypothesis_gates.log   (step 14 / 19 receipts)
  formal/tla/tlc.Duplication.log               (step 16)
  results/verus/lib_l5_ledger.verus.log        (if step 7 ran and it is not already inside the summary)
  results/live_l2_haiku1000.log                (if step 10 ran)
  tools/rescore_cells.log  or the last 30 lines of step 11's output   (if step 11 ran)
  results/runs/*-interleaved*/order.tsv            (if step 5/6 ran: the completion stamps, the wall-clock receipt of a run whose sidecars were lost)
  formal/tla/lattice16_a1_maxops3_c1_results.json  (if step 20 ran: the NoA1 matrix at MaxOps=3)
  results/ledger_world_atomic/  results/ledger_world_window5000/   (if step 21 ran: zip-free -- upload the six .json files)
NOTE: step 14 (the verified scorer) scores the cells that exist when it runs. If steps 11 or 6 produced cells after
      step 14 (the 2026-10-15 order was 14, 18, 11, 6), re-run:  ./scripts/run_experiments.sh --only 14 19
EOF
fi

if want 14; then log 14 "cargo: the analyser scores A1 with the VERIFIED detector; l3_server; the two bytes gates"
  delivered crates/analyser/src/oprecord.rs normalize_agent_key "the agent/agent_id reader fix" || true
  run "bash harness/macaudit/verified_bytes_gate.sh"
  run "cargo build --release -p mac-analyser 2>&1 | tail -3"
  run "cargo build --release --manifest-path crates/runtime/Cargo.toml --example l3_server 2>&1 | tail -3"
  run "cargo build --release --manifest-path crates/runtime/Cargo.toml --example l5_server 2>&1 | tail -3"
  # the fold refuses ledger_world_exec receipts whose server sha256 is not this one (a stand-in cannot pass as the bytes)
  run "mkdir -p results/verus && touch results/verus/l5_server.sha256 && sha=\$(sha256sum target/release/examples/l5_server | cut -d' ' -f1) && (grep -q \"\$sha\" results/verus/l5_server.sha256 || echo \"\$sha  target/release/examples/l5_server  \$(date -u +%FT%TZ)\" >> results/verus/l5_server.sha256) && tail -3 results/verus/l5_server.sha256"
  run "cargo test --release -p agent-consistency-runtime --lib detect_a1_verified 2>&1 | grep -E '^test |test result'"
  run "cargo test --release -p mac-analyser 2>&1 | grep -E '^test |test result'"
  AN="$( { ls target/release/analyser crates/analyser/target/release/analyser 2>/dev/null || true; } | head -1)"
  run "python3 harness/macaudit/verified_scorer_gate.py --analyser ${AN:-target/release/analyser} --root results --out tools/verified_scorer.json 2>&1 | tee tools/verified_scorer.log | tail -8"; fi

L3SERVER="${L3SERVER:-$( { ls target/release/examples/l3_server crates/runtime/target/release/examples/l3_server 2>/dev/null || true; } | head -1)}"
if want 15; then log 15 "probe 301 with the verified L3 sequencer deciding the release order (no key)"
  [ -n "$L3SERVER" ] || { echo "  FAIL: l3_server not built (run --only 14)"; FAILED+=("l3_server missing"); }
  for eff in sqlite http; do
    out="results/a6_real_latency/${eff}_verified.jsonl"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"; continue; fi
    run "$UVG5 probes/301_a6_toolnode_real_latency.py --batches results/langgraph_a6_natural --effect $eff --reps 5 --l3-server $L3SERVER --out $out"
  done
  # claims_from_results.py reads {sqlite,http}.jsonl (step 4, the committed baseline) AND {sqlite,http}_verified.jsonl (this step)
  fi

if want 16; then log 16 "TLC: Duplication.tla (predicate D: witness, divergent witness, idempotency guard)"
  J="${TLA_TOOLS:-$ROOT/tools/tla2tools.jar}"
  [ -f "$J" ] || run "curl -sSL -o $J https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar"
  run "(cd formal/tla && ./check_duplication.sh $J 2>&1 | grep -v JAVA_TOOL_OPTIONS | tee tlc.Duplication.log | tail -4)"; fi

if want 20; then log 20 "TLC: the sixteen NoA1 lattice points at MaxOps=3, two values, one cell (where the supersession witness is reachable; no key)"
  J="${TLA_TOOLS:-$ROOT/tools/tla2tools.jar}"
  [ -f "$J" ] || run "curl -sSL -o $J https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar"
  run "(cd formal/tla && CELLS=1 TLA_TOOLS=$J ./lattice16_a1_maxops3.sh 2>&1 | grep -v JAVA_TOOL_OPTIONS | tail -18)"; fi

if want 17; then log 17 "probe 303 --interleave --runs 3: five arms per session, three families (Table 3 replicated rows)"
  need_key ANTHROPIC_API_KEY; need_key OPENAI_API_KEY; need_key DEEPSEEK_API_KEY
  for spec in "$P_HAIKU" "$P_4OMINI" "$P_DEEPSEEK"; do set -- $spec; prov=$1; model=$2; shift 2
    out="results/live_a1_outcome/${model}_arms150i.json"
    if [ -f "results/live_a1_outcome/${model}_arms150i.run2.json" ] && [ "$FORCE" = 0 ]; then echo "  ${model}_arms150i.run{0,1,2}.json exist, skipping"; continue; fi
    run "$UVG probes/303_live_a1_outcome.py --provider $prov --model $model $* --n 100 --p-revise 1.0 --offsets 150 --modes vanilla,validated,verified,ledger,ledger_verified --interleave --runs 3 --seed 20261015 --l1-server $L1SERVER --out $out"
  done; fi

if want 18; then log 18 "probe 304: the ledger in a world (consumer, cancellation, fallible compensator, two revisions)"
  need_key ANTHROPIC_API_KEY; need_key OPENAI_API_KEY; need_key DEEPSEEK_API_KEY
  delivered probes/304_ledger_world.py "--compensator" "the --compensator switch" || true
  mkdir -p results/ledger_world
  # a receipt without a "compensator" field is the FIRST run (2026-10-14, compensator `latest`: one tracked confirmation,
  # model call between cancel and rebook); the world check caught both flaws, so those receipts are archived -- never
  # deleted: the paper cites them -- and the cell is re-run with the corrected compensator (--compensator all, the default)
  for f in results/ledger_world/*.json; do
    [ -f "$f" ] || continue
    if ! grep -q '"compensator"' "$f"; then
      mkdir -p results/ledger_world_v1_latest_conf
      run "mv '$f' results/ledger_world_v1_latest_conf/ && { [ -f '${f%.json}.records.jsonl' ] && mv '${f%.json}.records.jsonl' results/ledger_world_v1_latest_conf/ || true; } && echo '  archived first-run receipt $(basename "$f") (compensator latest)'"
    fi
  done
  for spec in "$P_HAIKU" "$P_4OMINI" "$P_DEEPSEEK"; do set -- $spec; prov=$1; model=$2; shift 2
    out="results/ledger_world/${model}.json"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"; continue; fi
    run "$UVG probes/304_ledger_world.py --provider $prov --model $model $* --n 100 --p-revise 1.0 --offset-ms 150 --revisions 2 --second-gap-ms 800 --modes validated,ledger,ledger_norollback --p-cancel-fail 0.1 --p-rebook-fail 0.1 --consumer-max-ms 1500 --seed 20261014 --compensator all --out $out"
  done; fi

if want 21; then log 21 "probe 304 with ATOMIC ledger registration (three families) + a 5 s consumer window (ledger arm)"
  need_key ANTHROPIC_API_KEY; need_key OPENAI_API_KEY; need_key DEEPSEEK_API_KEY
  delivered probes/304_ledger_world.py "--registration" "the atomic-registration switch" || true
  delivered probes/303_live_a1_outcome.py "LEDGER_REGISTRATION" "the atomic ledgered store" || true
  mkdir -p results/ledger_world_atomic results/ledger_world_window5000
  for spec in "$P_HAIKU" "$P_4OMINI" "$P_DEEPSEEK"; do set -- $spec; prov=$1; model=$2; shift 2
    out="results/ledger_world_atomic/${model}.json"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"
    else run "$UVG probes/304_ledger_world.py --provider $prov --model $model $* --n 100 --p-revise 1.0 --offset-ms 150 --revisions 2 --second-gap-ms 800 --modes validated,ledger,ledger_norollback --p-cancel-fail 0.1 --p-rebook-fail 0.1 --consumer-max-ms 1500 --seed 20261014 --compensator all --registration atomic --out $out"; fi
    out="results/ledger_world_window5000/${model}.json"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"
    else run "$UVG probes/304_ledger_world.py --provider $prov --model $model $* --n 100 --p-revise 1.0 --offset-ms 150 --revisions 2 --second-gap-ms 800 --modes ledger --p-cancel-fail 0.1 --p-rebook-fail 0.1 --consumer-max-ms 5000 --seed 20261014 --compensator all --registration atomic --out $out"; fi
  done; fi

if want 22; then log 22 "probe 302 refusal-price study on claude-sonnet-4-5: vanilla / pessimistic:drop / pessimistic:retry / SI:drop / SI:retry, edit-review + triage, N=100"
  need_key ANTHROPIC_API_KEY; pilot_packages
  delivered probes/103_autogen_pilot.py "ON_ABORT" "the truthful REFUSED tool results and --on-abort" || true
  delivered probes/302_wallclock_interleaved.sh "ARMS_STR" "the policy arms" || true
  st="$(ls -d results/runs/*-refusal-claude-sonnet-4-5 2>/dev/null | sort | tail -1)"; st="${st:+$(basename "$st")}"; st="${st:-$(date -u +%Y%m%dT%H%MZ)-refusal-claude-sonnet-4-5}"
  run "ARMS=\"vanilla pessimistic:drop pessimistic:retry snapshot_isolation:drop snapshot_isolation:retry\" WORKLOADS=\"edit-review triage\" N=100 PROVIDER=anthropic MODEL=claude-sonnet-4-5 STAMP=$st PY=\"$UVA_ABS\" ./probes/302_wallclock_interleaved.sh"
  echo "  UPLOAD after this step: the whole directory results/runs/$st (zip it) -- the fold reads its sidecars, refusals.jsonl and order.tsv"; fi

if want 24; then log 24 "probe 302 refusal-price CONTROL on claude-sonnet-4-5: REFUSED addressed to the refused agent; vanilla / pessimistic:drop / pessimistic:retry / SI:drop, edit-review + triage, N=100"
  need_key ANTHROPIC_API_KEY; pilot_packages
  delivered probes/103_autogen_pilot.py "REFUSAL_ADDRESSED" "the addressed REFUSED text (--refusal-addressed)" || true
  delivered probes/302_wallclock_interleaved.sh "REFUSAL_ADDRESSED" "the REFUSAL_ADDRESSED switch" || true
  st="$(ls -d results/runs/*-refusal-addressed-claude-sonnet-4-5 2>/dev/null | sort | tail -1)"; st="${st:+$(basename "$st")}"; st="${st:-$(date -u +%Y%m%dT%H%MZ)-refusal-addressed-claude-sonnet-4-5}"
  run "REFUSAL_ADDRESSED=1 ARMS=\"vanilla pessimistic:drop pessimistic:retry snapshot_isolation:drop\" WORKLOADS=\"edit-review triage\" N=100 PROVIDER=anthropic MODEL=claude-sonnet-4-5 STAMP=$st PY=\"$UVA_ABS\" ./probes/302_wallclock_interleaved.sh"
  echo "  UPLOAD after this step: the whole directory results/runs/$st (zip it) -- the fold reads its sidecars, refusals.jsonl, protocol.json and order.tsv"; fi

if want 23; then log 23 "probe 304 with the ledger's bookkeeping in the VERIFIED bytes (--ledger exec; l5_server), atomic registration, three families"
  need_key ANTHROPIC_API_KEY; need_key OPENAI_API_KEY; need_key DEEPSEEK_API_KEY
  L5="$( { ls target/release/examples/l5_server crates/runtime/target/release/examples/l5_server 2>/dev/null || true; } | head -1)"
  [ -n "$L5" ] || { echo "  FAIL: l5_server not built (run --only 14)"; FAILED+=("l5_server missing"); }
  if [ "$DRY" = 0 ] && ! grep -qE '[0-9]+ verified, 0 errors' results/verus/lib_l5_exec.verus.log 2>/dev/null; then
    echo "  WARN: results/verus/lib_l5_exec.verus.log does not show a zero-error verification (run --only 7); the run proceeds but the paper will call these bytes a port until it does"; fi
  mkdir -p results/ledger_world_exec
  for spec in "$P_HAIKU" "$P_4OMINI" "$P_DEEPSEEK"; do set -- $spec; prov=$1; model=$2; shift 2
    out="results/ledger_world_exec/${model}.json"
    if [ -f "$out" ] && [ "$FORCE" = 0 ]; then echo "  $out exists, skipping"
    else run "L5_SERVER=$L5 $UVG probes/304_ledger_world.py --provider $prov --model $model $* --n 100 --p-revise 1.0 --offset-ms 150 --revisions 2 --second-gap-ms 800 --modes validated,ledger,ledger_norollback --p-cancel-fail 0.1 --p-rebook-fail 0.1 --consumer-max-ms 1500 --seed 20261014 --compensator all --registration atomic --ledger exec --out $out"; fi
  done
  echo "  UPLOAD after this step: results/ledger_world_exec/*.json (and the .records.jsonl beside them), results/verus/lib_l5_exec.verus.log"; fi

if want 19; then log 19 "receipt-derived analyses: arm timing, replicated runs, hypothesis gates (then re-run 13)"
  run "python3 harness/macaudit/arm_timing.py --root results --tex --check 2>&1 | tee tools/arm_timing.log | tail -16"
  run "python3 harness/macaudit/live_runs_aggregate.py --root results/live_a1_outcome --tex 2>&1 | tee tools/live_runs.log | tail -30"
  run "python3 harness/macaudit/hypothesis_gates.py --root results --check --tex 2>&1 | tee tools/hypothesis_gates.log | tail -24"
  run "python3 harness/macaudit/a7_rescore.py --check 2>&1 | tail -3"
  # the fold itself (step 13's core): without it results/paper_receipts_summary.json is the PREVIOUS run's and the
  # gate below passes against a stale inlined block (2026-10-16: exactly what happened with --only 14,19,21)
  run "python3 harness/macaudit/claims_from_results.py --root results --paper paper | tail -4"
  run "python3 harness/macaudit/claims_gate.py --claims CLAIMS.json --scan README.md crates/runtime/README.md paper/main.tex paper/supplement.tex --artifact-url paper/main.tex 2>&1 | tail -4"
  echo; echo "UPLOAD after step 19 (the paper is regenerated from these):"
  echo "  results/paper_receipts_summary.json   tools/verified_scorer.json   tools/verified_scorer.log   tools/hypothesis_gates.log"
fi

if [ "$DRY" = 0 ]; then
  if [ ${#FAILED[@]} -gt 0 ]; then
    echo; echo "FAILED steps/commands (${#FAILED[@]}); fix and re-run with --only <n>:"; printf '  %s\n' "${FAILED[@]}"; exit 1
  else echo; echo "all requested steps completed"; fi
fi
