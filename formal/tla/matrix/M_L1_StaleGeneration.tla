---- MODULE M_L1_StaleGeneration ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L1(log) /\ StaleGeneration(log))

================================================================================
