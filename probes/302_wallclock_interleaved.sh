#!/usr/bin/env bash
# 302_wallclock_interleaved.sh -- the interleaved wall-clock rerun the paper
# says it lacks (Sec 5.8 / 6.2 (b)): "only a rerun with the three runtimes
# interleaved per session would remove the run-order confound."
#
# The committed run 20260913T0150Z executed its nine cells one after another,
# so the control (plan-execute, which aborts nothing) drifts -4.5%/-4.9% on
# gpt-4o and +13.5% on Claude -- the "null band" the paper then has to invent.
# This script runs ONE session at a time and cycles the runtime per session
# in a seeded random order (vanilla / pessimistic / snapshot_isolation), so
# provider latency drift hits all three arms alike and the paired per-session
# difference is a legitimate estimand.
#
#   OPENAI_API_KEY=... N=100 ./probes/302_wallclock_interleaved.sh            # gpt-4o
#   ANTHROPIC_API_KEY=... PROVIDER=anthropic MODEL=claude-sonnet-4-5 N=100 ./probes/302_wallclock_interleaved.sh
#
# Output: results/runs/<stamp>-interleaved/<workload>-<runtime>/*.jsonl and the
# token/wall-clock sidecars, in the SAME shape as runs/20260913T0150Z, so
# probes/141_realstore_metrics.py scores it unchanged (point it at the new
# stamp with --stamp if the probe grows that flag; otherwise edit RUNS at the
# top of the probe).  Also writes order.tsv: (session, runtime) in the order
# actually executed -- the receipt that the interleaving happened.
#
# Cost: 3 runtimes x 3 workloads x N sessions of gpt-4o; at N=100 and the
# paper's ~$3m/session that is ~$3 of inference.  Re-runnable: a cell that
# already holds N traces is skipped.
set -euo pipefail
N="${N:-100}"; SEED="${SEED:-42}"
PROVIDER="${PROVIDER:-openai}"; MODEL="${MODEL:-gpt-4o}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%MZ)-interleaved}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# the pilot imports autogen_agentchat: run it inside the pilot's uv project (envs/pilot-legacy), not the system python
if [ -z "${PY:-}" ]; then
  if [ -f "$ROOT/envs/pilot-legacy/pyproject.toml" ]; then PY="uv run --project $ROOT/envs/pilot-legacy python"; else PY=python3; fi
fi
PILOT="$(ls "$ROOT"/probes/*_autogen_pilot.py | head -1)"
[ -f "$PILOT" ] || { echo "FAIL: autogen_pilot probe not found under probes/" >&2; exit 1; }
case "$PROVIDER" in
  openai)    [ -n "${OPENAI_API_KEY:-}" ]    || { echo "FAIL: OPENAI_API_KEY unset" >&2; exit 1; };;
  anthropic) [ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "FAIL: ANTHROPIC_API_KEY unset" >&2; exit 1; };;
esac
RUN="$ROOT/results/runs/$STAMP"; mkdir -p "$RUN"
RUNTIMES=(vanilla pessimistic snapshot_isolation)
WORKLOADS=(edit-review plan-execute triage)

# seeded per-session permutation of the three runtimes
order_for() { # order_for <session> -> three runtimes, one per line
  $PY - "$1" "$SEED" <<'PY'
import random, sys
k, seed = int(sys.argv[1]), int(sys.argv[2])
r = ["vanilla", "pessimistic", "snapshot_isolation"]
random.Random(seed * 1_000_003 + k).shuffle(r)
print("\n".join(r))
PY
}

: > "$RUN/order.tsv"
for ((k = 0; k < N; k++)); do
  while IFS= read -r rt; do
    for wl in "${WORKLOADS[@]}"; do
      cell="$RUN/$wl-$rt"; mkdir -p "$cell"
      # autogen_pilot writes N sessions per call; we ask for ONE session with seed+k
      # into a per-session staging dir, then move it into the cell as session k.
      stage="$RUN/.stage-$wl-$rt-$k"; rm -rf "$stage"
      if ls "$cell"/*"-$(printf '%04d' "$k")".jsonl >/dev/null 2>&1; then continue; fi
      ( cd "$(dirname "$PILOT")" && $PY "$(basename "$PILOT")" --provider "$PROVIDER" --model "$MODEL" \
          --workload "$wl" --runtime "$rt" --n 1 --seed $((SEED + k)) --scenario-offset "$k" \
          --output "$stage" --tokens-output "$stage-tokens" ) || { echo "FAIL: $wl/$rt/$k" >&2; exit 1; }
      f="$(ls "$stage"/*.jsonl | head -1)"; mv "$f" "$cell/session-$(printf '%04d' "$k").jsonl"
      # the sidecar is named by SESSION. Before 2026-10-15 every one-session call wrote <wl>-<rt>-0000.tokens.jsonl and the
      # mv below overwrote the previous session's sidecar: the 2026-10-14 interleaved runs kept ONE sidecar per cell (the
      # last session's), so their wall-clock receipt is order.tsv (completion stamps, 1 s resolution), folded by
      # harness/macaudit/claims_from_results.py as the stamp-based estimate.
      mkdir -p "$RUN/tokens-$wl-$rt"
      for tf in "$stage-tokens"/*.tokens.jsonl; do
        [ -f "$tf" ] && mv "$tf" "$RUN/tokens-$wl-$rt/session-$(printf '%04d' "$k").tokens.jsonl"
      done
      rm -rf "$stage" "$stage-tokens"
      printf '%d\t%s\t%s\t%s\n' "$k" "$wl" "$rt" "$(date -u +%FT%TZ)" >> "$RUN/order.tsv"
    done
  done < <(order_for "$k")
done

cat > "$RUN/manifest.json" <<EOF
{"provenance": "captured", "design": "interleaved-per-session", "provider": "$PROVIDER", "model": "$MODEL",
 "n": $N, "seed": $SEED, "stamp": "$STAMP", "pilot_git_sha": "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"}
EOF
echo "done: $RUN  (score with: $PY probes/*_realstore_metrics.py --check after adding the stamp to RUNS)"
echo "then: $PY harness/macaudit/rescore_cells.py --root results   # add the new cells to results/expected.json first"
