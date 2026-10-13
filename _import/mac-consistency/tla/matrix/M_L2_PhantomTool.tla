---- MODULE M_L2_PhantomTool ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L2(log) /\ PhantomTool(log))

================================================================================
