---------------------------- MODULE Memory ----------------------------

EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS Agents, Cells, Values, Tools, NULL, MaxOps, ExternalCells, AllowSkew

ASSUME
    /\ NULL \notin Values
    /\ ExternalCells \subseteq Cells
    /\ AllowSkew \in BOOLEAN

VARIABLES log, inflight, registry, memory

vars == <<log, inflight, registry, memory>>

InitialMemory == [c \in Cells |-> NULL]

OpRecord == [
    pending        : BOOLEAN,
    agent          : Agents,
    read_set       : SUBSET Cells,
    read_values    : [Cells -> Values \cup {NULL}],
    read_registry  : SUBSET Tools,
    planned_tool   : Tools \cup {NULL},
    read_time      : Nat,
    write_set      : SUBSET Cells,
    write_values   : [Cells -> Values \cup {NULL}],
    write_registry : SUBSET Tools,
    write_time     : Nat,
    io             : Seq(Cells \X (Values \cup {NULL})),
    co             : Seq(Cells \X (Values \cup {NULL})),
    aborted        : BOOLEAN,
    preds          : SUBSET Nat
]

EmptyOp(a) == [
    pending        |-> FALSE,
    agent          |-> a,
    read_set       |-> {},
    read_values    |-> InitialMemory,
    read_registry  |-> {},
    planned_tool   |-> NULL,
    read_time      |-> 0,
    write_set      |-> {},
    write_values   |-> InitialMemory,
    write_registry |-> {},
    write_time     |-> 0,
    io             |-> <<>>,
    co             |-> <<>>,
    aborted        |-> FALSE,
    preds          |-> {}
]

Bijections(S) ==
    LET n == Cardinality(S)
    IN  {f \in [1..n -> S] : \A i, j \in 1..n : i # j => f[i] # f[j]}

IsPermutation(p, q) ==
    /\ Len(p) = Len(q)
    /\ \A i \in 1..Len(p) :
        Cardinality({k \in 1..Len(p) : p[k] = p[i]}) =
        Cardinality({k \in 1..Len(q) : q[k] = p[i]})

LatestWriteBefore(h, c, tau) ==
    LET candidates == {k \in 1..Len(h) :
                          /\ h[k].write_time < tau
                          /\ c \in h[k].write_set}
    IN  IF candidates = {} THEN NULL
        ELSE LET kmax == CHOOSE k \in candidates :
                            \A k2 \in candidates : h[k2].write_time <= h[k].write_time
             IN h[kmax].write_values[c]

Init ==
    /\ log      = <<>>
    /\ inflight = [a \in Agents |-> EmptyOp(a)]
    /\ registry = Tools
    /\ memory   = InitialMemory

StartRead(a) ==
    /\ ~inflight[a].pending
    /\ Len(log) < MaxOps

    /\ \E rs \in SUBSET Cells, pt \in registry \cup {NULL},
          rv \in [Cells -> Values \cup {NULL}] :
        /\ (~AllowSkew) => (rv = memory)
        /\ inflight' = [inflight EXCEPT ![a] = [
            pending        |-> TRUE,
            agent          |-> a,
            read_set       |-> rs,
            read_values    |-> rv,
            read_registry  |-> registry,
            planned_tool   |-> pt,
            read_time      |-> Len(log),
            write_set      |-> {},
            write_values   |-> InitialMemory,
            write_registry |-> {},
            write_time     |-> 0,
            io             |-> <<>>,
            co             |-> <<>>,
            aborted        |-> FALSE,
            preds          |-> {}]]
    /\ UNCHANGED <<log, registry, memory>>

CompleteWrite(a) ==
    /\ inflight[a].pending
    /\ Len(log) < MaxOps
    /\ \E ws \in SUBSET Cells :
        \E wv \in [Cells -> Values \cup {NULL}] :
            \E ioPerm \in Bijections(ws) :
                \E coPerm \in Bijections(ws) :
                    LET ioSeq == [i \in 1..Cardinality(ws) |->
                                    <<ioPerm[i], wv[ioPerm[i]]>>]
                        coSeq == [i \in 1..Cardinality(ws) |->
                                    <<coPerm[i], wv[coPerm[i]]>>]
                        newOp == [
                            pending        |-> FALSE,
                            agent          |-> a,
                            read_set       |-> inflight[a].read_set,
                            read_values    |-> inflight[a].read_values,
                            read_registry  |-> inflight[a].read_registry,
                            planned_tool   |-> inflight[a].planned_tool,
                            read_time      |-> inflight[a].read_time,
                            write_set      |-> ws,
                            write_values   |-> wv,
                            write_registry |-> registry,
                            write_time     |-> Len(log) + 1,
                            io             |-> ioSeq,
                            co             |-> coSeq,
                            aborted        |-> FALSE,
                            preds          |-> {}]
                    IN  /\ log'      = Append(log, newOp)
                        /\ memory'   = [c \in Cells |->
                                IF c \in ws THEN wv[c] ELSE memory[c]]
                        /\ inflight' = [inflight EXCEPT ![a] = EmptyOp(a)]
    /\ UNCHANGED <<registry>>

RemoveTool(t) ==
    /\ t \in registry
    /\ registry' = registry \ {t}
    /\ UNCHANGED <<log, inflight, memory>>

Next ==
    \/ \E a \in Agents : StartRead(a) \/ CompleteWrite(a)
    \/ \E t \in Tools  : RemoveTool(t)

Spec == Init /\ [][Next]_vars

=============================================================================
