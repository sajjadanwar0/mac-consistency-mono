-------------------------- MODULE A3_witness_check --------------------------
(* The cataloged causal-cascade predicate on literal histories.
   2026-09-15 round 23: A3 is an EXTERNALIZED operation with an aborted
   operation in its causal closure.  CascadeUnpropagated is the pre-round-23
   predicate (a surviving, unaborted dependent), kept to show what it missed:
   on h_relabeled a cascading abort flagged the dependent AFTER its effects
   were out, so CascadeUnpropagated is silent while CausalCascade fires.
   h_deferred is the output-commit outcome: the dependent had not
   externalized when the cascade reached it, so neither predicate fires.
   The residue still fires on the benign serial history, which reads a value
   no logged operation wrote. *)
EXTENDS Naturals, Sequences, Anomalies

\* The predicates are the cataloged ones in Anomalies.tla (not local copies),
\* so this check fails if the catalog's CausalCascade stops requiring an
\* externalized dependent.  A3_witness_check.cfg supplies Memory's constants.

Writer(ab, ext) ==
    [ aborted      |-> ab,
      externalized |-> ext,
      preds        |-> {},
      read_set     |-> {},
      read_time    |-> 0,
      read_values  |-> << >>,
      write_set    |-> {"c1"},
      write_time   |-> 1,
      write_values |-> [x \in {"c1"} |-> "v1"] ]

Reader(ab, ext, ps) ==
    [ aborted      |-> ab,
      externalized |-> ext,
      preds        |-> ps,
      read_set     |-> {"c1"},
      read_time    |-> 1,
      read_values  |-> [x \in {"c1"} |-> "v1"],
      write_set    |-> {},
      write_time   |-> 2,
      write_values |-> << >> ]

\* the writer externalized at commit and was retracted; the reader survived
h_cascade   == << Writer(TRUE, TRUE),  Reader(FALSE, TRUE, {1}) >>
\* the same, but a cascade flagged the reader after its effects were out
h_relabeled == << Writer(TRUE, TRUE),  Reader(TRUE, TRUE, {1}) >>
\* output commit: neither had externalized when the retraction cascaded
h_deferred  == << Writer(TRUE, FALSE), Reader(TRUE, FALSE, {1}) >>
\* a serial read of a value no logged operation wrote
h_benign    == << [ Reader(FALSE, TRUE, {}) EXCEPT !.write_time = 1 ] >>

VARIABLE dummy
\* Memory's variables take its Init and never move: only the literal histories matter.
WInit == dummy = 0 /\ Init
WNext == UNCHANGED <<dummy, vars>>
WSpec == WInit /\ [][WNext]_<<dummy, vars>>

Result ==
    /\ CausalCascade(h_cascade)    /\ CascadeUnpropagated(h_cascade)
    /\ CausalCascade(h_relabeled)  /\ ~ CascadeUnpropagated(h_relabeled)
    /\ ~ CausalCascade(h_deferred) /\ ~ CascadeUnpropagated(h_deferred)
    /\ ~ CausalCascade(h_benign)   /\ CausalCascadeResidue(h_benign)
=============================================================================
