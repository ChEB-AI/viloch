% "Not two or more oxygens": at most one oxygen atom.
concept(M) :- has_atom(M,A), c(A), not #count{ X : has_atom(M,X), o(X) } >= 2.
