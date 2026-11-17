% PREDICATE_NAME: aux_on_carbon
% DESCRIPTION: the atom is bonded to a carbon
aux_on_carbon(X) :- has_bond_to(X,C), c(C).
