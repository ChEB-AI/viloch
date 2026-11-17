concept(M) :- has_atom(M,A), not #count{ X : has_atom(M,X), n(X) } = 0.
