% two to four nitrogens
concept(M) :- has_atom(M,_), 2 <= #count{ A : has_atom(M,A), n(A) } <= 4.
