---- MODULE MC_A6NotA3 ----
(* 2026-09-15 round 23.  Lattice incomparability of A3 and A6, hosted on the
   parameterized runtime of Guarded.tla.  The base Memory runtime records no
   preds (CompleteWrite sets preds to {}) and has no abort action, so
   CausalCascade is unreachable there and the check cannot produce its witness.
   With G3 on and G6 off, A6 is reachable and A3 is not, so A6 => A3 is violated. *)
EXTENDS Guarded
A6ImpliesA3 == ToolEffectReordering(log) => CausalCascade(log)
====
