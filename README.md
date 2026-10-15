# mac-consistency

**Verified detection and prevention of concurrency anomalies in multi-agent
LLM systems -- the artifact.**

Four history predicates over an operation log (stale generation A1, phantom
tool A2, causal cascade A3, tool-effect reordering A6), a 16-point exclusion
lattice with one named chain L0 < L1 < L2 < L3 < L4, and three verified
layers under it: (i) TLA+ models with TLC witnesses, a 64-run realizability
matrix and three TLAPS proofs (`formal/tla/`); (ii) a Verus development that
proves the detectors sound and complete and each runtime discipline safe
(`crates/verus-detector/`), with the L2/L4 exec artifacts compiled unchanged
into the reference runtime (`crates/runtime/`); (iii) the empirical campaigns
-- AutoGen pilot, live LangGraph studies, the public-repository census -- as
numbered probes (`probes/`) whose receipts are committed (`results/`).

Every headline figure is in **`CLAIMS.json`**. `./reproduce.sh` re-derives each
one from committed data and fails on any disagreement; `harness/macaudit/claims_gate.py`
fails if any README, doc or `.tex` states a figure that `CLAIMS.json` does not.
The manuscript cites this repository at the tag named in `CLAIMS.json`
(`artifact.tag`; `scripts/release_tag.sh` creates it after the gates pass).

**What is the verified code, byte for byte.** `harness/macaudit/verified_bytes_gate.sh`
checks that every file the runtime compiles with plain cargo (proofs erased) is
byte-identical to the file the pinned Verus build verified: the L1 stores on
`vstd`'s lock, the L2 output-commit runtime, the L3 sequencer behind
`examples/l3_server.rs`, the L4 dispatcher, and the A1 detector
(`detect_a1_exec.rs`) that `crates/analyser` uses for every A1 verdict since
2026-10-14 (`harness/macaudit/verified_scorer_gate.py` rescores every published
A1 cell through it and writes `tools/verified_scorer.json`).

## Single-command audit

```
./reproduce.sh            # [1] TLC  [2] TLAPS  [3] Verus  [4] rescoring gates  [5] cargo  [6] census
./reproduce.sh --strict   # a skipped stage (missing tool) is a failure -- use before submission
make audit
```

Stages whose tool is absent say so and skip. Stage [4] needs python3 only and
runs in under a minute; it is the one to run on every commit.

## Layout

```
CLAIMS.json              single source of truth for every published number
reproduce.sh             single-command audit (stages [1]..[6])
Makefile                 setup / tlc / tlaps / verus / rust / data / census / audit
Cargo.toml               Rust workspace root (crates/runtime, crates/analyser)
pyproject.toml           root uv project: the harness package `macaudit`
crates/runtime/          reference runtime: L0/L1 stores on vstd's verified lock,
                         the L2/L4 verified exec artifacts (byte-identical to
                         crates/verus-detector/src/lib_l{2,4}_exec.rs), the
                         measurement examples and the live L2 driver
crates/verus-detector/   the Verus development (31 files + lib_l5_ledger.rs, the
                         L5 basis-ledger model); verus-version.txt pins the build
                         the counts were measured with
crates/analyser/         the scorer: its A1 verdict is the VERIFIED exec detector
                         (runtime::detect_a1_verified -> detect_a1_exec.rs, byte-identical
                         to the Verus source) with the former hand-written port kept
                         beside it as a cross-check (--strict fails on disagreement);
                         A2/A3/A6 remain ports gated against the Verus specs
formal/tla/              Memory/Anomalies/Guarded/CommitOrder .tla, the MC_* models,
                         lattice16.sh + committed matrices, check_*.sh verdict scripts;
                         Guarded5.tla + mkcfg5.py + lattice32.sh (A7 / G7 basis ledger,
                         the 32-point matrix, 160 runs)
formal/weakmem/          GenMC RC11 litmus check of the lock discipline
envs/                    ONE ENV = ONE MATRIX CELL (framework@version); per-cell uv
                         projects (langgraph-1.2.0, langgraph-1.2.5, autogen, crewai-1.15, letta)
harness/macaudit/        gates: rescore_cells.py (Def-1 rescoring of every cell),
                         predicate_matrix_a1.py (TLA+/Verus/analyser transcriptions agree),
                         outcome_rescore.py (booking-outcome table), a7_rescore.py
                         (A7 by argument provenance; A1 + A7 = booking != final),
                         claims_gate.py (+ --artifact-url / --remote-readme), verus_count.sh,
                         verified_bytes_gate.sh, verified_scorer_gate.py, arm_timing.py
                         (are the arms of Table 3 the same race?), live_runs_aggregate.py
                         (between-run intervals), hypothesis_gates.py H0-H6
probes/                  numbered probes (101..); `make setup` resolves their envs
results/                 committed evidence, one directory per campaign:
                         runs/ (AutoGen pilot, 3 stamped runs), live_a1_*/ (LangGraph live),
                         live_a1_outcome/ (probe 303: four arms, offset sweep, three
                         interleaved runs), ledger_world/ (probe 304, the ledger in a
                         world; ledger_world_v1_latest_conf/ archives the first run's
                         compensator, --compensator latest), a6_real_latency/,
                         live_l2/, langgraph_a6_*/, hc_*/ (contention sweep), traces/,
                         production_traces/, mast_oprecords/, pilot_tokens*/, l2_measure.json,
                         l4_measure.json, verus/count.json
archaeology/             the census frames and samples, the error-string corpus
docs/decisions/          decision records (what each "round" changed and why)
docs/legacy/             the three pre-merge READMEs, kept verbatim for the record
```

