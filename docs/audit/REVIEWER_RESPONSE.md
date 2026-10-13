# What changed in v4, objection by objection

Four external reviews of v3 (scores 4, 7.5, 3, 6 out of 10) converge on nine
objections. This file maps each to what v4 does about it, and says plainly
which ones only your machine can close. "Done" = in the v4 PDF now; "wired" =
the code, macro and table cell exist and fill themselves when the run finishes
(`scripts/run_experiments.sh`); "open" = not fixable by writing.

| # | Objection (who raised it) | v4 | How |
|---|---|---|---|
| 1 | A7 is not a concurrency anomaly; it fires in 100/100 sequential sessions; "category error" (R1, R3, R4) | **Done** | A7 is no longer in the catalog. It is the **residue predicate R** (Sec. 3.6), defined *outside* the catalog and the lattice, introduced as "not an anomaly, the harm no commit-time discipline reaches". Lattice back to 2^4; the 160 TLC runs are now a *composition* result (the ledger disturbs no lattice point; R excluded iff G7). Title, abstract, contributions, conclusion all say "four anomalies and the residue". Artifact names (`NoA7`, `a7_rescore.py`) are kept and the mapping is stated once. |
| 2 | Theorem 2 is a tautology (R1, R3, R4) | **Done** | Demoted to **Proposition 1** with the open-world hypothesis explicit, (ii) stated as the iff it is, and the alternative named honestly (freezing basis cells = a lock held past commit, priced at the pessimistic column). The text says "immediate ... recorded as a proposition, not a theorem". |
| 3 | L5 proof pending but advertised as verified (all four) | **Done** (honesty) / **open** (proof) | No sentence claims anything verified for the ledger. Abstract: "Verus specification, proof pending". Assurance table row: "model; Verus open". The chain ends at L4. The ledger is $\ell$, composable, not an $L_5$. The proof itself is step 7 of `run_experiments.sh` (needs Verus). |
| 4 | A3 detector ≠ Definition 4 (R1 critical) | **Done** | Sec. 3.3 now claims Def. 4 only under value-unique writes and **checks the hypothesis on the data**: new gate `hypothesis_gates.py` — 600/600 live L2 sessions collision-free, synthetic cascades unique by construction; collisions exist (126 cells) only in traces where A3 is never scored. Recorder-side fix stated (stamp values with writer id). |
| 5 | A2 means different things in TLA+ and Verus (R1, R3) | **Done** | Canonical definition: tool validity = (identifier, signature) membership; the TLA+ predicate is the identifier projection; the two coincide under the re-sign-as-replace encoding the dispatcher uses; recorded in the assurance table as "encoding stated, not proved". |
| 6 | Theorem 1's reach; `Send` fan-out; "answers the wrong question" (R1, R4) | **Done** | "Reach" paragraph after the proof: conditional guarantee over faithful histories; `Send` fan-out named as outside; hypothesis H1 **checked on all 25,637 committed records (0 violations)** by the new gate; runtime enforcement stated; the one false-positive shape counted (0 of 292 witness pairs). |
| 7 | "Verified detector for every predicate" overclaims; assurance levels blurred; flagship study runs unverified Python, not the verified bytes (R1, R4) | **Done** + **wired** | New **Table 2 (assurance)**: every claim labeled model / proof / bytes / port / open with its correspondence hypothesis and gate. Abstract says "four anomalies have verified detectors" and "every claim labeled". The flagship gap is closed by code: `crates/runtime/examples/l1_server.rs` exposes the **verified SiConcurrent store** over stdio and probe 303 gains `--modes verified`, so the live LangGraph study's commit decision is taken by the verified bytes (bridge = 100 lines, listed as trust-base item xi). Its Table 3 row fills itself after step 2 (< $3). |
| 8 | Missing experiments: L5 arm, offset sweep, interleaved cost, real-effect ToolNode, more models (all four) | **wired** | `scripts/run_experiments.sh`: 12 steps, cost and time per step, `--dry-run`, resumable. `claims_from_results.py` turns the receipts into `paper/claims_results.tex` (Table 3 cells, probe-301/302 sentences, the offset-curve figure), and `reproduce.sh` runs it. Tested end to end on synthetic receipts in the probes' exact schema. |
| 9 | Related work: Agentic Transaction, "Commit Before Trust", HAT, why-provenance, commutativity CC, exactly-once streaming, LLM nondeterminism, chopping; comparison table (R1, R3, R4) | **Done** (one open) | All added and verified against the sources today, except **"Commit Before Trust" (IEEE Xplore 11689396), which I could not reach from the sandbox** — open it, confirm title/authors/venue, and add the bib entry plus one sentence in Sec. 7.2. Comparison table: supplement Appendix V (Table S11). |
| 10 | Census undercuts motivation (R2, R3, R4) | **Done** | Confronted in the introduction ("What this paper is not claiming"), in Sec. 8 ("the census points the other way"), and the abstract reports it as a negative prevalence result. |
| 11 | A1+A7 = 100 is method-circular (R4) | **Done** | Sec. 3.6 and 6.1: the two sides are computed independently (outcome column compares store state; R reads trace write order); extractor recall measured (900/900, because the booking tool takes the date as a structured argument); blind spot stated as a lower bound. |
| 12 | Public README (L0–L4, 274/295) does not match the paper (R1) | **open — yours** | Push the monorepo, tag `v4-submission`, regenerate `crates/runtime/README.md` from `verus_count.sh --json` (the claims gate fails on it on purpose until you do), and put the tag in the paper's artifact footnote. |
| 13 | Two-value lattice safety half never re-run on the current model (R4) | **Done** (in this sandbox) / re-run yours | `formal/tla/lattice16_v2.sh`; outcome recorded in the paper (`\LatticeVtwoOutcome`) and `README.md`. |
| 14 | n=100 single runs, fixed offset, provider drift (all) | **wired** | Steps 3, 5, 6 of the runner; the paper's abstract now qualifies every rate with "at a 150 ms race offset". |

## What I cannot do from here, and what it costs you

* Steps 2–3, 5–6, 10–11 need your API keys: ≈ $3 + $6 + $3 + $15 + $3 + $15 ≈ **$45** at n=100 (headroom within $200 for a second seed of step 2 and 3).
* Step 7 needs the pinned Verus build; step 8 tlapm; step 9 is only CPU (~3 h).
* Item 12 is a git push and a tag.

## Rating, honestly

The reviews were right that v3's 7.5 counted pending items as if done. v4 as
shipped — every objection that could be fixed by definition, proof scope,
gate, or text is fixed — is a **6.5/10** paper with a **8/10 skeleton**: the
remaining distance is exactly the runs above. With steps 1–9 done and the
README synchronized: **8/10**, and the "flagship runs unverified code"
objection is gone because the verified arm *is* the flagship. 9 still needs
a production trace or a second framework driven live.
