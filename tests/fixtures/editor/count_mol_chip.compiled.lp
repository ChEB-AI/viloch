concept(V0) :- has_atom(V0,_), #count{ V1 : has_atom(V0,V1), o(V1), aromatic(V0) } >= 2.
