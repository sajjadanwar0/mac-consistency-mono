# Second round, receipts of 2026-10-14: what landed, what the audit found, what is still pending

Receipts received (runner steps 14–19 on the author's machine): `results/paper_receipts_summary.json`,
`tools/arm_timing.log`, `tools/live_runs.log`, `tools/hypothesis_gates.log`, `tools/cargo_build.log`,
`results/live_a1_outcome/*` (probe 303: sequential run, offset sweep, three interleaved runs of five arms),
the probe-304 console output (per-session world states), the probe-301 verified-L3 replay, the TLC
`Duplication.tla` log. The paper was regenerated from them; every receipt-derived number in the two `.tex`
files is a macro of `paper/claims_results.tex`, inlined into both files (the claims gate now fails when the
inlined block is stale or the two files disagree).

## What the receipts established

* Probe 303, three interleaved runs per family: A1 = 0/300 in every L1 arm; residue (R) 7/300 and 2/300 on
  haiku, 109 vs 104 on gpt-4o-mini, 185 vs 194 on deepseek-chat for the validated vs verified arms; ledger
  and ledger-verified 0/300 wrong bookings everywhere. The paired (McNemar) comparison of the two L1 arms is
  null on all three families (p = 0.180 / 0.735 / 0.474); the sequential-run haiku difference (12 vs 2,
  p = 0.010) did not replicate. The run, not the arm, is where the residue moves (vanilla A1 94/100
  sequential vs 296/300 interleaved on haiku, p = 0.018; validated residue 12/100 vs 7/300, p < 0.001).
* Probe 301 with the verified L3 bytes deciding the release order under concurrent dispatch: A6 0/165
  (SQLite, baseline 119/165) and 0/165 (HTTP, baseline 113/165).
* Hypothesis gates over every committed record: 56,079 records, 15,891 traces, 0 H0/H1 violations,
  1,299 A1 witnesses with 0 overwrite-restore shapes, basis recovered for 9,000/9,000 bookings,
  0 duplicate external effects among 9,900, 0 undeclared store reads over 5,400 records carrying an observed
  read set.
* Probe 304 (the ledger in a world), first run: R = 0 in all 300 ledger sessions, yet at session end a stale
  booking is active in 12/16/16 sessions and none in 6/9/12 (the injected refusal rate seen from the other
  side), a consumer reading within 1.5 s saw the final booking in 5/2/1 sessions, and in 1/5/10 sessions the
  ledger reported every obligation discharged while a stale booking was active.

## Two defects the receipts exposed, both fixed in this version

1. `crates/analyser` rejected every probe-303 record: the reader declared `agent_id` as a serde alias of
   `agent`, and the records carry both keys (same value). The verified-scorer gate therefore failed on every
   trace (4,818 problems) and its receipt had been folded as "available". Fix: `oprecord.rs` reconciles the
   two keys explicitly (equal → accepted, different → error, neither → error; five unit tests);
   `claims_from_results.py` marks the cell available only when the gate reports zero problems. The paper's
   verified-scorer cell stays pending until the rerun of step 14.
2. Probe 304's compensator tracked one confirmation per effect and drafted the replacement by a model call
   between the cancellation and the rebooking: a retry after a refused cancellation cancelled the replacement,
   left the original booking active and reported the obligation discharged. Fix: `--compensator all`
   (default) drafts first, cancels every active stale confirmation, rebooks, discharges only on full success;
   `--compensator latest` reproduces the first run. Runner step 18 archives the first run's receipts under
   `results/ledger_world_v1_latest_conf/` and reruns; the paper reports the first run (compensator `latest`)
   with the flaw as a finding and marks the rerun pending.

Also fixed: the pilot's pessimistic/SI runtimes could not import `baselines` (a namespace package the
migration filed under `results/`); the pilot now locates it and the runner puts its parent on `PYTHONPATH`.
`live_runs_aggregate.py` printed a Wald interval under "exact CI" when SciPy was absent; it now computes
Clopper–Pearson by bisection (the paper never used that column). Runner step 13 no longer runs `pdflatex`
unless `BUILD_PDF=1`.

## Independent hostile audit of the regenerated text (subagent, 2026-10-14) and what changed in response

* "1–65%" was not the range of any set the sentence named → stated as pooled per family and arm, with the
  per-run range 0–73% beside it. Offset-sweep residue range corrected to 40–52. "Four arms" / 4,500 made
  precise (900 October-sequential + 3,600 interleaved L1 sessions). 2.3× → 2.2× in the supplement.
* The world-wrong / none shares are the injected refusal rate seen from the other side → said so in §6.2 and
  removed from the abstract. "Fifth predicate" → "a predicate outside the catalog". "Show" → "observe" for
  the open-world remark; the measured ledger named as harness code in the abstract.
* "Indistinguishable" / "cannot tell apart" → the paired test with its interval ("detects no arm
  difference; bounds one at a few points on haiku, about ten elsewhere"); the Fisher tests remain in the
  supplement.
* The ledger invariant speaks of records and is satisfied vacuously by a misreporting compensator (§5.5);
  the open-world remark's never-cleared hypothesis vs the executable ledger (§3.6); the stamp convention
  behind the store axiom (§2); where H1 is load-bearing (§3.1).
* Stale supplement cross-references (pilot table, "Tables 3, 4 and 7", "Finding 6"), the S15 L3 row, the
  T′ counts, "triage void" → fixed. §6.7 now says which Claude run its cost numbers come from.
* Title changed from "Isolation Is Not the Harm …" (two independent reads: it generalizes a one-scenario
  finding) to "What Commit-Time Isolation Leaves Behind: …"; the former title is kept as a comment.
* Related work: Strom & Yemini 1985 (origin of output commit) and Korth, Levy & Silberschatz 1990 (formal
  compensation) added.
* The pilot table, the ToolNode table and the classical-correspondence table moved to the supplement to hold
  the main text at 16 pages.

## Pending (each marked in the text)

Step 14 rerun (verified scorer, no keys); step 18 rerun (probe 304 with the corrected compensator); step 11
(Claude pessimistic/SI cells and the rerun triage cell's A1, scored by the verified detector); step 6 (probe
302 interleaved on Claude; the 3-session stub campaign is resumed, not recreated).
