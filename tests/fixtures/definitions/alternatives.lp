% Either a sulfur, or a charged nitrogen.
concept(M) :- has_atom(M,A), s(A).
concept(M) :- has_atom(M,A), n(A), aux_charged(A).

% PREDICATE_NAME: aux_charged
% DESCRIPTION: the atom carries a formal charge
aux_charged(A) :- charge_p(A).
aux_charged(A) :- charge_n(A).
