---- MODULE MC_A0_vacuous ----

EXTENDS Memory, Anomalies

LostSelfWriteFree == ~LostSelfWrite(log)

====
