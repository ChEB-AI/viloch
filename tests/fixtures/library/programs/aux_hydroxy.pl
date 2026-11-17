% PREDICATE_NAME: aux_hydroxy
% DESCRIPTION: contains a hydroxy group, an oxygen with one hydrogen
aux_hydroxy(M) :- has_atom(M,O), o(O), has_1_hs(O), aux_on_carbon(O).
