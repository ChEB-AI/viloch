% An oxygen connected through a chain of bonds to a nitrogen.
concept(M) :- has_atom(M,A), o(A), aux_reaches_n(A).

% PREDICATE_NAME: aux_reaches_n
% DESCRIPTION: the atom is linked by bonds to a nitrogen
aux_reaches_n(X) :- has_bond_to(X,Y), n(Y).
aux_reaches_n(X) :- has_bond_to(X,Y), aux_reaches_n(Y).
