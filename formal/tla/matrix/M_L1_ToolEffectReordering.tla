---- MODULE M_L1_ToolEffectReordering ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L1(log) /\ ToolEffectReordering(log))

================================================================================
