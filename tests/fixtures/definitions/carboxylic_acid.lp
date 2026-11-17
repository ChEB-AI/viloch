% A carboxylic acid: a carbon double-bonded to one oxygen and single-bonded to another.
chebi_33575(M) :- aux_carboxy_group(M).

% PREDICATE_NAME: aux_carboxy_group
% DESCRIPTION: contains a carboxy group, C(=O)O
aux_carboxy_group(M) :- has_atom(M,C), c(C), has_atom(M,O1), o(O1), bDOUBLE(C,O1),
    has_atom(M,O2), o(O2), bSINGLE(C,O2).
