------------------------------- MODULE Hierarchy -------------------------------

EXTENDS Memory, Anomalies, Levels, TLAPS

THEOREM L1_Implies_L0 ==
    \A h \in Seq(OpRecord) : L1(h) => L0(h)
PROOF BY DEF L0, L1

THEOREM L2_Implies_L1 ==
    \A h \in Seq(OpRecord) : L2(h) => L1(h)
PROOF BY DEF L2

THEOREM L3_Implies_L2 ==
    \A h \in Seq(OpRecord) : L3(h) => L2(h)
PROOF BY DEF L3

THEOREM L4_Implies_L3 ==
    \A h \in Seq(OpRecord) : L4(h) => L3(h)
PROOF BY DEF L4

THEOREM L2_Prevents_A1 ==
    \A h \in Seq(OpRecord) : L2(h) => StaleGenerationFree(h)
PROOF BY DEF L2, L1

THEOREM L3_Prevents_A1 ==
    \A h \in Seq(OpRecord) : L3(h) => StaleGenerationFree(h)
PROOF BY DEF L3, L2, L1

THEOREM L3_Prevents_A3 ==
    \A h \in Seq(OpRecord) : L3(h) => CausalCascadeFree(h)
PROOF BY DEF L3, L2

THEOREM L4_Prevents_A1 ==
    \A h \in Seq(OpRecord) : L4(h) => StaleGenerationFree(h)
PROOF BY DEF L4, L3, L2, L1

THEOREM L4_Prevents_A3 ==
    \A h \in Seq(OpRecord) : L4(h) => CausalCascadeFree(h)
PROOF BY DEF L4, L3, L2

THEOREM L4_Prevents_A6 ==
    \A h \in Seq(OpRecord) : L4(h) => ToolEffectReorderingFree(h)
PROOF BY DEF L4, L3

THEOREM ChainCoherence ==
    \A h \in Seq(OpRecord) :
        /\ L1(h) => L0(h)
        /\ L2(h) => L1(h)
        /\ L3(h) => L2(h)
        /\ L4(h) => L3(h)
PROOF
  <1> TAKE h \in Seq(OpRecord)
  <1>1. L1(h) => L0(h) BY DEF L0, L1
  <1>2. L2(h) => L1(h) BY DEF L2
  <1>3. L3(h) => L2(h) BY DEF L3
  <1>4. L4(h) => L3(h) BY DEF L4
  <1> QED BY <1>1, <1>2, <1>3, <1>4

==========================================================================
