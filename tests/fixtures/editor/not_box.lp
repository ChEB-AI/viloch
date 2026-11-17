concept(M) :- has_atom(M,A), c(A), #count{ B : has_atom(M,B), n(B) } = 0.
