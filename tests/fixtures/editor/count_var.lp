concept(M) :- has_atom(M,_), N = #count{ A : has_atom(M,A), c(A) }, N >= 6, N <= 10.
