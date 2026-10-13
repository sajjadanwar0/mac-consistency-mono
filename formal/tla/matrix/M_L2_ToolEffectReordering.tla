---- MODULE M_L2_ToolEffectReordering ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L2(log) /\ ToolEffectReordering(log))

================================================================================
