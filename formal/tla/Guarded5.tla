------------------------------- MODULE Guarded5 -------------------------------
(*
  Guarded5: Guarded.tla with a FIFTH anomaly and a FIFTH discipline, so that
  every point of the Boolean lattice 2^{A1,A2,A3,A6,A7} is realized by one
  parameterized runtime.  Guarded.tla and its 64-run reference matrix are left
  untouched; this module repeats the four guards verbatim and adds:

    A7  SUPERSEDED-BASIS EFFECT.  An operation's external effect is derived
        from a BASIS: the (cell, value) pairs its arguments were taken from
        (argument provenance; in the model a nondeterministic subset of the
        operation's read values, so every provenance extractor is covered).
        A7 holds when the effect is out (externalized), some basis cell has
        since been overwritten with a different value by an operation that
        committed AFTER the effect's commit, and no compensation obligation
        has been registered for the effect.  A1 is the window before commit;
        A7 is the window after it -- which, for an irreversible effect whose
        basis is ordinary revisable state, never closes.

    G7  BASIS LEDGER.  (i) At commit the runtime records the effect's basis.
        (ii) When a write commits, every externalized operation whose basis
        holds (c, v) with c written to a value other than v gets a
        compensation obligation registered, atomically with the superseding
        commit.  (iii) An effect released (at commit, or later under output
        commit) on a basis the memory no longer agrees with gets its
        obligation registered at release.  G7 never refuses a step: it is a
        ledger, and refusing to release a stale-basis effect is a policy the
        executable runtime offers on top of it.  Nothing is said here about HOW
        an obligation is discharged (rebook, cancel, ask a human); the ledger
        guarantees only that no superseded effect is out without one -- the
        bounded-delay registration that is the strongest post-commit
        guarantee an irreversible effect admits (main paper, Theorem 2).

  Carriers: A1 read_set/read_time/read_values vs write_set/write_time/
  write_values; A2 registry/planned_tool; A3 preds/aborted/externalized;
  A6 io/co; A7 basis/obligation (read: write_set/write_values/write_time of
  the superseding op).  G7 writes only basis and obligation.
*)
EXTENDS Naturals, Sequences, FiniteSets, TLC, Anomalies

CONSTANTS G1, G2, G3, G6, G7
ASSUME G1 \in BOOLEAN /\ G2 \in BOOLEAN /\ G3 \in BOOLEAN /\ G6 \in BOOLEAN /\ G7 \in BOOLEAN

(* ---------------- the fifth predicate ---------------------------------- *)
SupersededBasisEffect(h) ==
    \E i \in 1..Len(h) :
        /\ h[i].externalized
        /\ ~h[i].obligation
        /\ \E b \in h[i].basis :
            \E j \in 1..Len(h) :
                /\ b[1] \in h[j].write_set
                /\ h[j].write_time > h[i].write_time
                \* j is the LATEST post-commit writer of the basis cell, so a
                \* value overwritten and then restored does not fire
                /\ \A k \in 1..Len(h) :
                      (b[1] \in h[k].write_set /\ h[k].write_time > h[i].write_time)
                        => h[k].write_time <= h[j].write_time
                /\ h[j].write_values[b[1]] # b[2]

SupersededBasisEffectFree(h) == ~SupersededBasisEffect(h)

(* basis entries the memory no longer agrees with *)
BasisStale(b) == \E p \in b : memory[p[1]] # p[2]

(* ---------------- the four guards of Guarded.tla, verbatim ------------- *)
Observed(rs, rv) ==
    { k \in 1..Len(log) :
        \E c \in rs : /\ c \in log[k].write_set
                      /\ rv[c] # NULL
                      /\ log[k].write_values[c] = rv[c] }

Closure(P) == P \cup UNION { log[p].preds : p \in P }

ReadSetStale(op) ==
    \E k \in 1..Len(log) :
        \E c \in op.read_set : /\ c \in log[k].write_set
                               /\ log[k].write_time > op.read_time

(* obligations G7 registers when ws/wv commit: every externalized operation
   whose basis names a cell in ws with a different value *)
Supersedes(k, ws, wv) ==
    /\ log[k].externalized
    /\ \E b \in log[k].basis : b[1] \in ws /\ wv[b[1]] # b[2]

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
          \E basis \in SUBSET { <<c, op.read_values[c]>> : c \in op.read_set } :
              /\ \A c \in Cells : (c \in ws) <=> (wv[c] # NULL)
              /\ G6 => (coPerm = ioPerm)
              /\ LET ioSeq == [i \in 1..Cardinality(ws) |-> <<ioPerm[i], wv[ioPerm[i]]>>]
                     coSeq == [i \in 1..Cardinality(ws) |-> <<coPerm[i], wv[coPerm[i]]>>]
                     \* without G3 the effect leaves at commit (as in Guarded.tla);
                     \* G7 (ii) registers an obligation at once if it leaves on a
                     \* basis the memory no longer agrees with
                     outNow == ~G3
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
                        externalized   |-> outNow,
                        basis          |-> basis,
                        obligation     |-> (G7 /\ outNow /\ BasisStale(basis)) ]
                     \* G7 (ii): register obligations on every effect this
                     \* commit supersedes, atomically with the commit
                     marked == [i \in 1..Len(log) |->
                                 IF G7 /\ Supersedes(i, ws, wv)
                                 THEN [log[i] EXCEPT !.obligation = TRUE]
                                 ELSE log[i]]
                 IN  /\ log'      = Append(marked, newOp)
                     /\ memory'   = [c \in Cells |-> IF c \in ws THEN wv[c] ELSE memory[c]]
                     /\ inflight' = [inflight EXCEPT ![a] = EmptyOp(a)]
    /\ UNCHANGED <<registry>>

GDrop(a) ==
    /\ inflight[a].pending
    /\ inflight' = [inflight EXCEPT ![a] = EmptyOp(a)]
    /\ UNCHANGED <<log, registry, memory>>

GAbort(k) ==
    /\ k \in 1..Len(log)
    /\ ~log[k].aborted
    /\ G3 => ~log[k].externalized
    /\ log' = [i \in 1..Len(log) |->
                IF i = k \/ (G3 /\ k \in log[i].preds)
                THEN [log[i] EXCEPT !.aborted = TRUE]
                ELSE log[i]]
    /\ UNCHANGED <<inflight, registry, memory>>

(* output commit (G3); with G7 a release on a stale basis registers an obligation *)
GExternalize(k) ==
    /\ G3
    /\ k \in 1..Len(log)
    /\ ~log[k].externalized
    /\ ~log[k].aborted
    /\ \A p \in log[k].preds : log[p].externalized
    /\ log' = [log EXCEPT ![k].externalized = TRUE,
                           ![k].obligation   = log[k].obligation \/ (G7 /\ BasisStale(log[k].basis))]
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
NoA7 == ~SupersededBasisEffect(log)

(* sanity: under G7 every externalized operation with a stale basis carries
   an obligation -- the inductive form of NoA7 *)
LedgerInvariant == \A k \in 1..Len(log) :
    (log[k].externalized /\ BasisStale(log[k].basis)) => log[k].obligation
==============================================================================
