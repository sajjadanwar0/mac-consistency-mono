---- MODULE MC_A3NotA6 ----
(* 2026-09-15 round 23.  Lattice incomparability of A3 and A6, hosted on the
   parameterized runtime of Guarded.tla.  The base Memory runtime records no
   preds (CompleteWrite sets preds to {}) and has no abort action, so
   CausalCascade is unreachable there and the check cannot produce its witness.
   With G3 off and G6 on, A3 is reachable and A6 is not, so A3 => A6 is violated. *)
EXTENDS Guarded
A3ImpliesA6 == CausalCascade(log) => ToolEffectReordering(log)
====
