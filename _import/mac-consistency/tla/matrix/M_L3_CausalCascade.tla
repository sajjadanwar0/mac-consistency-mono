---- MODULE M_L3_CausalCascade ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L3(log) /\ CausalCascade(log))

================================================================================
