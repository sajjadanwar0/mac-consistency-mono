--------------------------- MODULE A1LowerBound ---------------------------

EXTENDS Memory, Anomalies, Mechanisms, TLAPS

NonOverlappingAgent(h) ==
    \A i, j \in 1..Len(h) :
        (i # j /\ h[i].agent = h[j].agent)
        => (h[i].write_time <= h[j].read_time
            \/ h[j].write_time <= h[i].read_time)

MonotonicOp(h) ==
    \A m \in 1..Len(h) : h[m].read_time <= h[m].write_time

THEOREM A1LowerBoundTrace ==
    \A h \in Seq(OpRecord) :
        (NonOverlappingAgent(h) /\ MonotonicOp(h) /\ ~StaleGeneration(h))
        =>
        \A i \in 1..Len(h) :
            A1Mechanism(h, i)
PROOF
    <1>1. SUFFICES ASSUME NEW h \in Seq(OpRecord),
                          NonOverlappingAgent(h),
                          MonotonicOp(h),
                          ~StaleGeneration(h),
                          NEW i \in 1..Len(h),
                          ~A1Mechanism(h, i)
                   PROVE FALSE
        OBVIOUS
    <1>2. /\ ~ReadSetLock(h, i)
          /\ ~ValueAgreement(h, i)
        BY <1>1 DEF A1Mechanism
    <1>3. \E k \in 1..Len(h) :
            /\ k # i
            /\ h[k].write_time > h[i].read_time
            /\ h[k].write_time < h[i].write_time
            /\ \E c \in h[i].read_set \cap h[k].write_set :
                h[k].write_values[c] # h[i].read_values[c]
        BY <1>2 DEF ReadSetLock, ValueAgreement
    <1>4. PICK k \in 1..Len(h) :
            /\ k # i
            /\ h[k].write_time > h[i].read_time
            /\ h[k].write_time < h[i].write_time
            /\ \E c \in h[i].read_set \cap h[k].write_set :
                h[k].write_values[c] # h[i].read_values[c]
        BY <1>3
    <1>5. h[i].agent # h[k].agent

        <2> SUFFICES ASSUME h[i].agent = h[k].agent
                     PROVE FALSE
            OBVIOUS
        <2>1. h[i] \in OpRecord /\ h[k] \in OpRecord
            BY <1>1, <1>4
        <2>2. h[k].read_time <= h[k].write_time
            BY <1>1, <1>4 DEF MonotonicOp
        <2>3. h[i].write_time <= h[k].read_time
              \/ h[k].write_time <= h[i].read_time
            BY <1>1, <1>4 DEF NonOverlappingAgent
        <2> QED
            BY <2>1, <2>2, <2>3, <1>4 DEF OpRecord
    <1>6. StaleGeneration(h)
        BY <1>4, <1>5 DEF StaleGeneration
    <1> QED BY <1>1, <1>6

==========================================================================
