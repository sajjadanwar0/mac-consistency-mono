-------------------------- MODULE MC_CommitOrder --------------------------
\* TLC harness for the claims of CommitOrder.tla (2026-09-19 round 38).
\*
\* TLAPS proves the theorem. TLC cannot replace that proof and does not try to.
\* What it settles, and TLAPS does not, is what the theorem SAYS: that its
\* hypotheses are jointly satisfiable with a write inside a read window (the
\* proof is not vacuous), that each hypothesis is doing work, that the converse
\* fails (so StaleGeneration over-reports, and by exactly which shape), that the
\* relational definitions agree with Memory.tla's CHOOSE-based helper and with
\* a literal serial replay in commit order, and that StaleGeneration also fires
\* on histories that ARE serializable in some other order.
\*
\* SOUNDNESS OF THE PROJECTION. Every predicate below reads seven of OpRecord's
\* fifteen fields; records agreeing on those seven are indistinguishable to all
\* of them. The generator stamps times exactly as Memory.tla does: the n-th
\* commit has write_time n, and a read is stamped with a log length at or
\* before its own commit. Read values are FREE here, so the store axiom is a
\* hypothesis that can be dropped; MC_CommitOrder_Memory.tla checks that the
\* operational model satisfies it.
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Agents, Cells, Values, NULL, MaxLen

Rec == [ agent        : Agents,
         read_set     : SUBSET Cells,
         read_values  : [Cells -> Values \cup {NULL}],
         read_time    : 0..MaxLen,
         write_set    : SUBSET Cells,
         write_values : [Cells -> Values \cup {NULL}],
         write_time   : 1..MaxLen ]

\* --- verbatim from Anomalies.tla -------------------------------------
StaleGeneration(h) ==
    \E i, j \in 1..Len(h) :
        /\ i # j
        /\ h[i].agent # h[j].agent
        /\ \E c \in h[i].read_set \cap h[j].write_set :
            /\ h[i].read_time  < h[j].write_time
            /\ h[j].write_time < h[i].write_time
            /\ h[i].read_values[c] # h[j].write_values[c]

\* --- verbatim from Memory.tla ----------------------------------------
LatestWriteBefore(h, c, tau) ==
    LET candidates == {k \in 1..Len(h) :
                          /\ h[k].write_time < tau
                          /\ c \in h[k].write_set}
    IN  IF candidates = {} THEN NULL
        ELSE LET kmax == CHOOSE k \in candidates :
                            \A k2 \in candidates : h[k2].write_time <= h[k].write_time
             IN h[kmax].write_values[c]

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

\* BEGIN SHARED-CLASSICAL (kept byte-identical across modules; the fix script diffs them)
\* Kung and Robinson's backward validation fails: some committed write meets
\* the read set inside the read phase.  No agent conjunct, no value conjunct.
ValidationFails(h) ==
    \E i, j \in 1..Len(h) :
        /\ i # j
        /\ \E c \in h[i].read_set \cap h[j].write_set :
            /\ h[i].read_time  < h[j].write_time
            /\ h[j].write_time < h[i].write_time

\* The classical lost update (Berenson et al., P4): a stale reader that also
\* writes the cell it read.
LostUpdate(h) ==
    \E i, j \in 1..Len(h) :
        /\ i # j
        /\ h[i].agent # h[j].agent
        /\ \E c \in (h[i].read_set \cap h[i].write_set) \cap h[j].write_set :
            /\ h[i].read_time  < h[j].write_time
            /\ h[j].write_time < h[i].write_time
            /\ h[i].read_values[c] # h[j].write_values[c]
\* END SHARED-CLASSICAL

\* --- the machine that enumerates histories ---------------------------
VARIABLE h
Init == h = << >>
Next == /\ Len(h) < MaxLen
        /\ \E r \in Rec :
            /\ r.write_time = Len(h) + 1
            /\ r.read_time <= Len(h)
            /\ \A c \in Cells \ r.read_set  : r.read_values[c]  = NULL
            /\ \A c \in Cells \ r.write_set : r.write_values[c] = NULL
            /\ h' = Append(h, r)
Spec == Init /\ [][Next]_h

WF(g) == AgentsDoNotOverlap(g) /\ ReadsBeforeCommit(g) /\ ReadsReflectMemory(g)

\* --- serial replay ----------------------------------------------------
\* Memory after the first n operations of the order p (p[1] runs first).
RECURSIVE MemAfter(_, _, _)
MemAfter(g, p, n) ==
    IF n = 0 THEN [c \in Cells |-> NULL]
    ELSE [c \in Cells |-> IF c \in g[p[n]].write_set
                          THEN g[p[n]].write_values[c]
                          ELSE MemAfter(g, p, n - 1)[c]]

\* Every operation, run atomically in the order p, reads what it recorded.
ReplayAgrees(g, p) ==
    \A n \in 1..Len(g) : \A c \in g[p[n]].read_set :
        g[p[n]].read_values[c] = MemAfter(g, p, n - 1)[c]

CommitOrder(g) == [n \in 1..Len(g) |-> n]          \* write_time n is index n
Orders(g) == { p \in [1..Len(g) -> 1..Len(g)] : \A a, b \in 1..Len(g) : a # b => p[a] # p[b] }
WindowWrite(g) ==
    \E i, k \in 1..Len(g) : \E c \in g[i].read_set \cap g[k].write_set :
        g[i].read_time < g[k].write_time /\ g[k].write_time < g[i].write_time

\* --- the claims -------------------------------------------------------
Theorem                  == (WF(h) /\ ~StaleGeneration(h)) => CommitOrderSerializable(h)
NotVacuous               == ~(WF(h) /\ ~StaleGeneration(h) /\ WindowWrite(h))
Converse                 == (WF(h) /\ CommitOrderSerializable(h)) => ~StaleGeneration(h)
DropAgentsDoNotOverlap   == (ReadsBeforeCommit(h) /\ ReadsReflectMemory(h) /\ ~StaleGeneration(h)) => CommitOrderSerializable(h)
DropStoreAxiom           == (AgentsDoNotOverlap(h) /\ ReadsBeforeCommit(h) /\ ~StaleGeneration(h)) => CommitOrderSerializable(h)
CosIsSerialReplay        == CommitOrderSerializable(h) <=> ReplayAgrees(h, CommitOrder(h))
CosMatchesChoose         == CommitOrderSerializable(h) <=>
                               \A i \in 1..Len(h) : \A c \in h[i].read_set :
                                   h[i].read_values[c] = LatestWriteBefore(h, c, h[i].write_time)
StoreAxiomMatchesChoose  == ReadsReflectMemory(h) <=>
                               \A i \in 1..Len(h) : \A c \in h[i].read_set :
                                   h[i].read_values[c] = LatestWriteBefore(h, c, h[i].read_time + 1)
A1IsAValidationFailure   == StaleGeneration(h) => ValidationFails(h)
ValidationIsNoStronger   == ValidationFails(h) => StaleGeneration(h)
LostUpdateIsA1           == LostUpdate(h) => StaleGeneration(h)
A1OnlyOnNonSerializable  == (WF(h) /\ StaleGeneration(h)) => ~ \E p \in Orders(h) : ReplayAgrees(h, p)
=============================================================================
