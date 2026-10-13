---- MODULE M_L1_CausalCascade ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L1(log) /\ CausalCascade(log))

================================================================================
