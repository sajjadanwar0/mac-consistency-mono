---- MODULE M_L3_StaleGeneration ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L3(log) /\ StaleGeneration(log))

================================================================================
