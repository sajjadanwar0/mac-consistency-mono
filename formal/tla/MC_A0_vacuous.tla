---- MODULE MC_A0_vacuous ----
(* The empty-history point of the lattice: with no operations, every
   cataloged predicate is FALSE.  Checked at MaxOps = 0 so that the safety
   runs of lattice16.sh are known not to hold vacuously for a reason TLC
   cannot see (an unsatisfiable predicate), and the witness runs
   MC_A1..MC_A6 show each predicate is satisfiable once MaxOps > 0. *)
EXTENDS Memory, Anomalies

AllFree ==
    /\ ~StaleGeneration(log)
    /\ ~PhantomTool(log)
    /\ ~ToolEffectReordering(log)
    /\ ~CausalCascadeResidue(log)

====
