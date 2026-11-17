% The block editor's "not" box: no nitrogen atom at all.
concept(M) :- has_atom(M,A), o(A), #count{ B : has_atom(M,B), n(B) } = 0.
