--------------------------- MODULE MC_A1LowerBound ---------------------------
\* TLC harness for the claims of A1LowerBound.tla.
\*
\* SOUNDNESS OF THE PROJECTION. Memory.tla's OpRecord has fifteen fields, two
\* of them Seq-valued and therefore not enumerable by TLC. StaleGeneration,
\* ReadSetLock, ValueAgreement, NonOverlappingAgent and MonotonicOp reference
\* exactly seven: agent, read_set, read_values, read_time, write_set,
\* write_values, write_time. Records agreeing on those seven are
\* indistinguishable to every predicate below, so checking over the projection
\* is sound for these claims and for no others.
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Agents, Cells, Values, NULL, MaxLen, MaxTime

LBRecord == [ agent        : Agents,
              read_set     : SUBSET Cells,
              read_values  : [Cells -> Values \cup {NULL}],
              read_time    : 0..MaxTime,
              write_set    : SUBSET Cells,
              write_values : [Cells -> Values \cup {NULL}],
              write_time   : 0..MaxTime ]

\* --- verbatim from Anomalies.tla -------------------------------------
StaleGeneration(h) ==
    \E i, j \in 1..Len(h) :
        /\ i # j
        /\ h[i].agent # h[j].agent
        /\ \E c \in h[i].read_set \cap h[j].write_set :
            /\ h[i].read_time  < h[j].write_time
            /\ h[j].write_time < h[i].write_time
            /\ h[i].read_values[c] # h[j].write_values[c]

\* --- verbatim from Mechanisms.tla ------------------------------------
ReadSetLock(h, i) ==
    ~ \E k \in 1..Len(h) :
        /\ k # i
        /\ h[k].write_time > h[i].read_time
        /\ h[k].write_time < h[i].write_time
        /\ h[k].write_set \cap h[i].read_set # {}

ValueAgreement(h, i) ==
    \A k \in 1..Len(h) :
        (k # i
         /\ h[k].write_time > h[i].read_time
         /\ h[k].write_time < h[i].write_time)
        =>
        \A c \in h[i].read_set \cap h[k].write_set :
            h[k].write_values[c] = h[i].read_values[c]

A1Mechanism(h, i) == ReadSetLock(h, i) \/ ValueAgreement(h, i)

\* --- verbatim from A1LowerBound.tla ----------------------------------
NonOverlappingAgent(h) ==
    \A i, j \in 1..Len(h) :
        (i # j /\ h[i].agent = h[j].agent)
        => (h[i].write_time <= h[j].read_time
            \/ h[j].write_time <= h[i].read_time)

MonotonicOp(h) ==
    \A m \in 1..Len(h) : h[m].read_time <= h[m].write_time

\* --- the machine that enumerates traces -------------------------------
VARIABLE h
Init == h = << >>
Next == Len(h) < MaxLen /\ \E r \in LBRecord : h' = Append(h, r)
Spec == Init /\ [][Next]_h

\* --- the claims -------------------------------------------------------
\* C1: the disjunction in A1Mechanism is degenerate -- its first disjunct
\*     implies its second, so A1Mechanism is ValueAgreement alone.
Degenerate == \A i \in 1..Len(h) : ReadSetLock(h, i) => ValueAgreement(h, i)

\* C2: the theorem as stated in A1LowerBound.tla.
TheoremHolds ==
    (NonOverlappingAgent(h) /\ MonotonicOp(h) /\ ~StaleGeneration(h))
    => \A i \in 1..Len(h) : A1Mechanism(h, i)

\* C3: the CONVERSE also holds, so the theorem is an equivalence and not a
\*     one-way bound.
ConverseHolds ==
    (NonOverlappingAgent(h) /\ MonotonicOp(h)
     /\ (\A i \in 1..Len(h) : A1Mechanism(h, i)))
    => ~StaleGeneration(h)

\* C4/C5: each hypothesis dropped in turn. Both are EXPECTED TO BE VIOLATED;
\*        a violation is the evidence that the hypothesis is load-bearing.
DropNonOverlapping ==
    (MonotonicOp(h) /\ ~StaleGeneration(h))
    => \A i \in 1..Len(h) : A1Mechanism(h, i)

DropMonotonic ==
    (NonOverlappingAgent(h) /\ ~StaleGeneration(h))
    => \A i \in 1..Len(h) : A1Mechanism(h, i)

\* C6: does the converse need the hypotheses at all?
ConverseUnconditional ==
    (\A i \in 1..Len(h) : ValueAgreement(h, i)) => ~StaleGeneration(h)

\* C7: and does the FORWARD direction still need them once the degenerate
\*     disjunct is removed?
ForwardValueAgreementOnly ==
    (NonOverlappingAgent(h) /\ MonotonicOp(h) /\ ~StaleGeneration(h))
    => \A i \in 1..Len(h) : ValueAgreement(h, i)
==============================================================================
