---------------------- MODULE MC_CommitOrder_Memory ----------------------
\* The theorem of CommitOrder.tla has three hypotheses about a history. This
\* harness checks that they are INVARIANTS of the operational model, so the
\* theorem applies to every reachable log of Memory.tla, and then checks its
\* conclusion there (2026-09-19 round 38).
EXTENDS Memory, Anomalies

\* --- verbatim from CommitOrder.tla -----------------------------------
\* BEGIN SHARED-CORE (kept byte-identical across modules; the fix script diffs them)
WritesUpTo(h, c, t) ==
    { k \in 1..Len(h) : c \in h[k].write_set /\ h[k].write_time <= t }

WritesBefore(h, c, t) ==
    { k \in 1..Len(h) : c \in h[k].write_set /\ h[k].write_time < t }

LatestIn(h, S, k) ==
    k \in S /\ \A m \in S : h[m].write_time <= h[k].write_time

\* v is what a read of c returns when S is the set of writes it can see
ReadsAs(h, S, c, v) ==
    /\ (S = {}) => (v = NULL)
    /\ \A k \in S : LatestIn(h, S, k) => (v = h[k].write_values[c])

\* The store axiom: a read returns the latest commit at or before it.
ReadsReflectMemory(h) ==
    \A i \in 1..Len(h) : \A c \in h[i].read_set :
        ReadsAs(h, WritesUpTo(h, c, h[i].read_time), c, h[i].read_values[c])

\* Every operation read what it would have read at its own commit point.
CommitOrderSerializable(h) ==
    \A i \in 1..Len(h) : \A c \in h[i].read_set :
        ReadsAs(h, WritesBefore(h, c, h[i].write_time), c, h[i].read_values[c])

AgentsDoNotOverlap(h) ==
    \A i, j \in 1..Len(h) :
        (i # j /\ h[i].agent = h[j].agent)
        => (h[i].write_time <= h[j].read_time
            \/ h[j].write_time <= h[i].read_time)

ReadsBeforeCommit(h) ==
    \A m \in 1..Len(h) : h[m].read_time < h[m].write_time
\* END SHARED-CORE

\* OVERRULED: the strict form MC_A1_struct.tla used until this round. A read is
\* stamped Len(log) and sees the commit stamped Len(log); `< read_time` drops it.
StrictSnapshot(h) ==
    \A i \in 1..Len(h) : \A c \in h[i].read_set :
        h[i].read_values[c] = LatestWriteBefore(h, c, h[i].read_time)

\* --- the claims -------------------------------------------------------
HypothesesHoldOnMemory   == AgentsDoNotOverlap(log) /\ ReadsBeforeCommit(log) /\ ReadsReflectMemory(log)
TheoremOnMemory          == (~StaleGeneration(log)) => CommitOrderSerializable(log)
HypothesesAndTheoremOnMemory == HypothesesHoldOnMemory /\ TheoremOnMemory
StrictSnapshotIsOffByOne == StrictSnapshot(log)
SnapshotDoesNotPreventA1 == ReadsReflectMemory(log) => ~StaleGeneration(log)
=============================================================================
