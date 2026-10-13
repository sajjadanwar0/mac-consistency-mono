------------------------------- MODULE Guarded -------------------------------
(*
  Guarded: the Memory runtime of Memory.tla with four INDEPENDENT prevention
  disciplines, each switched by a constant, so that every point of the
  Boolean lattice 2^{A1,A2,A3,A6} is realized by ONE parameterized runtime:

    G1  read-set validation at commit (the SSI gate): an operation whose
        read set was overwritten after its read_time may not commit.
    G2  registry validation at commit: a planned tool that has been removed
        may not be dispatched.
    G3  causal tracking with OUTPUT COMMIT (2026-09-15 round 23): an
        operation records the committed writers whose values it read
        (transitively closed); it may not commit if any of them is aborted;
        its tool effects externalize only once every operation in its closure
        has externalized; an externalized operation is irrevocable (abort is
        refused); and an abort retracts every operation that has the aborted
        one in its closure -- none of which can have externalized.
        Without G3 effects externalize at commit and abort is unrestricted.
        OVERRULED (rounds <= 22): G3 externalized at commit and let abort
        retract externalized operations, satisfying the old flag-based A3 by
        relabeling dependents whose effects were already out.
    G6  commit-order sequencing: effects externalize in issuance order.

  The four disciplines act on disjoint carriers (read_set/write_time;
  registry/planned_tool; preds/aborted; io/co).  For a guard set S the
  realizability claim is: every anomaly in S is prevented on every reachable
  state, and every anomaly not in S has a reachable witness.  lattice16.sh
  checks all 16 configurations with TLC.

  Abort models saga retraction at the trace level (the `aborted` flag);
  compensation of memory contents is not modeled: a retracted value stays in
  memory, and under G3 a reader of it can neither commit nor externalize.
  CausalCascade (Anomalies.tla) depends on the aborted and externalized flags
  and on preds, not on memory contents.
*)
EXTENDS Naturals, Sequences, FiniteSets, TLC, Anomalies

CONSTANTS G1, G2, G3, G6
ASSUME G1 \in BOOLEAN /\ G2 \in BOOLEAN /\ G3 \in BOOLEAN /\ G6 \in BOOLEAN

(* committed writers whose value the read set observed, transitively closed *)
Observed(rs, rv) ==
    { k \in 1..Len(log) :
        \E c \in rs : /\ c \in log[k].write_set
                      /\ rv[c] # NULL
                      /\ log[k].write_values[c] = rv[c] }

Closure(P) == P \cup UNION { log[p].preds : p \in P }

(* a write to a read cell landed after the read *)
ReadSetStale(op) ==
    \E k \in 1..Len(log) :
        \E c \in op.read_set : /\ c \in log[k].write_set
                               /\ log[k].write_time > op.read_time

GCompleteWrite(a) ==
    /\ inflight[a].pending
    /\ Len(log) < MaxOps
    /\ LET op    == inflight[a]
           preds == Closure(Observed(op.read_set, op.read_values))
       IN
       /\ G1 => ~ReadSetStale(op)
       /\ G2 => (op.planned_tool = NULL \/ op.planned_tool \in registry)
       /\ G3 => (\A p \in preds : ~log[p].aborted)
       /\ \E ws \in SUBSET Cells :
          \E wv \in [Cells -> Values \cup {NULL}] :
          \E ioPerm \in Bijections(ws) :
          \E coPerm \in Bijections(ws) :
              /\ \A c \in Cells : (c \in ws) <=> (wv[c] # NULL)   \* write exactly the write set
              /\ G6 => (coPerm = ioPerm)
              /\ LET ioSeq == [i \in 1..Cardinality(ws) |-> <<ioPerm[i], wv[ioPerm[i]]>>]
                     coSeq == [i \in 1..Cardinality(ws) |-> <<coPerm[i], wv[coPerm[i]]>>]
                     newOp == [
                        pending        |-> FALSE,
                        agent          |-> a,
                        read_set       |-> op.read_set,
                        read_values    |-> op.read_values,
                        read_registry  |-> op.read_registry,
                        planned_tool   |-> op.planned_tool,
                        read_time      |-> op.read_time,
                        write_set      |-> ws,
                        write_values   |-> wv,
                        write_registry |-> registry,
                        write_time     |-> Len(log) + 1,
                        io             |-> ioSeq,
                        co             |-> coSeq,
                        aborted        |-> FALSE,
                        preds          |-> preds,
                        externalized   |-> ~G3 ]
                 IN  /\ log'      = Append(log, newOp)
                     /\ memory'   = [c \in Cells |-> IF c \in ws THEN wv[c] ELSE memory[c]]
                     /\ inflight' = [inflight EXCEPT ![a] = EmptyOp(a)]
    /\ UNCHANGED <<registry>>

(* an operation refused by a guard is dropped (its generation is lost);
   modeled as clearing the in-flight record without a log entry *)
GDrop(a) ==
    /\ inflight[a].pending
    /\ inflight' = [inflight EXCEPT ![a] = EmptyOp(a)]
    /\ UNCHANGED <<log, registry, memory>>

(* saga retraction of a committed operation; with G3 the retraction cascades
   to every operation whose closure contains it *)
GAbort(k) ==
    /\ k \in 1..Len(log)
    /\ ~log[k].aborted
    /\ G3 => ~log[k].externalized
    /\ log' = [i \in 1..Len(log) |->
                IF i = k \/ (G3 /\ k \in log[i].preds)
                THEN [log[i] EXCEPT !.aborted = TRUE]
                ELSE log[i]]
    /\ UNCHANGED <<inflight, registry, memory>>

(* output commit (G3): a committed, unaborted operation externalizes its tool
   effects once every operation in its causal closure has externalized *)
GExternalize(k) ==
    /\ G3
    /\ k \in 1..Len(log)
    /\ ~log[k].externalized
    /\ ~log[k].aborted
    /\ \A p \in log[k].preds : log[p].externalized
    /\ log' = [log EXCEPT ![k].externalized = TRUE]
    /\ UNCHANGED <<inflight, registry, memory>>

GNext ==
    \/ \E a \in Agents : StartRead(a) \/ GCompleteWrite(a)
    \/ \E t \in Tools  : RemoveTool(t)
    \/ \E k \in 1..MaxOps : GAbort(k) \/ GExternalize(k)

GSpec == Init /\ [][GNext]_vars

Perms == Permutations(Agents) \cup Permutations(Cells)

NoA1 == ~StaleGeneration(log)
NoA2 == ~PhantomTool(log)
NoA3 == ~CausalCascade(log)
NoA6 == ~ToolEffectReordering(log)

(* round 23 checks beyond the sixteen-point matrix *)
NoCascadeUnpropagated   == ~CascadeUnpropagated(log)
ExternalizedIrrevocable == \A k \in 1..Len(log) : log[k].externalized => ~log[k].aborted
NoExternalizedDependent == ~\E k \in 1..Len(log) : log[k].externalized /\ log[k].preds # {}
==============================================================================
