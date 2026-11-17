concept(M) :- has_atom(M,_), #count{ A,B : has_atom(M,A), has_atom(M,B), o(A), o(B), A < B } > 1.
