---- MODULE M_L4_ToolEffectReordering ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L4(log) /\ ToolEffectReordering(log))

================================================================================
