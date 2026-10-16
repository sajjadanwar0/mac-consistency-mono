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
