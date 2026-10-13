---- MODULE M_L3_PhantomTool ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L3(log) /\ PhantomTool(log))

================================================================================
