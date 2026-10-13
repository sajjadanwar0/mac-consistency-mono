--------------------------- MODULE Streaming ---------------------------

EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Agents, Cells, Values, BufferBound

StreamingOpRecord == [
    agent          : Agents,
    read_set       : SUBSET Cells,
    read_values    : [Cells -> Values],
    read_time      : Nat,
    write_set      : SUBSET Cells,
    write_values   : [Cells -> Values],
    write_time     : Nat,
    io             : Seq(Cells \X Values),
    co             : Seq(Cells \X Values),
    t_s            : Nat,
    t_e            : Nat,
    ext_idx        : Nat,
    private_buffer : SUBSET (Cells \X Values)
]

ObservedPrefix(o, t) ==
    IF t < o.t_s THEN <<>>
    ELSE IF t >= o.t_e THEN o.co
    ELSE SubSeq(o.co, 1, o.ext_idx)

A6Star(history) ==
    \E i \in 1..Len(history), t \in Nat :
        LET o   == history[i]
            obs == ObservedPrefix(o, t)
        IN  /\ Len(o.io) >= 2
            /\ \A k \in 0..Len(o.io) :
                obs # SubSeq(o.io, 1, k)

PreventsA6Star(R) ==
    \A history \in R :
        ~A6Star(history)

UnboundedWriteSet(R) ==
    \A B \in Nat :
        \E history \in R, i \in 1..Len(history) :
            Len(history[i].io) > B

BoundedBuffer(R) ==
    \A history \in R, i \in 1..Len(history), t \in Nat :
        LET o == history[i]
        IN  (t \in (o.t_s..o.t_e))
            => (Len(o.co) - o.ext_idx) <= BufferBound

THEOREM AtomicityStreamingImpossibility ==
    \A R :
        ~ /\ PreventsA6Star(R)
          /\ UnboundedWriteSet(R)
          /\ BoundedBuffer(R)

PROOF_OBLIGATION_AtomicityStreaming ==
    \A R :
        (PreventsA6Star(R) /\ UnboundedWriteSet(R) /\ BoundedBuffer(R))
        => FALSE

==========================================================================
