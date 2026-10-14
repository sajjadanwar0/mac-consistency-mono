> **SUPERSEDED (historical, kept for provenance).** Figures below are from an earlier round of the artifact;
> the current numbers are in `CLAIMS.json` at the repository root and in the manuscript. Do not cite this file.

# Experiment plan (v4): one command, thirteen steps, sized to your balances

Budgets this plan is sized to: **Claude $200, OpenAI $2.66, DeepSeek $4.28.**
OpenAI is used only where the paper already has gpt-4o/gpt-4o-mini cells
(gpt-4o-mini sessions are cents; the gpt-4o wall-clock rerun is cut to N=60 to
fit); DeepSeek becomes a **fourth API family** in Table 3 through its
OpenAI-compatible endpoint; everything else runs on Claude (≈ $40 of the $200).

**You run the experiments; the paper is regenerated from the receipts.** Step 13
folds every receipt into one file, `results/paper_receipts_summary.json`; upload
it (plus the two logs it names) and the PDF/LaTeX come back from here. You do
not need pdflatex or the LaTeX sources.

```
export ANTHROPIC_API_KEY=...  OPENAI_API_KEY=...  DEEPSEEK_API_KEY=...
./scripts/run_experiments.sh --dry-run      # prints every command with its cost and time
./scripts/run_experiments.sh                # or --only 1,2,4,7,12,13 first (cheapest, highest value)
```

| step | what it closes in the paper | needs | cost | time |
|---|---|---|---|---|
| 1 | builds the verified-store bridge (`l1_server`) | cargo | $0 | 2 min |
| 2 | **Table 3's `verified` and `ledger` rows** on haiku, gpt-4o-mini and deepseek-chat (the flagship study on the verified bytes; the ledger + compensator outcome; a fourth API family) | 3 keys | ~$1.5 | 1 h |
| 3 | the offset curve (rates as a function of the race, p-revise 0.5) on the same three | 3 keys | ~$2.5 | 2.5 h |
| 4 | Sec. 6.4: ToolNode A6 against real sqlite/http effects | none | $0 | 10 min |
| 5 | Sec. 6.6: paired, interleaved wall-clock overheads on gpt-4o (N=60) | OpenAI | ~$1.8 | 1 h |
| 6 | same on claude-sonnet-4-5 (N=100) | Claude | ~$15 | 1.5 h |
| 7 | Sec. 5.5: **Verus proof of the ledger model** (`verus --crate-type=lib src/lib_l5_ledger.rs`); curated/full counts; fixes the README line the claims gate flags; updates CLAIMS.json | Verus 0.2026.09.13 (you have it) | $0 | 20 min |
| 8 | tlapm log for CommitOrder.tla | tlapm (optional) | $0 | 10 min |
| 9 | lattice32 (160 runs) and the two-value safety half on your machine | java | $0 | 3 h |
| 10 | Sec. 6.3 live verdicts: 1,000-session per-model statement for haiku | Claude | ~$3 | 1 h |
| 11 | Table 4/7 Claude panel with op-records | Claude | ~$15 | 2 h |
| 12 | L2/L4 measurement receipts (`results/l2_measure.txt`, `results/l4_measure.txt`; the seeded examples' text is the receipt the gate diffs) | cargo | $0 | 5 min |
| 13 | fold receipts into `results/paper_receipts_summary.json`; run the gates; print the upload list | python3 | $0 | 1 min |

Order if you want the paper to move fastest per dollar: **1, 2, 4, 7, 12, 13** (one
evening, < $2), then 3, 6, 10, 11, 5, 9, 8.

If the Verus file does not verify on the first try (it was written without a
verifier at hand), upload `results/verus/lib_l5_ledger.verus.log` as is: the
errors are what I need to fix it, and the paper keeps saying "proof pending"
until it goes through.

---

# (v3 plan, kept for the rationale of each run)

Everything below runs on YOUR machine with YOUR keys. I cannot spend your API
budget from the sandbox (no keys there, and PyPI/crates.io are unreachable, so
`langgraph` cannot even be installed). Each probe writes a receipt under
`results/` and prints the LaTeX rows that drop into `paper/claims.tex` or the
tables; run `./reproduce.sh --data-only` afterwards so every gate re-checks.

Budget estimates use the paper's own measured per-session prices (Table S1/S2:
gpt-4o $3.1m, Claude Sonnet 4.5 $16m per pilot session; the live A1 session is
~2 calls x ~150 tokens). Totals below sum to ~$97, leaving headroom for reruns.

