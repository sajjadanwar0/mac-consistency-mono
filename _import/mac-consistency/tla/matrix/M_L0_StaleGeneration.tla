---- MODULE M_L0_StaleGeneration ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L0(log) /\ StaleGeneration(log))

================================================================================
