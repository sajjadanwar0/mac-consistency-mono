---------------------------- MODULE CommitOrder ----------------------------
(***************************************************************************)
(* 2026-09-19 round 38.  WHERE L1 SITS AMONG THE CLASSICAL CLASSES.         *)
(*                                                                         *)
(* A hostile reader of the catalog objects that StaleGeneration's minimal  *)
(* witness is serializable (in the order i;j), so A1 "is not an isolation   *)
(* anomaly".  True, and half the story.  The other half is a theorem:       *)
(*                                                                         *)
(*     every StaleGeneration-FREE history is serializable IN COMMIT ORDER.  *)
(*                                                                         *)
(* CommitOrderSerializable(h) says that every operation read exactly the    *)
(* values it would have read had it executed atomically at its commit       *)
(* point; since writes are installed in commit order anyway, that is        *)
(* value-level equivalence to the serial execution in commit order -- the   *)
(* commit-order-preserving serializability of Weikum and Vossen, by value.  *)
(* So L1 is a correctness class, not only a freshness wish, and A1 is its   *)
(* violation up to one over-report (a value overwritten and then restored), *)
(* which MC_CommitOrder.tla exhibits.  The argument is Kung and Robinson's  *)
(* backward validation; nothing here is new except that it is checked.      *)
(*                                                                         *)
(* Conventions, read off Memory.tla and not assumed: a read is stamped      *)
(* Len(log) and sees exactly the commits with write_time <= read_time; a    *)
(* commit is stamped Len(log)+1.  OVERRULED: MC_A1_struct.tla's strict      *)
(* `LatestWriteBefore(h, c, read_time)`, which excludes the commit the      *)
(* reader did see (corrected in the same round).                            *)
(*                                                                         *)
(* The definitions are relational (no CHOOSE, no maximum) so that the       *)
(* TLAPS proof needs no finiteness argument: "whenever k is the latest      *)
(* visible write, the value read is k's".  On finite histories a latest     *)
(* visible write exists whenever any does; MC_CommitOrder.tla checks that   *)
(* this form agrees with Memory.tla's CHOOSE-based LatestWriteBefore and    *)
(* with a literal serial replay.                                            *)
(***************************************************************************)
EXTENDS Memory, Anomalies, TLAPS

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

THEOREM StaleGenerationIsAValidationFailure ==
    \A h \in Seq(OpRecord) : StaleGeneration(h) => ValidationFails(h)
BY DEF StaleGeneration, ValidationFails

THEOREM LostUpdateIsStaleGeneration ==
    \A h \in Seq(OpRecord) : LostUpdate(h) => StaleGeneration(h)
BY DEF LostUpdate, StaleGeneration

THEOREM A1FreeIsCommitOrderSerializable ==
    ASSUME NEW h \in Seq(OpRecord),
           AgentsDoNotOverlap(h), ReadsBeforeCommit(h),
           ReadsReflectMemory(h), ~StaleGeneration(h)
    PROVE  CommitOrderSerializable(h)
<1>1. ASSUME NEW i \in 1..Len(h), NEW c \in h[i].read_set,
             NEW k \in 1..Len(h), c \in h[k].write_set,
             h[i].read_time < h[k].write_time,
             h[k].write_time < h[i].write_time
      PROVE  h[k].write_values[c] = h[i].read_values[c]
    <2>0. h[i] \in OpRecord /\ h[k] \in OpRecord
        OBVIOUS
    <2>1. k # i
        BY <1>1, <2>0 DEF OpRecord
    <2>2. h[i].agent # h[k].agent
        <3> SUFFICES ASSUME h[i].agent = h[k].agent
                     PROVE FALSE
            OBVIOUS
        <3>1. \/ h[i].write_time <= h[k].read_time
              \/ h[k].write_time <= h[i].read_time
            BY <2>1 DEF AgentsDoNotOverlap
        <3>2. h[k].read_time < h[k].write_time
            BY DEF ReadsBeforeCommit
        <3> QED
            BY <1>1, <2>0, <3>1, <3>2 DEF OpRecord
    <2> QED
        BY <1>1, <2>1, <2>2 DEF StaleGeneration
<1>2. ASSUME NEW i \in 1..Len(h), NEW c \in h[i].read_set
      PROVE  ReadsAs(h, WritesBefore(h, c, h[i].write_time), c, h[i].read_values[c])
    <2> DEFINE U == WritesUpTo(h, c, h[i].read_time)
               B == WritesBefore(h, c, h[i].write_time)
               v == h[i].read_values[c]
    <2>0. h[i] \in OpRecord /\ h[i].read_time < h[i].write_time
        BY DEF ReadsBeforeCommit
    <2>1. ReadsAs(h, U, c, v)
        BY DEF ReadsReflectMemory
    <2>2. U \subseteq B
        <3> SUFFICES ASSUME NEW m \in U PROVE m \in B
            OBVIOUS
        <3>1. m \in 1..Len(h) /\ c \in h[m].write_set /\ h[m].write_time <= h[i].read_time
            BY DEF WritesUpTo
        <3>2. h[m] \in OpRecord
            BY <3>1
        <3> QED
            BY <2>0, <3>1, <3>2 DEF WritesBefore, OpRecord
    <2>3. (B = {}) => (v = NULL)
        BY <2>1, <2>2 DEF ReadsAs
    <2>4. ASSUME NEW k \in B, LatestIn(h, B, k)
          PROVE  v = h[k].write_values[c]
        <3>0. k \in 1..Len(h) /\ c \in h[k].write_set /\ h[k].write_time < h[i].write_time
            BY DEF WritesBefore
        <3>1. h[k] \in OpRecord
            BY <3>0
        <3>2. CASE h[k].write_time <= h[i].read_time
            <4>1. k \in U
                BY <3>0, <3>2 DEF WritesUpTo
            <4>2. LatestIn(h, U, k)
                BY <2>2, <2>4, <4>1 DEF LatestIn
            <4> QED
                BY <2>1, <4>1, <4>2 DEF ReadsAs
        <3>3. CASE h[i].read_time < h[k].write_time
            BY <1>1, <3>0, <3>3
        <3> QED
            BY <2>0, <3>1, <3>2, <3>3 DEF OpRecord
    <2> QED
        BY <2>3, <2>4 DEF ReadsAs
<1> QED
    BY <1>2 DEF CommitOrderSerializable
============================================================================
