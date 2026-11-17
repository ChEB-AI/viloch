concept(V0) :- has_atom(V0,V1), c(V1), #count{ V2 : has_atom(V0,V2), o(V2), bDOUBLE(V1,V2) } = 0.
