concept(M) :- has_atom(M,_), #sum{ W : mol_weight(M,W) } > 10.
