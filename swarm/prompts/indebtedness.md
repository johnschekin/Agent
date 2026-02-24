# Indebtedness Family Prompt

Primary target:
- debt_capacity.indebtedness and child concepts under that family subtree

Focus:
- negative covenant sections and linked definitions
- clause-level baskets and exceptions

First loop:
1. run `structural_mapper.py` with current strategy
2. run `pattern_tester.py` on a stratified sample
3. inspect miss summary + outlier summary
4. refine strategy and persist only if precision improves
