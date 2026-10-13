---- MODULE M_L4_CausalCascade ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L4(log) /\ CausalCascade(log))

================================================================================
