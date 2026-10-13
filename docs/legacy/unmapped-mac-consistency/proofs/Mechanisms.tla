--------------------------- MODULE Mechanisms ---------------------------
EXTENDS Memory, Anomalies

ReadSetLock(h, i) ==
    ~ \E k \in 1..Len(h) :
        /\ k # i
        /\ h[k].write_time > h[i].read_time
        /\ h[k].write_time < h[i].write_time
        /\ h[k].write_set \cap h[i].read_set # {}

ValueAgreement(h, i) ==
    \A k \in 1..Len(h) :
        (k # i
         /\ h[k].write_time > h[i].read_time
         /\ h[k].write_time < h[i].write_time)
        =>
        \A c \in h[i].read_set \cap h[k].write_set :
            h[k].write_values[c] = h[i].read_values[c]

A1Mechanism(h, i) == ReadSetLock(h, i) \/ ValueAgreement(h, i)

RegistryStable(h, i) ==
    h[i].planned_tool # NULL =>
        (h[i].planned_tool \in h[i].read_registry =>
         h[i].planned_tool \in h[i].write_registry)

AppendOnlyRegistry(h) ==
    \A i, j \in 1..Len(h) :
        (i < j) => h[i].read_registry \subseteq h[j].read_registry

A2Mechanism(h, i) == RegistryStable(h, i)
==========================================================================
