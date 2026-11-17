concept(V0) :- has_atom(V0,_), #count{ V1,V2 : has_atom(V0,V1), o(V1), has_atom(V0,V2), o(V2), V1 < V2 } > 1.
