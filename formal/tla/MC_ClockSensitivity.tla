------------------------- MODULE MC_ClockSensitivity -------------------------
\* Is A_1 an anomaly, or an artifact of the logical clock the trace carries?
\*
\* Section 5.13 reports the same live sessions firing 42/100, 72/100 and
\* 26/100 under the COMPLETION clock (write times ordered by the order node
\* bodies returned) and 0/100 under the BARRIER clock (all writes of one
\* superstep land at a single tick), while the summarizer commits on a plan
\* value the same superstep superseded in every session. This module
\* separates the two notions and states their relationship, so the numbers
\* stop looking like a contradiction.
\*
\* A record carries both clocks:
\*   read_barrier / write_barrier   the superstep the read was taken from and
\*                                  the superstep the write lands in
\*   write_order                    position in the completion clock
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Agents, Cells, Values, NULL, MaxLen, MaxBarrier, MaxOrder

CRecord == [ agent         : Agents,
             read_set      : SUBSET Cells,
             read_values   : [Cells -> Values \cup {NULL}],
             read_barrier  : 0..MaxBarrier,
             write_set     : SUBSET Cells,
             write_values  : [Cells -> Values \cup {NULL}],
             write_barrier : 0..MaxBarrier,
             write_order   : 0..MaxOrder ]

\* Two candidate well-formedness conditions, kept SEPARATE because only one
\* of them turns out to do any work (the runner proves which).
\*
\*   ReadBeforeWrite      an operation reads state committed strictly before
\*                        the barrier it writes in.
\*   ClockRefinesBarrier  the completion clock refines the barrier order: a
\*                        node body cannot return before a barrier that
\*                        precedes it has closed. This is the one a runtime
\*                        must actually guarantee.
ReadBeforeWrite(h) ==
    \A m \in 1..Len(h) : h[m].read_barrier < h[m].write_barrier

ClockRefinesBarrier(h) ==
    \A m, n \in 1..Len(h) :
        h[m].write_barrier < h[n].write_barrier
        => h[m].write_order < h[n].write_order

\* Definition 1, parameterised by the clock that supplies the two times.
Conflict(h, i, j, c) ==
    /\ i # j
    /\ h[i].agent # h[j].agent
    /\ c \in h[i].read_set \cap h[j].write_set
    /\ h[i].read_values[c] # h[j].write_values[c]

\* COMPLETION clock: read at the barrier boundary, write at its return slot.
A1Temporal(h) ==
    \E i, j \in 1..Len(h), c \in Cells :
        /\ Conflict(h, i, j, c)
        /\ h[i].read_barrier < h[j].write_barrier
        /\ h[j].write_order  < h[i].write_order

\* BARRIER clock: both times are barrier indices.
A1Barrier(h) ==
    \E i, j \in 1..Len(h), c \in Cells :
        /\ Conflict(h, i, j, c)
        /\ h[i].read_barrier  < h[j].write_barrier
        /\ h[j].write_barrier < h[i].write_barrier

\* SEMANTIC: the reader committed on a value a different agent superseded
\* before the reader's own effect became authoritative -- i.e. no later than
\* the reader's own barrier. Mentions NO completion order, so it cannot vary
\* with the order node bodies happen to return.
A1Semantic(h) ==
    \E i, j \in 1..Len(h), c \in Cells :
        /\ Conflict(h, i, j, c)
        /\ h[i].read_barrier   < h[j].write_barrier
        /\ h[j].write_barrier <= h[i].write_barrier

VARIABLE h
Init == h = << >>
Next == Len(h) < MaxLen /\ \E r \in CRecord : h' = Append(h, r)
Spec == Init /\ [][Next]_h

\* C1: firing under the barrier clock implies semantic staleness, with NO
\*     hypothesis at all -- it mentions no completion order.
BarrierImpliesSemantic == A1Barrier(h) => A1Semantic(h)

\* C2: firing under the completion clock implies semantic staleness, given
\*     that the completion clock refines the barrier order. This is what
\*     makes 42/100 a lower bound on 100/100 rather than a rival figure.
TemporalImpliesSemantic ==
    ClockRefinesBarrier(h) => (A1Temporal(h) => A1Semantic(h))

\* C3: and that hypothesis is load-bearing -- EXPECTED VIOLATED. Without it a
\*     body may return before an earlier barrier has closed, and the
\*     completion clock then witnesses an order the barriers deny.
TemporalNeedsRefinement == A1Temporal(h) => A1Semantic(h)

\* C4: the converse fails -- EXPECTED VIOLATED. The gap between 42 and 100.
SemanticImpliesTemporal ==
    ClockRefinesBarrier(h) => (A1Semantic(h) => A1Temporal(h))

\* C5: when every write lands in one barrier the barrier clock cannot witness
\*     anything: its window needs write_barrier_j < write_barrier_i. This is
\*     why 0/100 is definitional and not a measurement.
OneBarrierBlindsBarrierClock ==
    (\A m, n \in 1..Len(h) : h[m].write_barrier = h[n].write_barrier)
    => ~A1Barrier(h)

\* C6: the completion clock is NOT blind there -- EXPECTED VIOLATED, which is
\*     precisely the sensitivity Section 5.13 observed.
OneBarrierBlindsCompletionClock ==
    ClockRefinesBarrier(h)
    /\ (\A m, n \in 1..Len(h) : h[m].write_barrier = h[n].write_barrier)
    => ~A1Temporal(h)
==============================================================================
