---- MODULE M_L0_ToolEffectReordering ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L0(log) /\ ToolEffectReordering(log))

================================================================================
