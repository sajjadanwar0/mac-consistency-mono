# Hostile re-review of v4 (`paper/main.pdf`, 16 pp. + `paper/supplement.pdf`, 30 pp.)

v4 answers four external reviews of v3 (4, 7.5, 3, 6 /10). `REVIEWER_RESPONSE.md`
maps each objection to the change. This file is my own pass over the result,
with the same seven questions, after compiling it and reading the extracted
text against the gates' numbers.

## Does the proof have logical gaps?
* **Theorem 1** is unchanged and now scoped in the text: a conditional
  guarantee over faithful histories; `Send` fan-out named as outside; the
  hypothesis Lemma 1 needs (per-agent non-overlap) is checked on all 25,637
  committed records by a gate that fails on the first violation (0 found).
  The reviewer's "answers the wrong question" stands as a matter of taste:
  the paper now says in the same breath that CORC is orthogonal to the
  post-commit harm, and that the residue predicate exists because of it.
* **Proposition 1** (formerly Theorem 2) claims only what it has: an
  impossibility under the open-world hypothesis and a definitional iff. The
  text calls both "immediate". A referee can no longer say the paper
  dresses a definition as a theorem; they can still say the proposition is
  thin, which it is.
* **A2 and A3 correspondences** are now stated as what they are: an encoding
  (A2) and a hypothesis checked on every scored trace (A3). Neither is a
  mechanized equivalence; the assurance table says so in its own words.
* **The residue predicate** no longer inflates the catalog or the lattice.
  Its one logical risk is the extractor: argument provenance under-reaches,
  the text says so, and the recall on this workload (900/900) is measured,
  not assumed. The partition identity is explained as the agreement of two
  independent computations, which is correct, and the gate enforces it.
* **Open, and said to be open**: the ledger's Verus proof; the refinement of
  the concurrent stores; the verified-detector wiring. Nothing in the text
  leans on any of them.

## Are the claims supported by the data?
* Every v3 number stands and three new ones are gate-derived (0 overlaps /
  25,637; 0 of 292 overwrite-restore; 900/900 recall; 600/600 collision-free
  live L2 sessions). The two-value safety half is re-run on the current
  model in this sandbox (see README last lines).
* The abstract now leads with the predicate--harm gap and the cost per sound
  operation, qualifies the live rates with the race offset, and reports the
  census as a negative prevalence result.
* Still pending, and printed as "--": the verified arm and the ledger arm of
  the live study, the offset sweep, the real-effect ToolNode replay, the
  interleaved cost rerun. All five are one script away; none is a sentence
  away.

## Does related work miss anything?
Added and verified today: Agentic Transaction (2608.13900), HAT (Bailis et
al. 2014), why-provenance (Buneman et al. 2001; Green et al. 2007), view
maintenance (Gupta--Mumick 1995), commutativity-based CC (Weihl 1988),
transaction chopping (Shasha et al. 1995), MillWheel and Flink's
transactional sinks, LLM nondeterminism (Atil et al. 2024), the framework
repositories. A comparison table of the closest systems is Table S11.
**One cannot-verify**: "Commit Before Trust" (IEEE Xplore 11689396) was
unreachable from the sandbox; it is left for you to confirm and add.

## Failure points that remain
1. The verified arm, the ledger arm and the sweep are unrun. Until step 2 of
   the runner executes, the flagship study still runs an application-layer
   L1 and the ledger's benefit is a prediction. This is the objection that
   survives any rewrite.
2. The ledger's Verus proof is a draft. Step 7.
3. A production trace or a second framework driven live: not in the artifact.
4. n=100 single runs and one offset until steps 3/5/6.
5. The public README disagrees with the paper until you push and tag.

## Rating
* v4 as shipped: **6.5/10** — the text no longer overclaims anywhere I can
  find, every formal relation is labeled with its assurance level, and the
  one new predicate is positioned as a residue rather than an anomaly. What
  holds it below 7 is not writing: it is the five "--" cells.
* v4 + steps 1–9 of the runner + the README/tag: **8/10**. The verified arm
  makes the flagship study run the verified bytes, which closes the
  reviewers' structural objection rather than answering it; the ledger has
  a proof and a measurement; the rates become a curve.
* 9 needs what no script here supplies: a production trace or a second
  framework with a matching outcome table.

## Will it be accepted at a top journal?
With steps 1–9 done: a credible major-revision-then-accept at IEEE TSE or
ACM TOSEM. The reviewers' three decisive objections (L5 unproved and
unmeasured; A3 detector ≠ definition; verification and measurement never
on one system) are answered respectively by a proof you run, a hypothesis
the gate checks on every scored trace, and a bridge that puts the verified
store behind the live study. Without the runs: major revision, with the
"--" cells requested by name — exactly as before, but now with the code,
the cost and the time to fill them stated in the paper's own artifact.
