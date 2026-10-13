---- MODULE M_L1_PhantomTool ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L1(log) /\ PhantomTool(log))

================================================================================
