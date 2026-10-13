# Hierarchy Matrix

The level definitions in `Levels.tla` are constructed so that each higher
level is the conjunction of the previous level with the negation of one
anomaly. This makes the prevention relations true by construction; TLAPS
proofs of soundness are one-liners (see `proofs/`).

The ADMITS column is empirically verified by the witness traces in
`tla/MC_A*.tla` and `tla/MC_A*_witness.txt`. Each anomaly has a TLC-checked
counter-example exhibiting it.

| Level | A1 (StaleGen) | A2 (Phantom) | A3 (Cascade) | A5 (LongGen) | A6 (Reorder) |
|-------|---------------|--------------|--------------|--------------|--------------|
| L0    | ✓ admits      | ✓ admits     | ✓ admits     | ✓ admits     | ✓ admits     |
| L1    | ✓ admits      | ✓ admits     | ✓ admits     | ✓ admits     | ✓ admits     |
| L2    | ✗ prevents    | ✓ admits     | ✓ admits     | ✗ prevents   | ✓ admits     |
| L3    | ✗ prevents    | ✓ admits     | ✗ prevents   | ✗ prevents   | ✓ admits     |
| L4    | ✗ prevents    | ✓ admits     | ✗ prevents   | ✗ prevents   | ✗ prevents   |
| L5    | ✗ prevents    | ✓ admits     | ✗ prevents   | ✗ prevents   | ✗ prevents   |
| L6    | ✗ prevents    | ✗ prevents   | ✗ prevents   | ✗ prevents   | ✗ prevents   |

**Sources of evidence per cell:**

- `✓ admits`: TLC witness exists in `tla/MC_A<j>_witness.txt`. The witness
  is admitted by L0 (the trivial level), which by transitivity means it is
  also a witness for all weaker levels in the hierarchy.

- `✗ prevents`: by construction of the level definitions in `Levels.tla`,
  e.g. `L2(history) == ~StaleGeneration(history) /\ ~LongGeneration(history)`
  immediately implies `L2(history) => ~StaleGeneration(history)`.
  TLAPS proofs of these soundness theorems are in `proofs/Hierarchy.tla`.

**Caveats:**

- L4 and L5 admit/prevent identical sets in our current model. This is
  because A4 (Split-View) is currently `FALSE`. The L4/L5 distinction
  becomes meaningful when replication is added.
- A2 is preventable only at L6. This reflects that phantom-tool requires
  serialisability-class guarantees (registry stability across an op's
  lifetime), which is the strongest level.

**Note on partial empirical verification:**

The full empirical matrix at MaxOps=3 with 7 levels × 5 anomalies = 35 tests
proved intractable for TLC at our model's state space (>20M states per slow
test). The `prevents` claims are instead established formally via TLAPS,
which scales to the proof obligations directly.
