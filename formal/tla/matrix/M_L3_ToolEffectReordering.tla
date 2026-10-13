---- MODULE M_L3_ToolEffectReordering ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L3(log) /\ ToolEffectReordering(log))

================================================================================
