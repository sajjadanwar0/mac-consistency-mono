---------------------------- MODULE Hierarchy ----------------------------

EXTENDS Naturals, Sequences, Memory, Anomalies, Levels

------------------------------------------------------------------------
THEOREM L1_Implies_L0 ==
    \A h \in Seq(OpRecord) : L1(h) => L0(h)
  PROOF BY DEF L0, L1

THEOREM L2_Implies_L1 ==
    \A h \in Seq(OpRecord) : L2(h) => L1(h)
  PROOF BY DEF L1, L2

THEOREM L3_Implies_L2 ==
    \A h \in Seq(OpRecord) : L3(h) => L2(h)
  PROOF BY DEF L2, L3

THEOREM L4_Implies_L3 ==
    \A h \in Seq(OpRecord) : L4(h) => L3(h)
  PROOF BY DEF L3, L4

------------------------------------------------------------------------
THEOREM L2_PreventsA1 ==
    \A h \in Seq(OpRecord) : L2(h) => StaleGenerationFree(h)
  PROOF BY DEF L2, L1

THEOREM L3_PreventsA1 ==
    \A h \in Seq(OpRecord) : L3(h) => StaleGenerationFree(h)
  PROOF BY DEF L3, L2, L1

THEOREM L3_PreventsA3 ==
    \A h \in Seq(OpRecord) : L3(h) => CausalCascadeFree(h)
  PROOF BY DEF L3, L2

THEOREM L4_PreventsA1 ==
    \A h \in Seq(OpRecord) : L4(h) => StaleGenerationFree(h)
  PROOF BY DEF L4, L3, L2, L1

THEOREM L4_PreventsA3 ==
    \A h \in Seq(OpRecord) : L4(h) => CausalCascadeFree(h)
  PROOF BY DEF L4, L3, L2

THEOREM L4_PreventsA6 ==
    \A h \in Seq(OpRecord) : L4(h) => ToolEffectReorderingFree(h)
  PROOF BY DEF L4, L3

------------------------------------------------------------------------
THEOREM Hierarchy ==
    \A h \in Seq(OpRecord) :
        /\ L1(h) => L0(h)
        /\ L2(h) => L1(h)
        /\ L3(h) => L2(h)
        /\ L4(h) => L3(h)
  PROOF BY L1_Implies_L0, L2_Implies_L1, L3_Implies_L2, L4_Implies_L3

==========================================================================
