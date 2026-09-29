# Held-back guard probes

llm-dev must not read, quote or tune against these; only qa runs them and
reports category-level misses.

- `relief_guard_heldback.json`: `explain.claims_relief_result` (hard rule 7,
  U10). Written 2026-09-29 before its first run; 20 claims (6 "not tried"
  forms) and 20 advice, hedge and question sentences. First result, on
  explain.py 4465926a: 9/20 claims caught, 0/20 false positives.
