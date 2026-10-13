---- MODULE M_L2_StaleGeneration ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L2(log) /\ StaleGeneration(log))

================================================================================
