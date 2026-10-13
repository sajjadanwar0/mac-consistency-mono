---------------------------- MODULE Levels ----------------------------

EXTENDS Naturals, Sequences, Memory, Anomalies

L0(h) == TRUE

L1(h) == StaleGenerationFree(h)

L2(h) == /\ L1(h)
         /\ CausalCascadeFree(h)

L3(h) == /\ L2(h)
         /\ ToolEffectReorderingFree(h)

L4(h) == /\ L3(h)
         /\ PhantomToolFree(h)

==========================================================================