`paper/` holds the manuscript sources (`main.tex`, `supplement.tex`, both
self-contained); every receipt-derived number in them is a macro that
`harness/macaudit/claims_from_results.py` regenerates from `results/`
(`paper/claims_results.tex`, inlined into both files), and `claims_gate.py`
fails when the inlined block is stale or the two files disagree.

## Prerequisites

* uv >= 0.4 -- manages Python itself; the harness is stdlib-only
* Java >= 11 (TLC; `reproduce.sh` fetches `tla2tools.jar` on first run)
* Rust >= 1.83 (`cargo`) for `crates/runtime` and `crates/analyser`
* Verus **exactly** `crates/verus-detector/verus-version.txt` -- a newer verifier
  makes proof files stop *compiling*, which the counter reports as "no
  verification summary"; `verus_count.sh` refuses to print a total from a
  mismatched build
* tlapm (optional) for stage [2]; GenMC >= 0.17 (optional) for `formal/weakmem`

## Step-by-step

```bash
git clone https://github.com/sajjadanwar0/mac-consistency && cd mac-consistency
make setup        # uv sync for the root project and every env cell
make data         # offline rescoring gates (python3 only, < 1 min)
make tlc          # TLC witnesses + lattice16 (~15 min on 4 cores)
make verus        # requires the pinned Verus build
make rust         # cargo test; L2/L4 measurements vs results/*.json
./reproduce.sh    # everything, gate-style
```

Run one probe in its pinned cell:

```bash
uv run --project envs/langgraph-1.2.0 python probes/125_langgraph_live_a1.py --help
```

## Workflows

**Add a measurement.** Write `probes/NNN_name.py` (next free number), have it
write its receipt under `results/<campaign>/`, add the headline figure to
`CLAIMS.json`, and add a line to `reproduce.sh` that re-derives it from the
receipt. A figure with no receipt and no gate is not reported.

**Refresh a receipt deliberately** (never implicitly): re-run the probe, review
the diff against the committed receipt, commit both. Git history holds every
prior receipt. A drift is a finding, not noise.

**Change a predicate.** Definition 1 is transcribed in four places (TLA+,
Verus spec, Rust analyser, Python gates). `predicate_matrix_a1.py --strict`
fails if they disagree on any committed cell; change all four or none.

**Renumber an obligation count.** Only `verus_count.sh --json` writes the
`verus` block of `CLAIMS.json`; READMEs quote `CLAIMS.json`, never the other
way round.

## Conventions

American English; ASCII-only in artifacts; complete files; numbered probes
continue from the highest committed number; every audit gates on committed
receipts; probe verdicts that depend on a model call record the model, the
provider and the run timestamp in the receipt, and are never regenerated
silently.
