--------------------------- MODULE Duplication ---------------------------
(***************************************************************************)
(* At-most-once externalization, stated as a predicate rather than         *)
(* assumed.  The runtime model of the paper (Memory.tla) externalizes an    *)
(* operation's effects once, at commit.  One deployed resumption path       *)
(* breaks that: LangGraph's `interrupt` resumes a node by re-executing it   *)
(* from its start, so an irreversible effect issued BEFORE the gate is      *)
(* emitted again after it, with different arguments when the shared value   *)
(* was revised during the gate (probes/124_langgraph_interrupt_probe.py;    *)
(* results/python_loose/interrupt_probe_results.json: "EMAIL 14 June",      *)
(* "EMAIL 21 June").  This module is that shape in five actions, with the   *)
(* predicate D the catalog lacked, a TLC witness of the deployed shape, and *)
(* the idempotency guard that restores the hypothesis.                      *)
(*                                                                         *)
(* D is kept OUTSIDE the anomaly catalog and the lattice, like the residue  *)
(* predicate R: it is not a property of the read--generate--commit window   *)
(* but of the executor's replay semantics, and the four disciplines neither *)
(* create nor remove it (its carrier -- the effect stream -- is disjoint    *)
(* from theirs).                                                            *)
(*                                                                         *)
(* A node: read the shared cell, ISSUE an effect derived from the value     *)
(* read, reach a human-in-the-loop GATE, and on approval FINISH.  RESUME    *)
(* re-executes the node from its start (the documented semantics); another  *)
(* agent may REVISE the shared cell at any time.  With Dedup = TRUE an      *)
(* idempotency key (agent, effect) suppresses a second emission.            *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Agents, Values, NULL, Dedup, MaxRevisions

ASSUME NULL \notin Values /\ Dedup \in BOOLEAN /\ MaxRevisions \in Nat

VARIABLES
    emitted,    \* the external effect stream: Seq([agent, arg]); irreversible, append-only
    cell,       \* the shared value the effect is derived from
    phase,      \* [Agents -> {"start", "issued", "gated", "done"}]
    resumed,    \* [Agents -> BOOLEAN]: the node has been resumed once (bounds the state space)
    revisions   \* number of revisions so far (bounded by MaxRevisions)

vars == <<emitted, cell, phase, resumed, revisions>>

Emission == [agent : Agents, arg : Values \cup {NULL}]

TypeOK ==
    /\ emitted \in Seq(Emission)
    /\ cell \in Values \cup {NULL}
    /\ phase \in [Agents -> {"start", "issued", "gated", "done"}]
    /\ resumed \in [Agents -> BOOLEAN]
    /\ revisions \in 0..MaxRevisions

AlreadyEmitted(a) == \E k \in 1..Len(emitted) : emitted[k].agent = a

Init ==
    /\ emitted = <<>>
    /\ cell \in Values
    /\ phase = [a \in Agents |-> "start"]
    /\ resumed = [a \in Agents |-> FALSE]
    /\ revisions = 0

\* The node issues its effect from the value it read (the effect is derived from the
\* cell by copying, as in the live study's booking).  Under Dedup an effect already
\* out for this node is not issued again.
Issue(a) ==
    /\ phase[a] = "start"
    /\ IF Dedup /\ AlreadyEmitted(a)
         THEN emitted' = emitted
         ELSE emitted' = Append(emitted, [agent |-> a, arg |-> cell])
    /\ phase' = [phase EXCEPT ![a] = "issued"]
    /\ UNCHANGED <<cell, resumed, revisions>>

\* The human-in-the-loop gate after the effect (the shape the framework documents as hazardous).
Gate(a) ==
    /\ phase[a] = "issued"
    /\ phase' = [phase EXCEPT ![a] = "gated"]
    /\ UNCHANGED <<emitted, cell, resumed, revisions>>

\* Resume re-executes the node from its START: the read is re-taken and the effect re-issued.
Resume(a) ==
    /\ phase[a] = "gated"
    /\ ~resumed[a]
    /\ resumed' = [resumed EXCEPT ![a] = TRUE]
    /\ phase' = [phase EXCEPT ![a] = "start"]
    /\ UNCHANGED <<emitted, cell, revisions>>

Finish(a) ==
    /\ phase[a] = "gated"
    /\ phase' = [phase EXCEPT ![a] = "done"]
    /\ UNCHANGED <<emitted, cell, resumed, revisions>>

\* Another agent revises the shared value (at any time; bounded).
Revise ==
    /\ revisions < MaxRevisions
    /\ \E v \in Values \ {cell} : cell' = v
    /\ revisions' = revisions + 1
    /\ UNCHANGED <<emitted, phase, resumed>>

Next ==
    \/ \E a \in Agents : Issue(a) \/ Gate(a) \/ Resume(a) \/ Finish(a)
    \/ Revise

Spec == Init /\ [][Next]_vars

------------------------------------------------------------------------
\* D: one node's effect is out twice (at-most-once externalization violated).
DuplicateEffect ==
    \E i, j \in 1..Len(emitted) :
        /\ i # j
        /\ emitted[i].agent = emitted[j].agent

\* The stronger shape the probe observed: the two emissions carry different arguments,
\* because the shared value was revised during the gate.
DuplicateDivergent ==
    \E i, j \in 1..Len(emitted) :
        /\ i # j
        /\ emitted[i].agent = emitted[j].agent
        /\ emitted[i].arg # emitted[j].arg

AtMostOnce == ~DuplicateEffect
NoDivergentDuplicate == ~DuplicateDivergent

\* Every node that reached "done" has exactly one effect out (under Dedup).
OneEffectPerDoneNode ==
    \A a \in Agents :
        phase[a] = "done" => Cardinality({k \in 1..Len(emitted) : emitted[k].agent = a}) = 1

==========================================================================
