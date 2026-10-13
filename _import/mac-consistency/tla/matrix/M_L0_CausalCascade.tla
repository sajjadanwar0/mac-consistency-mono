---- MODULE M_L0_CausalCascade ----
EXTENDS Memory, Anomalies, Levels

NoCoOccurrence == ~(L0(log) /\ CausalCascade(log))

================================================================================
