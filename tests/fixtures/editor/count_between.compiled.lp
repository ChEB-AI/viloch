concept(V0) :- has_atom(V0,_), 2 <= #count{ V1 : has_atom(V0,V1), n(V1) } <= 4.
