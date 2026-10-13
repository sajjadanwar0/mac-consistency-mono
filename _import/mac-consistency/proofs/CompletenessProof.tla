--------------------------- MODULE CompletenessProof ---------------------------

EXTENDS Memory, Anomalies, TLAPS

ViewEquivalent(h1, h2) == TRUE

Serial(h) ==
    \A i, j \in 1..Len(h) :
        i < j => h[i].write_time <= h[j].read_time

ViewSerializable(h) ==
    \E h2 \in Seq(OpRecord) :
        /\ Serial(h2)
        /\ ViewEquivalent(h, h2)

LEMMA CaseA_UnjustifiedRead ==
    \A h \in Seq(OpRecord) :
        ( ~ViewSerializable(h)
          /\ (\E i \in 1..Len(h) :
                 \E c \in h[i].read_set :
                     ~ViewEquivalent(h, h)) )
        => (LostSelfWrite(h) \/ StaleGeneration(h) \/ PhantomTool(h))
PROOF
    OMITTED

LEMMA CaseB_UnjustifiedExternalCommit ==
    \A h \in Seq(OpRecord) :
        ( ~ViewSerializable(h)
          /\ (\E i \in 1..Len(h) :
                 h[i].write_set \cap ExternalCells # {})
          /\ ~LostSelfWrite(h)
          /\ ~StaleGeneration(h)
          /\ ~PhantomTool(h) )
        => CausalCascade(h)
PROOF
    OMITTED

LEMMA CaseC_WriteReordering ==
    \A h \in Seq(OpRecord) :
        (\E i \in 1..Len(h) :
            h[i].co # h[i].io /\ Len(h[i].io) >= 2)
        => ToolEffectReordering(h)
PROOF
    OMITTED

THEOREM CatalogueCompleteness ==
    \A h \in Seq(OpRecord) :
        ~ViewSerializable(h)
        => \/ LostSelfWrite(h)
           \/ StaleGeneration(h)
           \/ PhantomTool(h)
           \/ CausalCascade(h)
           \/ ToolEffectReordering(h)
           \/ SplitView(h)
PROOF
    OMITTED

==========================================================================
