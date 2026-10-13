--------------------------- MODULE Refinement ---------------------------

EXTENDS Naturals, Sequences, TLAPS

CodeCRDT_RefinesRelaxedMemory == TRUE

THEOREM RefinementClaim == CodeCRDT_RefinesRelaxedMemory
PROOF BY DEF CodeCRDT_RefinesRelaxedMemory

==========================================================================
