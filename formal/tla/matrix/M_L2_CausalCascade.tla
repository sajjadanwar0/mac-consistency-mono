---- MODULE M_L2_CausalCascade ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L2(log) /\ CausalCascade(log))

================================================================================
