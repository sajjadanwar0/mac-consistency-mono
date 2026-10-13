---- MODULE M_L4_StaleGeneration ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L4(log) /\ StaleGeneration(log))

================================================================================
