% "Not exactly one oxygen" (a negated count with two bounds): none, or two or more.
concept(M) :- has_atom(M,A), c(A), not 1 <= #count{ X : has_atom(M,X), o(X) } <= 1.
