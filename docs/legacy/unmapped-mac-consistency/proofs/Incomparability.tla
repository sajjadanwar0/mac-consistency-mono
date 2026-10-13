--------------------------- MODULE Incomparability ---------------------------
EXTENDS Memory, Anomalies, Levels, TLAPS

WitnessL3b_NotL3a(h) == L3b(h) /\ ~L3a(h)
WitnessL3a_NotL3b(h) == L3a(h) /\ ~L3b(h)

THEOREM IncomparabilityL3aL3b ==
    \E h1, h2 \in Seq(OpRecord) :
        /\ WitnessL3b_NotL3a(h1)
        /\ WitnessL3a_NotL3b(h2)
PROOF
    OMITTED

THEOREM L4_IsMeet ==
    \A h \in Seq(OpRecord) : L4(h) <=> (L3a(h) /\ L3b(h))
PROOF BY DEF L4
==========================================================================
