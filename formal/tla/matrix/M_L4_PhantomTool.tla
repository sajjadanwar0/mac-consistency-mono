---- MODULE M_L4_PhantomTool ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L4(log) /\ PhantomTool(log))

================================================================================