| # | Probe | What it fixes in the paper | Model(s) | Sessions | Est. cost | Paper location |
|---|---|---|---|---|---|---|
| 1 | `probes/303_live_a1_outcome.py` | the live rates become a *function of relative latency* (offset swept 0/150/500/1500 ms) and the booking outcome gets a denominator the harness did not force (p-revise 0.5) | claude-haiku-4-5, gpt-4o-mini | 3 modes x 4 offsets x 100 = 1,200 per model | < $5 total | Table 3 gains an offset column; Fig. 3; Sec. 6.1 "What the rates are" becomes a curve |
| 2 | `probes/302_wallclock_interleaved.sh` | removes the run-order confound; the "null band" paragraph in Sec. 6.6 is replaced by a paired estimate | gpt-4o (900 sessions), claude-sonnet-4-5 (900) | 1,800 | gpt-4o ~$3; Claude ~$15 (x3 for n=300/cell: ~$55) | Sec. 6.6 wall-clock paragraph; new Table "paired per-session overhead" |
| 3 | `probes/301_a6_toolnode_real_latency.py --effect sqlite` and `--effect http` | replaces the modeled `asyncio.sleep` with real effects; the ToolNode reorder rate is then under latency nobody chose | none (replays recorded batches) | 33 batches x 5 reps x 2 backends | $0 | Table 6 gains two rows ("real effect: sqlite / http"); Sec. 6.4 drops "modeled" from the finding |
| 4 | live L2 replay with a larger API-model sample (`crates/runtime/l2-live`, `tools/live_l2/gen_sessions.py --n 1000`) | the pooled 0/66 rests on 62 Llama retractions; 1,000 haiku sessions at a neutral prompt gives a per-model statement for one API family | claude-haiku-4-5 | 1,000 (3 calls each) | ~$3 | Sec. 6.3 "Live verdicts": per-model row for haiku |
| 5 | natural-prompt ToolNode on two more backbones (`probes/121_langgraph_a6_experiment_natural.py --provider anthropic --model claude-sonnet-4-5`; `--model gpt-4o`) | the batching claim is about *backbones*; two data points per vendor is thin | claude-sonnet-4-5, gpt-4o | 30 turns each | ~$2 | Table 6: two more rows |
| 6 | pilot replication on Claude Sonnet 4.5 **with op-records** (`rerun_pilot.sh --table4`, PROVIDER=anthropic) | Table 4 and Table 7 are gpt-4o only; the Claude replication exists only as token logs | claude-sonnet-4-5 | 900 | ~$15 | Table 4/7 gain a Claude panel; "per sound commit" exists for Claude |
| **7** | **`probes/303_live_a1_outcome.py --modes vanilla,validated,sequential,ledger`** (the L5 arm: basis ledger + rebooking compensator) | **the paper's new predicate A7 has a theorem (cannot be prevented, only owed) and a TLC-checked ledger; this is the one measurement of what a registered obligation buys: the `Booking != final` column under L5, and its price in compensation generations** | claude-haiku-4-5, gpt-4o-mini | 4 modes x 100 (one offset, 150 ms, is enough; add offsets later) | < $2 total | Table 3, the two `ledger (L5)` rows (`\LfiveLiveOutcome`); Sec. 6.1 "A7 decides the residue" last sentence; Sec. 8 |

Run order: 3 (free, today), **7 (cheapest, unblocks the new contribution)**, 1, 5, 4, 2, 6.

## Exact commands (from the monorepo root after `scripts/00_migrate_monorepo.sh`)

