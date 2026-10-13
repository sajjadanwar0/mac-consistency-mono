# Hostile review of the submitted version (arXiv:2606.17182, 19 Sep 2026 sources)

Scope of this audit: both documents read in full (25 + 27 pages); every
committed cell rescored with an independent Definition-1 implementation; TLC
witnesses, the 15 CommitOrder verdicts and six of the 64 lattice runs
reproduced (state counts identical to the committed reference); the three
companion repositories cloned and inspected; cost/census/task-utility scorers
re-run offline. Rating of the submitted version: **4.5 / 10**. Verdict: reject
in current form.

## 1. Logical gaps in the proofs

| # | Gap | Evidence | Severity |
|---|---|---|---|
| P1 | Theorem 1 ("L1 is commit-order serializability") is a definitional restatement. `CommitOrderSerializable` is *defined* as "each read equals the latest write before its own commit"; under the store axiom this is ¬A1 modulo the restored-value case. The name borrowed from Weikum–Vossen (COCSR, a conflict-based condition) does not fit a value-level, reads-only condition. | `tla/CommitOrder.tla` lines 60–75 (definition), proof ~40 lines of unfolding | major (naming), minor (math) |
| P2 | The Verus "sound and complete against Definition 1" claim is false as stated: `lib_detector_equivalence.rs::OpRecord` has no `agent` field; `a1_witness` omits the different-agent conjunct and returns false on an absent value. | `verus-detector/src/lib_detector_equivalence.rs:159–175` | major (claim), harmless on model histories (Lemma: `CommitOrder.tla` step ⟨2⟩2) |
| P3 | "Scored by the verified detector" (Tables 2, 3, 6) is false: the scorer is `rust-analyser/src/anomalies.rs`, a hand-written crate with no dependency on `verus-detector`; it also lacks the agent conjunct and compares `Option`s (an absent read value fires). | `rust-analyser/Cargo.toml` (no dep), `anomalies.rs:12–40` | major |
| P4 | L2's A3-freedom is partly enforced by refusing to record the anomaly: `abort_valid ≡ ¬externalized`. The theorem is recoverability + "externalized cannot abort"; the harm (402–549 exposed effects) survives. The paper concedes this but headlines "no reachable state admits A3". | `lib_l2_safety.rs:990` | moderate |
| P5 | The "faithful emitter" proviso of L1j/L2j is violated by the paper's own live harness, which rewrites `read_time` to the validating re-read (`langgraph_live_a1.py:343`), erasing the stale read from the trace. | harness source | moderate |
| P6 | 364 obligations include 86 refinements of superseded representations, 13 of self-described tautology/stubs, 48 re-included modules, 9 for an A4 "theorem" that is a tautology of append-only logs. Load-bearing count ≈ 236. | per-file table (Appendix S) | moderate (presentation) |
| P7 | Model excludes `Send` fan-out (same node name, parallel instances) via per-agent non-overlap; census found 7 such sites. A2 cannot see hallucinated tools; A6 cannot see dropped/duplicated effects (the paper's own `interrupt` probe found duplication). | Sec. 2, 3, 6.2 | minor–moderate |

## 2. Claims vs. data

| # | Claim | What the data say | Where |
|---|---|---|---|
| D1 | "read-set validation removes every firing" (abstract) | True for the flag. The booking contradicts the final trip date in 34/100 (gpt-4o-mini), 7/100 (haiku), 100/100 (Llama) validated sessions; 100/100 in every vanilla and every "sequential control" session. The "material" column is computed as `A1 AND …` and cannot exceed the A1 count. | `python/live_a1_*/results.json`; `harness/outcome_rescore.py --check` |
| D2 | "a concurrent revision lands inside the window in 60% and 91% of sessions" | The harness starts the date agent 150 ms after the flight agent's read; the rate is whether (150 ms + 16-token reply) beats a 96-token reply. | `langgraph_live_a1.py:364–365` |
| D3 | Superstep "300/300 summary grounded in superseded plan" | BSP semantics by construction; the writer is prompted to say Lisbon, the summarizer cannot see it; the completion clock is synthesized (`write_time = entry + #finishes`). Census: 0/407 sites of that shape. | `langgraph_live_a1.py:475–513` |
| D4 | A6 "reproduced on LangGraph's released ToolNode" | Reorder is `asyncio.sleep(uniform(0.01,0.20))`; `co = argsort(latency)` is the definition of `gather`. The real content is the batching behaviour (gpt-4o-mini 30/30, llama 3/30, haiku 0/30) and transcript invisibility (33/33). | `langgraph_a6_experiment_natural.py:59,80` |
| D5 | Artifact ships `l3_live_a6.jsonl` (4 parallel API calls, "L3 sequencer" = a sort; haiku "batched 40/40") which the pilot README headlines ("110/120 → 0/120") and the paper does not report; contradicts Table 6's "haiku 0/30". | user zip; `mac-consistency-pilot/README.md` |
| D6 | L2 Table 7: "every figure is decided by the schedule" — 3,000 single-threaded seeded schedules establish that flipping a flag after release does not retrieve the effect. | Sec. 5.9 | — |
| D7 | Cost: one run, n=100/cell, run-order confound (control drifts −4.9%/+13.5%), post-hoc null band, toy workloads where pessimistic drops the reviewer 99/100. | Sec. 5.5, 5.8 | — |
| D8 | No in-the-wild instance of any cataloged anomaly: the 34 repos hit a writer/writer fail-stop; deer-flow is sequential; Letta is L0 lost-update; census 0 confirmed. | Sec. 5.6, 6.4 | — |
| D9 | Five different obligation totals across the artifact (274/295, 331/352, 338/359, 358/379, 364/385); stale per-file counts in READMEs and in `reproduce_mac.sh` (lib_l2_safety 22 vs 33, lib_l4_safety 5 vs 9, lib_l2_exec 49 vs 73). | the four READMEs, `reproduce_mac.sh:100–123` |
| D10 | `tla/MC_A0_vacuous.tla` does not parse (`LostSelfWrite` undefined); README lists it as expect-hold. | reproduced |
| D11 | Public `mac-consistency` README: A1LowerBound still "Theorem 5.1, generation lower bound" (withdrawn); "L2 model still states the flag form" (contradicts Sec. 4.10); claims `mac-consistency.tex` is in the repo (it is not); `proofs/` duplicate "slated for removal". | README |
| D12 | No committed receipts for Tables 7/8 (L2/L4 measurements) — numbers live in README prose; no tlapm log for `CommitOrder.tla` (60). | repos |
| D13 | Numbers that DO reproduce: all 29 Def-1 cells (84 checks), Table 5 (workcost), Table 6 (realstore_metrics --check), census table, task-utility rows, ToolNode per-turn counts, live-L2 retraction counts (1/3/62), lattice16 sample, 15 CommitOrder verdicts, all TLC witnesses. | this audit |

## 3. Related work missed

MemTX (2607.23929); "Position: Multi-Agent Systems Should Prioritize
Concurrency Control" (2608.18092); Governed Shared Memory (2606.24535);
Multi-Agent Transactive Memory (2606.19911); AsyncLM (2412.07017) and
future-based async function calling (2605.15077); IsolateGPT (NDSS'25);
ToolEmu (ICLR'24); Progent (2504.11703); Gray & Reuter 1993; transactional
boosting (Herlihy–Koskinen 2008); consistency rationing (Kraska et al. 2009);
blackboard architecture (used uncited). SagaLLM author order inconsistent
between the two bibliographies.

## 4. Failure points (ranked)

1. Predicate ≠ harm (D1), unreported.
2. "Verified detector scored the tables" and "Verus restates Def. 1" (P2, P3).
3. Artifact hygiene: five totals, broken model, stale READMEs, three repos, no receipts (D9–D12).
4. Constructed races presented as framework findings (D2–D4).
5. Novelty self-declared as a port; mechanisms are textbook.
6. Form: 52k words, zero figures in the main paper, 61 "withdrawn/earlier version" hedges, in-line arguments with an imagined referee.

## 5. What the v2 rewrite changed (see SELF_AUDIT.md for the hostile re-review)

Every item in §1–§4 is either fixed in `paper/` or stated as a limitation
with a named probe; the predicate/harm gap is now the paper's own finding
(Table 3, Fig. 3); Theorem 1 is renamed to what it proves; the transcription
gap is stated with Lemma 1 and gated; obligations are accounted by what they
bear; the related work is added; the main paper is 14 pages with three
figures and no revision narrative.
