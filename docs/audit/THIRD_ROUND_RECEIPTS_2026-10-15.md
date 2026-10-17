# Third round, receipts of 2026-10-15: what landed, what the audit found, what is still pending

Receipts received (runner steps 18, 11, 6, 13, 19 on the author's machine, after step 14 of 2026-10-14):
`results/paper_receipts_summary.json`, `tools/hypothesis_gates.log`, `tools/live_runs.log`,
`tools/verified_scorer.log`, the per-session receipts of probe 304 for both compensators
(`results/ledger_world/`, `results/ledger_world_v1_latest_conf/`, JSON + records), the console log of the run.
The paper (v7) was regenerated from them. Every receipt-derived number in the two `.tex` files is a macro of
`paper/claims_results.tex`, inlined into both (the claims gate checks the inlined block and that the two files
agree; it failed on the author's machine exactly because the tex files predated the receipts, and passes on the
regenerated ones).

## What the receipts established

* Probe 304, corrected compensator (`--compensator all`, the default): R = 0 in all 300 ledger sessions; in the
  sessions whose every obligation the ledger reports discharged (82 / 81 / 88 of 100 on haiku, gpt-4o-mini,
  deepseek-chat) the world holds exactly the final booking in 82 / 81 / 88; in every session with an open
  obligation (18 / 19 / 12) the world is wrong or empty. Report and world agree in 300/300 ledger sessions
  (exact 95% interval on the disagreement rate [0, 1.2]%); the first run's compensator agreed in 278/300
  (1 / 5 / 10 clean-but-wrong, 0 / 4 / 2 open-but-right). The failure shapes are the injected refusals seen from
  the world: double (cancel refused, rebook ok) 12 / 12 / 2, none (rebook refused) 6 / 7 / 8, stale only 0 / 0 / 2.
  The consumer, reading 0–1.5 s after the first release, acts on the stale booking in 100 / 96 / 93 sessions
  (the compensation needs a model call: median 1.4–1.5 s after the commit) and finds none in 0 / 1 / 0 (first
  run: 53 / 52 / 50, the model call between cancel and rebook). Retries: 0 / 7 / 16 — an open obligation is
  retried only at a further supersession; on haiku the first revision is caught by L1 and only the second lands
  after the commit (99/100 sessions register one obligation), on deepseek-chat both revisions land after the
  commit in 65/100 sessions.
* Verified scorer gate: 114 cells, 11,103 traces, 0 problems (every cell's verified count equals the Definition-1
  Python count and, where asserted, the manuscript's). The cell is filled in C3, Table 2, §5.1, §8, W.5.
* Hypothesis gates over every committed record: 64,408 records, 18,288 traces, 19 campaigns, 0 H0/H1
  violations, 1,299 A1 witnesses with 0 overwrite-restore shapes, basis recovered for 9,000/9,000 bookings,
  0 duplicate external effects among 10,800, 0 undeclared store reads over 6,300 records.
* Claude op-record pilot: all nine cells ran (900 traces). The verified scorer ran BEFORE steps 11 and 6
  completed, so only the three vanilla cells carry a verified A1 count (edit-review 100/100, plan-execute 0/100,
  triage 0/100 under seeded tickets); the six guarded cells are in the text as "--", pending `--only 14 19`.
  The triage zero is reported as a number whose cause is not established (the gpt-4o 48/100 cell differs in
  family and protocol at once).
* Probe 302 on Claude Sonnet 4.5 (interleaved wall-clock, 900 sessions) completed, but its timing sidecars were
  overwritten by the run script (see below); the wall-clock cell stays pending on the run's `order.tsv`.

## Defects the receipts exposed, all fixed in this version

1. `claims_from_results.py`: a function-local `import re` in `gates()` shadowed the module import, so the Claude
   pilot macros (`\VSClaude...`, `\PilotClaudeAvailable`) raised `UnboundLocalError`, swallowed by a bare
   `except: pass`. The three local imports are removed and the handler now prints the failure and leaves a
   comment in `claims_results.tex`.
2. `probes/302_wallclock_interleaved.sh`: a one-session pilot call always numbered its session 0, so every
   sidecar was `<wl>-<rt>-0000.tokens.jsonl` and the move overwrote the previous session's file (one survivor
   per cell; the same numbering gave every triage session the same seeded ticket). The script now names the
   sidecar by session and passes `--scenario-offset $k` to the pilot (new flag). The fold reads sidecars keyed
   by their session file name and, as a separate labelled estimate (`\WallclockStamp...`), the per-session
   wall-clock from `order.tsv` completion stamps (1 s resolution, interpreter start-up included).
3. `scripts/run_experiments.sh`: `delivered()` was defined below its call sites (steps 11 and 6 logged
   `delivered: command not found`); it is now defined with the other helpers. The upload list names
   `order.tsv` and says to re-run `--only 14 19` when steps 11 or 6 produce cells after step 14.
4. The fold emitted each `\VSClaude` macro twice (value, then `--`); it now emits each once.

## Independent hostile audit of the regenerated text (subagent, 2026-10-15) and what changed in response

Every number the auditor recomputed from the receipts reproduced (Fisher, McNemar, Clopper–Pearson, the 300/300 and
278/300 agreement counts, retries, compensation latencies, the census intervals, the TLAPS and Verus logs). The
findings were about what the sentences claimed and about internal consistency; each was acted on:

* The compensator runs inside the superseding put, in the date agent's thread, and the second revision's timer
  starts after that put returns: stated in §6.2 and W.4; the superseding writer's stall is now part of the ledger's
  price in §6.1.
* "The consumer acts on the stale booking because the compensation needs a model call" explained only part of the
  column. The fold now splits the stale reads by what had happened when the consumer read (before any revision had
  landed: 28/34/34; after the revision and before the compensation: 72/51/44; after a compensation a later revision
  superseded: 0/11/15), and the abstract, §6.2 and W.4 say so; the 1.5 s window is labelled a harness parameter.
* The executable ledger registers the obligation after the put, outside the store lock (`LedgeredStore.put`); only
  the Verus model registers atomically. "Atomically" is now reserved for the model (abstract, §3.6, §5.5, §7.3, §9).
* "A1 and R partition …" holds only for one-revision workloads; R = 0 in the ledger arms is by construction; the
  world is simulated in-process; "the records cannot tell the compensators apart" narrowed to R (the store and the
  compensation records could); the 300/300 count no longer carries a confidence interval in the main text.
* The store axiom, the one hypothesis of Theorem 1 not gated on the records, is now gate H7 in `hypothesis_gates.py`
  (0 violations over 29,005 declared reads in 14,266 store-instrumented traces; the four campaigns converted from
  transcripts and tool logs — production_traces, mast_oprecords, oprecords, traces — read state their traces never
  recorded and are reported, not gated). Table 1 names the gates (H0, H1, H7) instead of "H1–H3".
* The paired-difference interval is Newcombe's method 10 (Wilson-based) instead of Wald (haiku: [−0.5, +4.1] in
  place of [−0.3, +3.6]); a χ² homogeneity test across the three runs is reported per arm (deepseek-chat validated
  residue p = 0.014); the sequential-vs-interleaved contrasts are labelled nominal and confounded; deepseek-chat's
  non-significant contrasts appear in the main text.
