---- MODULE M_L0_PhantomTool ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L0(log) /\ PhantomTool(log))

================================================================================
