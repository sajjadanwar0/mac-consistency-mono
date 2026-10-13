---------------------------- MODULE Anomalies ----------------------------

EXTENDS Naturals, Sequences, Memory

------------------------------------------------------------------------
StaleGeneration(h) ==
    \E i, j \in 1..Len(h) :
        /\ i # j
        /\ h[i].agent # h[j].agent
        /\ \E c \in h[i].read_set \cap h[j].write_set :
            /\ h[i].read_time  < h[j].write_time
            /\ h[j].write_time < h[i].write_time
            /\ h[i].read_values[c] # h[j].write_values[c]

------------------------------------------------------------------------
PhantomTool(h) ==
    \E i \in 1..Len(h) :
        /\ h[i].planned_tool # NULL
        /\ h[i].planned_tool \in h[i].read_registry
        /\ h[i].planned_tool \notin h[i].write_registry

------------------------------------------------------------------------
\* 2026-09-15 round 23.  A3 is an EXTERNALIZED effect whose causal basis
\* was retracted: operation j issued its tool effects, and an operation in
\* its causal closure was later aborted.  External effects cannot be recalled,
\* so no later flag on j repairs this.
\* OVERRULED (rounds <= 22): the cataloged A3 was
\*     ~h[j].aborted /\ p \in h[j].preds /\ h[p].aborted
\* which a cascading abort falsifies by flagging j aborted AFTER j's effects
\* were out -- relabeling, not prevention.  It is kept below as
\* CascadeUnpropagated: internal bookkeeping, not the cataloged anomaly.
CausalCascade(h) ==
    \E j \in 1..Len(h), p \in 1..Len(h) :
        /\ h[j].externalized
        /\ p \in h[j].preds
        /\ h[p].aborted

CascadeUnpropagated(h) ==
    \E j \in 1..Len(h), p \in 1..Len(h) :
        /\ ~ h[j].aborted
        /\ p \in h[j].preds
        /\ h[p].aborted

------------------------------------------------------------------------
CausalCascadeResidue(h) ==
    \E j \in 1..Len(h) :
        \E c \in h[j].read_set :
            /\ h[j].read_values[c] # NULL
            /\ \A k \in 1..Len(h) :
                  ~( /\ k # j
                     /\ c \in h[k].write_set
                     /\ h[k].write_time =< h[j].read_time
                     /\ h[k].write_values[c] = h[j].read_values[c] )

------------------------------------------------------------------------
SplitView(h) == FALSE

------------------------------------------------------------------------
ToolEffectReordering(h) ==
    \E i \in 1..Len(h) :
        /\ Len(h[i].io) >= 2
        /\ h[i].co # h[i].io
        /\ IsPermutation(h[i].io, h[i].co)

------------------------------------------------------------------------
StaleGenerationFree(h)         == ~StaleGeneration(h)
PhantomToolFree(h)             == ~PhantomTool(h)
CausalCascadeFree(h)           == ~CausalCascade(h)
CascadeUnpropagatedFree(h)     == ~CascadeUnpropagated(h)
CausalCascadeResidueFree(h)    == ~CausalCascadeResidue(h)
SplitViewFree(h)               == ~SplitView(h)
ToolEffectReorderingFree(h)    == ~ToolEffectReordering(h)

==========================================================================