* The lattice's NoA1 safety verdicts at MaxOps = 2 cover only the cold-start class (Appendix L). New
  `formal/tla/lattice16_a1_maxops3.sh` (runner step 20) re-checks the sixteen NoA1 points at MaxOps = 3, two values
  and one cell, where the supersession witness is reachable: 16/16 points as expected (the eight G1 points safe
  exhaustively over 3.0–10.2M distinct states, depth 12; the eight G1-off points reach A1 within 462–1,163
  states) and the witness-class pair (NoA1NonNull: a non-NULL stale read) reached without G1 in 18,242 states and
  excluded with it (3,886,087 states) — `formal/tla/lattice16_a1_maxops3_c1_results.json`, TLC 1.8.0, two workers,
  2026-10-15. The two-cell universe did not close in 25 minutes on two cores (72M distinct states; log committed
  as `lattice16_a1_maxops3_c2_attempt.log`); the verdict covers the one-cell universe, and the paper says so.
* "Realizes exactly" → "excludes exactly" (soundness only); the §6.1 setup says what the models do (the booking's
  date is the read value; the models set latency and draft text; model output is scored only in the materiality
  study); H3's zero cannot occur on these workloads (monotone revisions); the footnote no longer calls CLAIMS.json the
  one source of every number.
* Supplement: Appendix F's "serializable in commit order" made precise (value-level, on reads; the TLA module
  header's phrase explained); ≥25 cross-references renumbered (the live table is Table 2, cost is Table 5/§6.6,
  the census §6.7, threats §6.8, materiality inside §6.1, the pilot table in Appendix M); 2.3× → 2.2×; the
  interleaved Claude run's lost sidecars (Appendix O); `lib_l5_ledger.rs`'s stale "DRAFT" header rewritten.
