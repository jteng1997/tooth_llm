# Held-back probes (extraction and guards)

llm-dev must not read, quote or tune against these; only qa runs them and
reports category-level misses. Each set is run on a configuration change it
tests, once, with the configuration hashes recorded.

- `severity_phrases_c.json`: pain_severity extraction (U2), same shape as
  `llm/eval/severity_phrases_b.json`. Written by research-pm 2026-09-29
  before any run; expected values from the user's rulings only (definition
  and SP01-SP09, 2026-09-26). 36 severe (7 `tuned`: they use a ruled word
  that the extraction instruction quotes), 28 not severe (8 `tuned`), and
  8 `unclear` (`"severe": null`), which the rulings do not settle. Score
  only the 64 settled ones; report the unclear ones apart, for the user.
  2026-09-30: the user ruled on the 8 (HU01-HU08) after seeing both
  configurations' readings; they are now keyed (42 severe, 30 not severe)
  and marked `post_hoc_ruling`. Report them apart: they are not an
  independent test (`docs/decisions.md`, 2026-09-30).
- `relief_guard_heldback.json`: `explain.claims_relief_result` (hard rule 7,
  U10). Written 2026-09-29 before its first run; 20 claims (6 "not tried"
  forms) and 20 advice, hedge and question sentences. First result, on
  explain.py 4465926a: 9/20 claims caught, 0/20 false positives.
