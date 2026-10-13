---- MODULE CodeCRDT ----

EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS Agents, Cells, Values, Tools, NULL, MaxOps, ExternalCells

VARIABLES log, inflight, syncClock, registry

vars == <<log, inflight, syncClock, registry>>

InitialMemory == [c \in Cells |-> NULL]

EmptyOp(a) == [
    pending |-> FALSE, agent |-> a,
    read_set |-> {}, read_values |-> InitialMemory,
    read_registry |-> {}, planned_tool |-> NULL,
    read_time |-> 0,
    write_set |-> {}, write_values |-> InitialMemory,
    write_registry |-> {}, write_time |-> 0,
    io |-> <<>>, co |-> <<>>
]

RECURSIVE ApplyForward(_, _, _)
ApplyForward(state, k, n) ==
    IF k > n THEN state
    ELSE LET entry == log[k]
             newState == [c \in Cells |->
                IF c \in entry.write_set
                THEN entry.write_values[c]
                ELSE state[c]]
         IN ApplyForward(newState, k + 1, n)

Replica(a) == ApplyForward(InitialMemory, 1, syncClock[a])

GlobalMemory == ApplyForward(InitialMemory, 1, Len(log))

Init ==
    /\ log = <<>>
    /\ inflight = [a \in Agents |-> EmptyOp(a)]
    /\ syncClock = [a \in Agents |-> 0]
    /\ registry = Tools

StartRead(a) ==
    /\ ~inflight[a].pending
    /\ Len(log) < MaxOps
    /\ \E rs \in SUBSET Cells, pt \in registry \cup {NULL}:
        inflight' = [inflight EXCEPT ![a] = [
            pending |-> TRUE, agent |-> a,
            read_set |-> rs,
            read_values |-> Replica(a),
            read_registry |-> registry,
            planned_tool |-> pt,
            read_time |-> Len(log),
            write_set |-> {},
            write_values |-> InitialMemory,
            write_registry |-> {},
            write_time |-> 0,
            io |-> <<>>, co |-> <<>>]]
    /\ UNCHANGED <<log, syncClock, registry>>

CompleteWrite(a) ==
    /\ inflight[a].pending
    /\ Len(log) < MaxOps
    /\ \E ws \in SUBSET Cells, wv \in [Cells -> Values \cup {NULL}]:
        LET newOp == [
            pending |-> FALSE, agent |-> a,
            read_set |-> inflight[a].read_set,
            read_values |-> inflight[a].read_values,
            read_registry |-> inflight[a].read_registry,
            planned_tool |-> inflight[a].planned_tool,
            read_time |-> inflight[a].read_time,
            write_set |-> ws, write_values |-> wv,
            write_registry |-> registry,
            write_time |-> Len(log) + 1,
            io |-> <<>>, co |-> <<>>]
        IN
        /\ log' = Append(log, newOp)
        /\ inflight' = [inflight EXCEPT ![a] = EmptyOp(a)]
        /\ syncClock' = [syncClock EXCEPT ![a] = Len(log) + 1]
    /\ UNCHANGED <<registry>>

SyncReplica(a) ==
    /\ syncClock[a] < Len(log)
    /\ syncClock' = [syncClock EXCEPT ![a] = syncClock[a] + 1]
    /\ UNCHANGED <<log, inflight, registry>>

RemoveTool(t) ==
    /\ t \in registry
    /\ registry' = registry \ {t}
    /\ UNCHANGED <<log, inflight, syncClock>>

Next ==
    \/ \E a \in Agents: StartRead(a) \/ CompleteWrite(a) \/ SyncReplica(a)
    \/ \E t \in Tools: RemoveTool(t)

Spec == Init /\ [][Next]_vars

phiLog       == log
phiInflight  == inflight
phiRegistry  == registry
phiMemory    == GlobalMemory

MemoryProjection ==
    INSTANCE Memory WITH
        log       <- phiLog,
        inflight  <- phiInflight,
        registry  <- phiRegistry,
        memory    <- phiMemory,
        AllowSkew <- TRUE

LostSelfWrite ==
    \E i, j \in 1..Len(log):
        /\ log[i].agent = log[j].agent
        /\ log[i].write_time < log[j].read_time
        /\ \E c \in log[i].write_set \cap log[j].read_set:
            ~ \E k \in 1..Len(log):
                /\ log[k].write_time >= log[i].write_time
                /\ log[k].write_time <= log[j].read_time
                /\ c \in log[k].write_set
                /\ log[k].write_values[c] = log[j].read_values[c]

LostSelfWriteFree == ~LostSelfWrite

StaleGeneration ==
    \E i, j \in 1..Len(log):
        /\ i # j
        /\ log[i].agent # log[j].agent
        /\ log[i].read_time < log[j].write_time
        /\ log[j].write_time < log[i].write_time
        /\ \E c \in log[i].read_set \cap log[j].write_set:
            log[i].read_values[c] # log[j].write_values[c]

StaleGenerationFree == ~StaleGeneration

====
