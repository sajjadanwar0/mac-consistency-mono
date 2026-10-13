--------------------------- MODULE Refinement ---------------------------

EXTENDS CodeCRDT, TLAPS

phiVars == <<phiLog, phiInflight, phiRegistry, phiMemory>>

THEOREM Init_Refines ==
    Init => MemoryProjection!Init
PROOF

    OMITTED

THEOREM CompleteWrite_Refines ==
    \A a \in Agents :
        CompleteWrite(a) /\ vars' = phiVars'
        => MemoryProjection!CompleteWrite(a)
PROOF

    OMITTED

THEOREM SyncReplica_Stutters ==
    \A a \in Agents :
        SyncReplica(a) => UNCHANGED phiVars
PROOF

    BY DEF SyncReplica, phiLog, phiInflight, phiRegistry, phiMemory,
           GlobalMemory, ApplyForward

THEOREM CodeCRDT_Refines_RelaxedMemory ==
    Spec => phiVars
PROOF
    OMITTED

==========================================================================
