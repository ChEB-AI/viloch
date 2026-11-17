concept(M) :- has_atom(M,_), #count{ A : has_atom(M,A), o(A) } >= 2.
