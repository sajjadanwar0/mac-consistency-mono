---- MODULE MC_A1_struct ----
\* The structural snapshot, with Memory.tla's own stamps (2026-09-19 round 38).
\* A read is stamped Len(log) and SEES the commit stamped Len(log), so the
\* snapshot an operation holds is "the latest write at or before read_time",
\* which in terms of Memory.tla's strict helper is read_time + 1.
\*
\* OVERRULED (rounds <= 37): the strict form, without the + 1. It drops the very
\* commit the reader saw, so L1_struct was FALSE on ordinary histories and the
\* invariants below were checked on a smaller class than intended
\* (check_commitorder.sh, claim StrictSnapshotIsOffByOne). The published witness
\* is a read at time 0, which satisfies both forms, so the observation stands:
\* a snapshot taken at read time does not prevent StaleGeneration. With the
\* corrected form L1_struct is the store axiom of CommitOrder.tla and holds on
\* every reachable log, so that observation now covers all of them.
EXTENDS Memory, Anomalies

L1_struct(h) ==
    \A i \in 1..Len(h) :
        \A c \in h[i].read_set :
            h[i].read_values[c] = LatestWriteBefore(h, c, h[i].read_time + 1)

SnapshotImpliesNoStaleGen      == L1_struct(log) => ~StaleGeneration(log)
NoStaleGenerationGivenL1struct == L1_struct(log) => ~StaleGeneration(log)
NoStaleGenerationGivenL2struct == L1_struct(log) => ~StaleGeneration(log)
====