```bash
# 3. A6 with real effects (no key)
uv run --project envs/langgraph-1.2.5 python probes/301_a6_toolnode_real_latency.py \
   --batches results/langgraph_a6_natural --effect sqlite --reps 5 --out results/a6_real_latency/sqlite.jsonl
uv run --project envs/langgraph-1.2.5 python probes/301_a6_toolnode_real_latency.py \
   --batches results/langgraph_a6_natural --effect http   --reps 5 --out results/a6_real_latency/http.jsonl

# 1. live A1 as an outcome experiment
export ANTHROPIC_API_KEY=...; export OPENAI_API_KEY=...
uv run --project envs/langgraph-1.2.0 python probes/303_live_a1_outcome.py --provider anthropic --model claude-haiku-4-5 \
   --n 100 --p-revise 0.5 --offsets 0,150,500,1500 --out results/live_a1_outcome/claude-haiku-4-5.json
uv run --project envs/langgraph-1.2.0 python probes/303_live_a1_outcome.py --provider openai --model gpt-4o-mini \
   --n 100 --p-revise 0.5 --offsets 0,150,500,1500 --out results/live_a1_outcome/gpt-4o-mini.json

# 7. the L5 arm (A7 / basis ledger) -- same harness, four modes; prints the Table 3 rows
uv run --project envs/langgraph-1.2.0 python probes/303_live_a1_outcome.py --provider anthropic --model claude-haiku-4-5 \
   --n 100 --offsets 150 --modes vanilla,validated,sequential,ledger --out results/live_a1_outcome/claude-haiku-4-5_l5.json
uv run --project envs/langgraph-1.2.0 python probes/303_live_a1_outcome.py --provider openai --model gpt-4o-mini \
   --n 100 --offsets 150 --modes vanilla,validated,sequential,ledger --out results/live_a1_outcome/gpt-4o-mini_l5.json
# each run prints, per mode: a1, a7, booking!=final, regenerations, obligations registered/discharged,
# compensation generations. Under `ledger` expect a7 = 0 (every superseded booking is owed) and
# booking!=final to drop to the compensator's failure rate; paste the two rows into paper/claims.tex as
#   \newcommand{\LfiveLiveOutcome}{...}   (replace the [pending] macro; the table rows pick it up)

# 2. interleaved cost rerun
N=100 ./probes/302_wallclock_interleaved.sh                                  # gpt-4o
PROVIDER=anthropic MODEL=claude-sonnet-4-5 N=100 ./probes/302_wallclock_interleaved.sh
python3 probes/141_realstore_metrics.py --check    # after adding the new stamp to RUNS in that probe

# then, always
./reproduce.sh --data-only && python3 harness/macaudit/claims_gate.py --claims CLAIMS.json --scan README.md paper
```

## How each result enters the paper

* 303 -> replace `\LiveOffsetMs`-based prose in `sec/06-evaluation.tex` with the
  offset curve; add a column "offset" to Table 3 or a small line plot (pgfplots
  skeleton is in Fig. 3's TikZ). The outcome column keeps its definition.
* 302 -> replace the "Wall-clock, with its confound" paragraph with the paired
  estimate (mean paired difference, bootstrap CI, Holm over six cells); delete
  the null-band sentence.
* 301 -> Table 6 two extra rows; in Sec. 6.4 change "Modeled: per-tool latency"
  to a sentence reporting the real-effect rate.
* 4/5/6 -> extra rows in the tables named above.
* 7 -> `\LfiveLiveOutcome` in `paper/claims.tex` (one line: `$a/100$ booking $\neq$ final,
  $k$ obligations registered, $k'$ discharged, $g$ compensation generations`); the
  A7 column of Table 3 for the ledger rows must read 0, by construction (if it does
  not, the ledger has a bug and `a7_rescore.py --check` will say so before the paper does).

## What you must also do without the API (formal side, ~2 days)

1. Install the pinned Verus (`crates/verus-detector/verus-version.txt`), run
   `verus_count.sh --full`, and commit `results/verus/count.json`; make
   `claims_gate.py` pass. Until then the paper's 364/385 is carried from your
   artifact, not re-derived.
2. Run `tlapm CommitOrder.tla` and commit its log next to the two existing
   TLAPS logs (the 60 is currently uncorroborated by a committed log).
3. Add `--json` receipt output to `examples/l2_measure.rs` and
   `examples/l4_measure.rs`; commit `results/l2_measure.json`,
   `results/l4_measure.json` (Tables 5 and the L4 numbers currently live only
   in README prose).
4. Add the `agent` field to the Verus `OpRecord`, the agent conjunct to
   `a1_witness`/`detect_a1`, re-verify, and wire `rust-analyser` to
   `verus_detector::detect_a1` (the shim `verified_a1.rs` shows how). This
   closes the transcription gap outright instead of by Lemma 1.
5. **Verify `crates/verus-detector/src/lib_l5_ledger.rs`** (drafted here, UNVERIFIED:
   no Verus in the sandbox). `verus src/lib_l5_ledger.rs` -- expect the four
   preservation lemmas, `lemma_l5_no_a7` and the two non-vacuity lemmas to go
   through with at most `assert`-level hints (the write step is the only
   non-trivial case: the marked cell is the one that became stale). Put the
   obligation count into `\LfiveVerus` in `paper/claims.tex` and add the file to
   `verus_count.sh`'s curated list. If a lemma needs an `assume`, the paper
   says so in Sec. 5.5 -- do not quietly add one.
6. **Run the full `lattice32.sh`** (`make lattice32`, ~1-2 h) and commit
   `formal/tla/lattice32_results.json` as `lattice32_results.reference.json`.
   The bundle ships the matrix computed here (see `formal/tla/`); re-running it
   on your machine is what makes the 160/160 figure yours.
7. Fix `crates/runtime/README.md`: it still says `358 curated` where CLAIMS.json
   says 364/385; `reproduce.sh` fails on it by design until the line is regenerated
   from `verus_count.sh --json`.