* Related work: Crooks et al. 2017 (client-centric isolation, beside Definition 2), Silo and TicToc (read-set
  validation at commit) in the main text; Viper, PolySI, Plume, DaisyNFS/GoTxn and Helland's idempotence in Appendix R.

## Text changes

* Abstract, C4, §6.2, §8, §9 rewritten around the corrected run: the headline is the report/world agreement,
  the first run demoted to one sentence in the main text with its full table in W.4. Table 5 gains a
  right/discharged column and drops the consumer-none column (0 / 1 / 0; in the supplement table).
* §6.1 scorer paragraph, C3, Table 2, §8: the verified-scorer cell filled; the first failed pass stated.
* §6.3: the Claude vanilla cells scored; the six guarded cells marked pending with the reason.
* §6.7, threats, §8: the lost sidecars stated; the stamp-based estimate described and conditional.
* Supplement: W.4 rewritten (both runs tabulated, failure shapes, timing from the records, all as fold
  macros); W.5 the passed gate; M the Claude panel; O the probe-302 receipt account.
* Main text trimmed to hold 16 pages (prose only: captions, intro, census, limitations, conclusion).

## Pending (each marked in the text)

Step 14 rerun after 11 (the six guarded Claude cells' verified A1 counts; `--only 14 19`); the Claude interleaved
run's `order.tsv` for the stamp-based wall-clock cell (folded by step 19 once the file is beside the run). Beyond
the markers: the two-cell NoA1 universe at MaxOps = 3 (a longer TLC run), and the open items the audit left as
design choices rather than defects — a world that is not an in-process mock, a sweep of the consumer window, an
executable ledger that registers under the store lock (which would need the probe-303/304 ledger arms rerun).

---

## Fourth round (2026-10-16, evening): step 14/21 receipts folded — paper v7.2

Uploaded: `paper_receipts_summary.json` (turned out to be the 2026-10-15 fold, byte-identical:
step 19 did **not** re-run the fold — fixed below), `hypothesis_gates.log` (21 campaigns,
71,714 records, H7 0/35,069), the Claude interleaved run directory (900 cell-sessions,
`order.tsv`, one surviving sidecar per cell), `ledger_world_atomic/` and
`ledger_world_window5000/` (receipts carry `registration=atomic`, `compensator=all`,
seed 20261014). NOT uploaded: `tools/verified_scorer.json` / `.log` (the run log shows
"126 cells scored by the verified detector; 0 problem(s)", up from 114, but the per-cell
receipt is on the author's machine) — the Claude pess/SI cells therefore stay `[pending:
runner step 14 after 11]`, the one marker left in both PDFs.

Folded here from the raw receipts (sandbox mirror of `results/`), independently recomputed
from the per-session logs (every Table-4 column matched; wall-clock means matched the fold
to the first decimal; registration stamps: 839/839 ledger records in the atomic run and
786/786 in the after-put run carry a date_agent put's write_time — the stamp does NOT
distinguish the two designs; atomicity is a property of the code path, recorded by the
receipt's `registration` field, not demonstrated by the records).

What the new receipts say:
- Atomic registration moved nothing within the intervals (ledger arm, min–max over the
  three families, after-put → atomic: world wrong 4–12 → 10–15, double 2–12 → 8–13, none
  6–8 → 7–11, consumer stale 93–100 → 98–99, report/world agreement 300/300 → 300/300). The
  window it closes is the microseconds between write and registration call; the consumer
  reads over 1.5 s; the compensation takes 1.1–1.5 s (median). The paper says so and claims
  no improvement; Table 4 is now the atomic run (the shipped design), the after-put run is
  supplement Table S19 as the control.
- 5 s consumer window: consumer stale 51–67 of 100 (vs 98–99 at 1.5 s); split before
  revision / before compensation / after a compensation a later revision superseded
  = 9–10 / 23–32 / 10–34; world columns unchanged; agreement 300/300.
- Wall-clock from stamps (Claude Sonnet 4.5, 99 paired sessions per cell): triage pess
  +1.3% [-1.1,+3.7], SI +1.3% [-2.1,+5.9]; plan-execute (control) −0.5% [-3.5,+2.5],
  +2.1% [-1.6,+6.1]; edit-review pess +5.3% [+2.0,+8.4] (the one cell clearing zero),
  SI +2.4% [-1.2,+6.4]. Reconciled with the September +109.5%: in this run the pessimistic
  arm dropped the engineer in 100/100 triage sessions (records) but made no extra model
  calls (surviving sidecar: 4, as vanilla; the stamps admit no more), where the September
  refusals were retried at 7.75 calls/session. Cause of the retry difference not established
  from receipts; the paper says exactly that.

Fixes this round:
- `scripts/run_experiments.sh`: step 19 now runs `claims_from_results.py` before the claims
  gate (root cause of the stale summary), and prints the upload list including
  `tools/verified_scorer.json`.
- `harness/macaudit/claims_from_results.py`: probe-304 fold writes the atomic and 5 s runs
  under their own summary keys (`probe304_atomic`, `probe304_window5000`; they were being
  filed under `probe304_first_run`), records the receipt's `registration` field
  (`\LW*Registration`), warns if an atomic-run receipt says otherwise, and emits
  `\<prefix><Arm><Metric>{Lo,Hi,Range}` = min–max over the families for every integer and
  timing column, so the prose never depends on a hand-ordered pair of per-model macros
  (two such pairs had inverted: "1.5–1.4 s", "4–12" vs "10–15" orderings).
- Paper: §6.2 rewritten onto the atomic run with Range macros; "Two controls" sentence
  (after-put run; 5 s window); §5.5 conditional resolved; C4 cites the atomic agreement;
  C6/(ii) says atomic registration is free and closes a window the measurements could not
  see; wall-clock paragraph carries the stamp cells and the 109.5%-vs-1.3% reconciliation;
  threats updated; supplement W.4 Registration paragraph rewritten with the after-put →
  atomic comparison and the 5 s split; §O names the one non-null cell and records the
  independent recomputation; Table S19 caption says "after-put registration".
- main.pdf 16 pages, 0 overfull; supplement 37 pages (10 pre-existing overfull boxes);
  inlined macro blocks identical in both files and to `paper/claims_results.tex`;
  claims gate 0 mismatching figures.

Still pending: `tools/verified_scorer.json` + `.log` (fills the six Claude pess/SI cells;
no API cost: `./scripts/run_experiments.sh --only 14` already ran, just upload the files).

### Independent audit of v7.2 (same evening) and what it changed

A second, isolated pass re-derived every Table-4 cell, every prose range, the two control
runs and the six stamp overheads from the raw receipts (all reproduced) and found six
should-fix items in the prose, all fixed before delivery:
1. The three-way consumer split ("before revision / before compensation / after
   compensation") was a landed/done test that could not support the causal gloss put on its
   third bucket ("after a compensation a further revision then superseded"). Haiku session 50
   of the atomic run is a counter-example (cancel refused at 3668 ms, consumer at 3683 ms saw
   both dates, no later revision). The fold now places each stale read in four exhaustive
   buckets, asserting the sum: no revision landed / inside the latest landed revision's
   compensation (matched by compensator.read_time == the put's write_time) / stale booking
   left by a refused cancellation (world log) / then-current booking later superseded.
   Atomic run: 18–31 / 60–74 / 1–2 / 1–10; 5 s window: 9–10 / 31–33 / 6–9 / 1–18. The
   supplement's sentence "the third share is not a failure of the compensation" is gone.
2. "The compensation itself takes 1.1–1.5 s" was booking-commit → first compensation record.
   `CompLatency*` is now compensator record − the revision it answers (1.0–1.2 s median);
   the old quantity is `BookingToCompensation*` (1.1–1.5 s) and is labelled as such.
3. "The window atomic registration closes is microseconds" — no receipt measures it (ledger
   records carry logical stamps only). Now: "closed by the code, unmeasured".
4. The after-put run was presented as "the control that shows what the change did and did
   not move"; it is a null by construction (the probe injects no fault, and no consumer read,
   in the gap) and an unpaired, different-day run. Now said so; "world columns unchanged"
   (5 s vs 1.5 s) → "within noise" with the numbers.
5. W.4's protocol paragraph still described after-put notification in the present tense one
   paragraph above the sentence retiring it. Fixed.
6. "Clean" sessions include 0–1 that registered nothing (vacuous); the main text now says so
   (`\LW*CleanVacuous`).
Nits also taken: 897 of 900 stamps (session 0's vanilla stamps absent → n=99), 1 s ticks ≈
one tenth of a 7–11 s session so +5.3% is a one-tick median, the 61 s gap in edit-review SI
(session 54), "one surviving sidecar" (n=1), the dropped-engineer count labelled as a trace
shape read without the detector, "in 97 of 100".

---

## Fifth round (2026-10-17): fixing what the review labelled — paper v7.3

The author's instruction: fix the gaps and failure points, do not label them. What was fixed, with
what receipt, and what remains open and why:

**Proof gap: the store axiom (H7) and the converted campaigns.** The converted campaigns
(mast_oprecords, oprecords, production_traces, traces; 3,289 of 6,448 reads disagree with the
latest visible write) supply NO published cell: results/expected.json's six campaigns are the three
pilot runs and the three live_a1 families, all store-instrumented. This is now a GATE, not a
remark: `hypothesis_gates.py --check` fails if any published cell's campaign is converted, prints
the instrumented totals (`\HypInstrumentedRecords/Traces`, `\HypPublishedCampaigns`,
`\HypPublishedConvertedCampaigns`), and the Reach paragraph says every A1 verdict in the paper is
taken on records the theorem's hypotheses were checked on. Preamble defaults for the new macros
are derived from the 2026-10-16 gates log's per-campaign table (71,714 − 15,375 records; 19,488 −
2,510 traces); step 19 re-derives them.

**Proof gap: the executable ledger was harness Python.** Added `crates/verus-detector/src/
lib_l5_exec.rs` (exec-mode L5 on the lib_l3_exec pattern: `register_effect`, `mark` — proved
total: after it no effect with a superseded basis is without an obligation, every other field kept,
the obligation bit exactly what it was or what this write set — `report`, `open_flags`,
`thm_covered_no_residue`, non-vacuity lemma), byte-identical `crates/runtime/src/l5_exec.rs`,
`examples/l5_server.rs` (JSON lines, mirrors l3_server, checks the verified preconditions),
`probes/_modules/exec_ledger.py` (the bridge: interning, shadow cross-check, raises on
disagreement), `probes/304_ledger_world.py --ledger exec` (receipt field `ledger`, server sha256,
per-session cross-check of the server's open set against the shadow), runner step 7 verifies the
file (zero errors required), step 14 builds the server, step 23 reruns the world study on it;
fold prefix `LWexec`, `\LfiveExecVerus`, `\LfiveExecAvailable`, `\LedgerWorldExecAvailable`;
paper §5.5, Table 1 row, limitations and supplement S conditional on those receipts (until then:
"a port", with no pending marker). Verus is not in the sandbox: the proof is written against the
idioms of the files that verify under the pinned build, reviewed by a second pass, and will be
checked by step 7 on the author's machine; a mock run of probe 304 over a Python twin of the server
agreed with the harness ledger session by session on the same seeds. Still a port until step 7.

**Proof gap: the refinement of the two concurrent stores.** Not fixed; it is a proof that does not
exist yet (bounded simulation is the evidence). Stated as open, as before.

**Failure point: the pending Claude pessimistic/SI cells.** Needs `tools/verified_scorer.json` from
the author's machine (step 14 already produced it there); nothing else can fill it.

**Failure point: +109.5% vs +1.3%.** The receipts (results/pilot_tokens_claude/, the September
Claude sidecars) show the September price was paid in further round-robin chat rounds after the
refusal (7 calls in 68/100 sessions, 9 in 15, up to 17; vanilla 4 in every session), with the same
696-token protocol prompts (October: 732, the seeded ticket), and both runs' tools told the refused
agent COMMITTED — a pilot defect: `read_state` raised KeyError on a refused begin and `write_state`
answered COMMITTED for a dropped commit (pessimistic and SI alike). Fixed: the tools return REFUSED
("your operation was NOT applied") under a recorded policy `--on-abort drop|retry`, counted per
session in refusals.jsonl; probe 302 takes `ARMS="... pessimistic:drop pessimistic:retry ..."`;
runner step 22 is the paired five-arm study on Sonnet (edit-review + triage, N=100, ~$15–20);
fold `probe302_refusal` → `\Refusal<Model>...`; paper §6.3/§6.6 and supplement M/O conditional.
The earlier draft's "free-form 116-token prompts" explanation was WRONG (that was the gpt-4o
September run) and was removed before delivery.

**Failure point: preprints in related work.** Counted from the bibliography: 20 of the 2026
agent-side works are arXiv-only; said so in §7.2, with "no claim of ours rests on their results".

**Failure point: "races we opened".** §6.1 now says what the 0 ms point is: the harness imposes
the order (the date agent is released at the flight agent's read) and no delay; the models'
latencies decide where the revision lands (probe 303: `flight_read_done.wait(); sleep(offset)`).
A production prevalence measurement is the only real fix and needs a deployment; not available.

Also: bibliography venue strings abbreviated (IEEE style) to hold 16 pages; related work and
limitations tightened; one conclusion sentence that restated the abstract removed.

### Independent audit of the v7.3 additions (same morning) and what it changed

Blockers found and fixed before delivery: `examples/l5_server.rs` began with an outer attribute
before inner doc comments (E0753; step 14 would have failed, so step 23 too) — removed; the
supplement's "mock runs agree" sentence attributed a test of a hand-written Python twin of the
server to the verified bytes — now says exactly that, and the receipt design was closed: probe 304
records whether the server was the built binary (`standin`, by name and magic bytes) and its
SHA-256, step 14 records the built binary's SHA-256 to results/verus/l5_server.sha256, and the fold
refuses to fold a ledger_world_exec receipt that is a stand-in or whose hash differs. Should-fixes
taken: the pilot's `aborts` was summed over agents sharing one recorder (now one count), and a
refused pessimistic read followed by its write counted two refusals (now one per refused
operation); the September enumeration omitted the 8 four-call sessions and now lists them, with
the note that the sidecars carry no agent identity (attribution follows AutoGen's one call per
turn); the Reach sentence's "6 that do / any table" was an undercount and an overreach — the gate
now covers every campaign the tables are folded from (13 on the 2026-10-16 log; expected.json's
six plus live_a1_outcome, the ledger_world runs and the Claude pilot/interleaved runs) and the
sentence says "no rate of this paper's tables"; the preamble's gate defaults were a 2026-10-15
vintage beside 2026-10-16 instrumented totals — all moved to the 10-16 log; `lib_l5_exec.rs` is
kept out of `verus_count.sh`'s totals (NEVER_COUNT) so the pinned 371/392 and claims_gate.py stay
reconciled until a deliberate renumbering; §S says "specified, and proved once step 7's receipt
lands"; `ledger.close()` on every path of probe 304; the bridge docstring no longer claims to
mirror the preconditions (the Rust bridge checks them; Python propagates). The Verus file itself:
no definite parse or proof failure found by inspection against the files that verify under the
pinned build; two places named where step 7 might ask for a hint (an explicit assertion after the
`set` in `mark`; the `r.0@` tuple-view idiom), both cheap to add if it does.

## Sixth round (2026-10-17, evening): step 7/14/19/22/23 receipts — paper v7.4

Receipts folded (run log of `--only 7,14,19`, then `--only 23`, then `--only 22`;
`results/paper_receipts_summary.json`, `tools/verified_scorer.{log,json}`, `tools/hypothesis_gates.log`,
`results/ledger_world_exec/`, `results/runs/20261017T0753Z-refusal-claude-sonnet-4-5/`):

**Step 7 ran under the WRONG Verus.** `~/bin/verus-pinned` on the author's machine is a
0.2026.05.03 build, not the pinned 0.2026.09.13.671956e. Under it every file of the crate
"failed", including the files that have verified for months, the counts came out 160/181, and the
runner's regeneration block then REWROTE `CLAIMS.json`, `crates/runtime/README.md`,
`results/verus/count.json` and overwrote `results/verus/lib_l5_ledger.verus.log` with errors. Fixes:
step 7 now reads `verus --version`, hard-stops when it differs from `VERUS_PIN` (printing the
`export VERUS=$HOME/.local/opt/verus-<pin>/verus` line) and never runs the rewrite when a count log
says INCOMPLETE or mismatched; `count.json` carries `verus_version` and the fold ignores a
`count.json` whose version is not the pin (the 371/392 preamble defaults stand). The four files
must be restored on the author's machine with `git checkout --` before the rerun. The three
genuine errors in `lib_l5_exec.rs` were the May build's demand that a postcondition on `&mut self`
name `old(self)`/`final(self)`; every ensures of the mutable methods now uses `final(self)` (loop
invariants keep bare `self`). The file's verification under the pinned build remains the one
pending marker in main.pdf (§5.5) and in the limitations' pending list.

**Step 14** (2026-10-17): 126 cells through the verified detector, 0 problems; the Sonnet guarded
cells are now scored (0/100, 0/100, 0/100 pessimistic; 50/100, 0/100, 0/100 default SI) and the
stale "await the next pass" sentence in supplement §M was replaced by the numbers. The built
`l5_server`'s SHA-256 (`f141b709…`) was recorded to `results/verus/l5_server.sha256`.

**Step 19**: the fold ran before the gate this time (fixed last round); gates log of 2026-10-16
vintage reproduced (71,714 records / 19,488 traces; H7 scope 13 published campaigns, 0 converted).

**Step 23** (exec ledger, three families, atomic registration, server sha matches step 14's
record, not a stand-in): folded as `\LWexec*`; world wrong / none / consumer-stale / clean ranges
and 300/300 report–world agreement in §5.5 and §S, stated as "bytes with the proofs erased by
cargo; a receipt that the bookkeeping reproduces the harness ledger's, not a verification".

**Step 22** (refusal-price study, Sonnet, N=100, five arms × edit-review and triage): folded as
`\RefusalClaude*`. Mechanism read from the records and `refusals.jsonl`: on Sonnet the triager and
the engineer commit READ-ONLY operations in 100/100 sessions (they never write a priority or
resolution; gpt-4o did in 41 and 45 of 100), so under pessimistic locking the triager's read holds
the ticket lock across its turns and the reporter and engineer are refused every turn in between
(8.47 refusals per session; 15.01 calls against 4.00, wall-clock +297.8%; retry 16.98 calls,
+332.7%); on edit-review the editor's lock refuses the reviewer 5 times per session (11.00 calls
against 5.00, +104.2%) and the editor's own write never commits (0/100) — the records do not settle
why (AutoGen dispatches a turn's tool calls concurrently and the pilot does not serialize an agent's
own begin/commit pair; stated as unsettled in §O, with the serializing pilot named as the missing
control); default SI refuses only the reviewer's overwritten read set (44/100 sessions, +19.7% /
+52.0%) and nobody on triage. Abstract and C4 carry the one-line consequence ("a lock held across a
model's turns costs 2–4× in calls on the contended workloads"). Both the refusal run and the exec
run postdate this round's step 14/19 passes; the supplement says so (no A1 verdict is taken from
either; the next `--only 7,14,19` pass gates them, the scope gate naming `runs/*-refusal-*`).

Page budget: main.pdf at 16 pages with 0 overfull boxes after abbreviating five bibliography venue
strings (IEEE Data Eng. Bull., Int. J. Softw. Tools Technol. Transf., Commun. ACM, Proc. VLDB
Endow., the Weikum–Vossen subtitle); the rule holds that cuts after the last float (`tab:cost`) are
the only ones that move the page count.

### Independent numbers audit of v7.4 (same evening) and what it changed — paper v7.5

61 hand-typed or macro figures checked against the raw receipts; 57 passed. The three failures and
what the fix uncovered:

1. **"41 and 45 of 100 for gpt-4o"** (triager priority / engineer resolution, run 20260913T0150Z,
   triage-vanilla) was wrong: the records give 44 and 41 (45 is the SI cell's triager count).
   Fixed in §6.3 and §M. **"priority written in 28/100 sessions"** (§M) had no definition that
   reproduces it; the records give 49/100 (triager 44, reporter 13). Fixed with the definition.
2. **"the Sonnet reviewer writes its review in 47–48 of 100 sessions"** cited the scored run, whose
   unguarded cell gives 50/100; 48 and 47 are the interleaved and refusal runs. Fixed (50; 47–48 in
   the two later runs). The auditor also found that the fold mirror's copy of run
   20261014T0253Z-claude holds only the three vanilla cells and its triage-vanilla is the VOID
   unseeded cell, so the main text's "triager and engineer commit read-only records in 100/100
   sessions" was asserted of a cell whose traces are not in the mirror. Now stated of the six cells
   whose records were inspected (interleaved vanilla/SI/pess, refusal vanilla/SI-drop/SI-retry; 600
   sessions; fold macros `\Interleaved…WriterCommits`, `\Refusal…WriterCommits`), with the scored
   cell's verified-scorer verdict beside them. The user should upload `results/runs/20261014T0253Z-claude/`
   in full (seeded triage-vanilla and the six guarded cells) so the mirror is complete.
3. **The editor's lost write under locking (0/100) was NOT a runtime self-race.** The sidecars show
   that every one of the 1,100 completions of each pessimistic edit-review arm is 55 tokens long —
   the length of a `read_state` call (a `write_state` call is 76–97, `DONE` 5 in the unguarded arm,
   where 147 of 500 completions have a write's length) — so the editor never attempted its write:
   it repeated its first step in each of its six turns, re-acquiring the lock that refused the
   reviewer. The only difference in its context from the unguarded arm is the reviewer's REFUSED
   tool result, which AutoGen's group chat delivers to every participant and which named no agent.
   Two controls on record agree: under SI the editor repeated a step of its own in every one of the
   44 refused sessions (28 blind rewrites of doc, 16 re-reads; 1.44 editor records per session vs
   1.00), and in the 2026-10-14 interleaved run, whose tools surfaced the refusal as a KeyError
   text, the locked editor wrote in 100/100 sessions. The supplement's self-race hypothesis was
   replaced by this; the abstract and C4 now say the 2–4× price is partly the chat's broadcast of
   the refusal; §6.6 says the price measured is that of a refusal in a chat that broadcasts tool
   results, AutoGen's default, not of the lock alone. Fix, not label: the REFUSED text is now a
   protocol parameter (`--refusal-addressed`: names the refused agent, tells the others it is not
   theirs; recorded in protocol.json and refusals.jsonl), probe 302 takes `REFUSAL_ADDRESSED=1`,
   runner step 24 runs the addressed arms (vanilla, pessimistic:drop, pessimistic:retry, SI:drop;
   edit-review + triage; N=100; ~$10), and the fold keys the two protocols under different macros
   (`\RefusalClaude…` vs `\RefusalAddrClaude…`, never mixed; `\RefusalAddrClaudeAvailable`).
   The paper carries a second pending marker for it.

Also found while fixing: (a) the uploaded `paper_receipts_summary.json` carried
`\renewcommand{\VerusCurated}{160}` / `\VerusFull{181}` from the wrong-toolchain step 7, and the
fold's `--from-summary` path merged them into the regenerated claims block (the delivered v7.4
files did not carry them only because the block had been inspected) — `from_summary` now refuses
the Verus totals unless the summary's count.json is a complete count under the pin, and `verus()`
requires `verus_version == pin` (a count without the field is the old runner's and is not folded);
(b) the Claude cost replication (the +109.5% triage cell, `results/pilot_tokens_claude/`) is dated
2026-05-11 in every sidecar and the paper had called it "September" — redated to May 2026 in §6.5,
§6.6 and §M; (c) the supplement said the interleaved Claude run "refuses the reviewer in 99/100"
(gpt-4o's figure) — in that run no reviewer record exists in 100/100; (d) "the triager's operation
is a read with no write" under locking is 89/100 (drop) and 99/100 (retry) in the refusal run —
stated with the counts; (e) the §M placeholder quote is one of several phrasings — said so.
Trimmed to hold 16 pages: the τ-bench sentence and the Retro sentence (with their bibitems), the
conclusion's opening restatement, one transition, one limitation sentence restating prevalence.
