concept(V0) :- has_atom(V0,_), 6 <= #count{ V1 : has_atom(V0,V1), c(V1) } <= 10.
