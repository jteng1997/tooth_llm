# Test 5 — held-out triage results (draft)

research-pm, 2026-09-26. DRAFT for the lead. Scoring rules:
`docs/plans/test5-analysis-spec.md` (pre-registered 2026-09-23, with the §9
amendments, all dated before scoring). Run log: `docs/decisions.md`,
2026-09-26, "Test 5 held-out scoring 1/4 … 4/4". This file gives aggregates
only. Per-case detail stays in `labels/heldout/results/` (gitignored), and
nothing per-case goes to llm-dev.

**Every number below is agreement with SDCEP as encoded in protocol v0.2,
including the user's 2026-09-22 decisions. It is not a clinical validation.**
The vignettes assume the photo findings are correct. The detector catches
about 29% of carious photos at the current threshold, so end-to-end accuracy
on real patients is not measured here.

---

## 1. Headline

- **What the patient sees (`final`): 0/200 under-triaged** (95% CI 0.0–1.8%,
  one-sided upper bound 1.5%), weighted κ 1.000. On the end-to-end set, 0/60
  (CI 0.0–6.0%). **The pre-registered bar (0 under-triage, κ ≥ 0.8) is met.**
- **This is by construction, not the model's achievement.** Under protocol
  v0.2 every criterion is structured, so code alone (`protocol_check`) also
  scores 200/200. Code raises any lower proposal, so the model cannot move
  `final` below the key (spec §9.7).
- **The model on its own (`llm_proposed`) under-triaged 30/155 = 19.4%**
  (CI 13.5–26.5%), κ 0.781 (CI 0.708–0.853). On the same 155 cases the old
  rules baseline under-triaged 26/155 (16.8%, CI 11.3–23.6%). **The model's
  own level is no better than the rules baseline** (exact McNemar p = 0.689;
  30 cases only the model missed, 26 only rules missed). Every one of the 30
  was caught by code: 26 raised to the model's own cited criteria, 4 by the
  protocol check.
- **The fallback bar is met only because of a rule change made after a dev
  finding.** Fallback to rules is 0/233 (CI 0.0–1.6%). Under the rule as
  first registered it would be **39/233 = 16.7%** (CI 12.2–22.2%). That is a
  **finding against the model**: in 39 of 233 triage calls it stated a level
  below its own verified citations.

## 2. Data and configurations

| Set | n | Levels | Configuration |
|---|---|---|---|
| Triage-level held-out | 200 (84 boundary) | E 45, U 55, S 55, R 45 | rules 43182a2db1550c64; llm c4c54a4057052c60 |
| End-to-end held-out | 60 | 15 per level | drop 4e91288b2d70aa31 (headline); prepend cc8146620d16b601 (secondary) |

qwen3:14b, protocol v0.2, commit 06d3792, each configuration scored once.
Patient text from P7 (llama3.1:8b writer; gemini-3.5-flash-lite blind
reader); see caveats §6.

## 3. Triage-level set (n = 200)

| System | n | Under-triage (95% CI) | Severe | Missed EMERGENCY | Over-triage | Exact | Weighted κ (95% CI) |
|---|---|---|---|---|---|---|---|
| `final` | 200 | 0 (0.0–1.8%) | 0 | 0/45 | 0 | 200/200 | 1.000 (1.000–1.000) |
| `protocol_check` (code only) | 200 | 0 (0.0–1.8%) | 0 | 0/45 | 0 | 200/200 | 1.000 |
| `llm_proposed` | 155 | 30 = 19.4% (13.5–26.5%) | 1 | n/a (0 EMERGENCY scored) | 0 | 125/155 | 0.781 (0.708–0.853) |
| `rules` (old baseline) | 200 | 51 = 25.5% (19.6–32.1%) | 31 | 25/45 | 10 = 5.0% | 139/200 | 0.595 (0.504–0.680) |

`llm_proposed` is scored on 155. The other 45 are EMERGENCY keys where the
red-flag floor ends triage before any model call, so the model gives no
level (§6).

**Head to head (under-triage, exact McNemar, common cases):**
- `final` vs `rules`, n = 200: 0 vs 51; b = 0, c = 51; p = 8.9 × 10⁻¹⁶.
- `llm_proposed` vs `rules`, n = 155: 30 vs 26; b = 30, c = 26; share against
  the model 30/56 (CI 39.7–67.0%); p = 0.689. No difference shown.
- `final` vs `protocol_check`, n = 200: no discordant pairs. Underpowered:
  fewer than 10 discordant pairs, so no test of a difference is reported.

**Where the model's own level falls short (30 cases).** All 30 are one or
two levels low, and none is an over-triage.
- **20: tooth pain that is mild, controlled, or not yet treated, proposed
  ROUTINE** where the protocol gives SOON (S1, "any tooth pain → within 7
  days"). That is 20 of the 28 such cases in which the model was called.
- **6: lingering pain proposed SOON** where the protocol gives URGENT (U5).
  That is all 6 lingering-pain cases. U5 is the user's provisional house rule
  (2026-09-22, item 5). SDCEP would give non-urgent when pain relief works,
  so here the model sides with the guideline over the house rule. It is
  still under-triage against the key, and whether it is clinically right is
  the dentist's call (Form C, C2).
- **3: pain on biting proposed SOON (2) or ROUTINE (1)** where the protocol
  gives URGENT (U3).
- **1: a photo finding plus a missing tooth proposed ROUTINE** where the
  protocol gives SOON (S2, the user's house rule for a symptom-free photo
  finding).

So the model is systematically less urgent than the protocol, most of all
where the protocol deliberately errs towards caution.

**The code ceiling (§3a).** `protocol_check` agrees with the key on 200/200,
so on this set the model has nothing left to add. Its measurable
contribution is its own level (above), the injection cases, and the
rationale text (Test 2, not here).

**Operations** (233 triage calls: 155 first runs + 78 stability runs):

| Measure | Value |
|---|---|
| Valid output | 233/233 (39 kept only after code raised the level) |
| Retried | 93/233 = 39.9% (CI 33.6–46.5%); 139 rejected attempts |
| Fallback to rules (the bar, ≤ 1%) | **0/233** (0.0–1.6%), met |
| `llm_raised` | 38/233 = 16.3% (11.8–21.7%) |
| … plus raised, then raised further by the protocol | +1 |
| Sum, the rule as first registered | **39/233 = 16.7%** (12.2–22.2%) |
| `decided_by`, first runs with a model call | `llm` 125/155 (80.6%, CI 73.5–86.5%); `llm_raised` 26; `protocol_check` 4 |
| Latency per triage call | p50 7.3 s, p95 16.3 s |

**FINDING (§9.9):** 39/233 proposals (16.7%) stated a level below their own
verified citations, above 1%. The model's levels disagree with its own
citations. The fallback rule was changed after the dev rehearsal found the
same pattern (15/75), before any held-out scoring (`decisions.md`,
2026-09-26). So the 0% fallback rests on that change and must not be read as
reliability.

**Stability** (20 pre-chosen cases, §9.3; runs per case: 5 for 19 cases, 3
for 1):

| | All runs identical | Repeats identical | Paraphrases identical |
|---|---|---|---|
| `final` | 20/20 | 20/20 | 19/19 |
| `llm_proposed` | 17/20 (CI 62.1–96.8%) | 20/20 | 16/19 (CI 60.4–96.6%) |

The model is deterministic on the same words. All its instability comes from
rewording. EMERGENCY cases never reach the model and are not described. One
case has no paraphrases (§6).

**Sensitivity, §9.5 (H001 exposure).** Source:
`labels/heldout/results/test5_heldout_llm_qwen3_14b_sensitivity.log`, a
re-report of the same saved runs without the 6 exposed cases (commit
a8af8a5; no model call).

| System | All 200 | Without the 6 exposed keys (194) |
|---|---|---|
| `final` | 0 under, κ 1.000 | 0/194 under (0.0–1.9%), κ 1.000 |
| `llm_proposed` | 30/155 under, κ 0.781 | 30/149 under (14.0–27.5%), κ 0.771 (0.688–0.843) |
| `rules` | 51/200 under, κ 0.595 | 51/194 under (20.2–33.1%), κ 0.578 (0.486–0.668) |
| stability, `llm_proposed` | all identical 17/20 | 16/19 (paraphrases 15/18) |

The 6 exposed keys were agreements for every system, and no conclusion
changes.

## 4. End-to-end set (n = 60)

| Condition | System | n | Under-triage (95% CI) | Severe | Over | Exact | κ (95% CI) |
|---|---|---|---|---|---|---|---|
| **drop** (headline) | `final` | 60 | 0 (0.0–6.0%) | 0 | 0 | 60/60 | 1.000 |
| | `llm_proposed` | 45 | 11 = 24.4% (12.9–39.5%) | 1 | 0 | 34/45 | 0.719 (0.548–0.857) |
| | `rules` | 60 | 16 | 9 (8/15 missed EMERGENCY) | 3 | 41/60 | 0.592 (0.431–0.747) |
| prepend (secondary) | `final` | 60 | 0 (0.0–6.0%) | 0 | 0 | 60/60 | 1.000 |
| | `llm_proposed` | 45 | 7 = 15.6% (6.5–29.5%) | 0 | 0 | 38/45 | 0.829 (0.690–0.929) |

- `final` vs `rules` (both conditions): b = 0, c = 16, p = 3.1 × 10⁻⁵.
- Error attribution (§3): **no `final` miss to attribute** in either
  condition. The `llm_proposed` misses follow the triage-level pattern:
  controlled or mild pain proposed ROUTINE, and lingering pain proposed lower.
  All were raised by code.
- Fallback 0/45 in both conditions. `llm_raised` is 10/45, plus 1 raised
  further (drop), and 7/45 (prepend).
- **Extraction** (25 cases reach the chat, 125 cells): 5/125 cells differ
  from the key under drop (4.0%, CI 1.3–9.1%; severity 4, duration 1), and
  7/125 under prepend (5.6%; severity 3, duration 2, location 1, pain relief
  1). None changed a `final` level.
- **Severity by direction (§9.8), n = 25 cases that reach the chat, both
  conditions:** false severe 0/25 (CI 0–13.7%; 0/22 of mild/moderate keys),
  missed severe 0/25 (0/3 of severe keys, CI 0–70.8%). The severity
  mismatches were all between mild and moderate, and moved no level in
  either direction for `final` or `protocol_check`. Only 3 keys are severe,
  so the missed-severe direction is barely tested.
- **Interview: never asked 0/60 in both conditions** (§3 bucket 1 is
  empty). The interview skips a chat question once an earlier answer has
  already settled its field, by design (`interview.py`). `check_e2e` reports
  these separately as **skipped, already settled**:
  - **drop: 3/60 cases.** 3 skips, and the settled value matched the key in
    2/3. The other was severity mild → moderate.
  - **prepend: 20/60 cases, 28 skips.** The opening message often settles
    severity, triggers or duration before they are asked. The settled value
    matched the key in 24/28. The 4 that differed moved no level: 2 severity
    mild↔moderate, 1 duration off by one day, and 1 location with the wrong
    arch.
  - Cost of the skip: when an earlier answer gets a field wrong, the direct
    question that might have corrected it is never asked.
- **Prepend vs drop.** With the opening, the model's own level is closer to
  the key (7 vs 11 under-triaged), but extraction differs from the key
  slightly more often (7 vs 5 cells). Prepend is not the product (§9.6).

## 5. What the numbers change (spec §5)

- **`final` under-triage is 0**, so there is nothing to attribute and no
  fine-tuning trigger.
- **`final` beats `rules` on under-triage and κ.** But under v0.2 the credit
  belongs to the protocol encoded in code, not to the model. The paper should
  say that the LLM's own triage matched the rules baseline and did not beat
  it, and that safety came from the code floor and the raise-only protocol
  check.
- **The fallback bar is met by `fallback_rules`.** The §9.9 finding stands
  beside it: the model's stated level disagrees with its own citations in 1
  of 6 calls.
- **κ ≥ 0.8** is met by `final`. `llm_proposed` is 0.781 (CI straddles 0.8)
  on triage and 0.719 on e2e drop.

## 6. Caveats that travel with these numbers

1. **SDCEP as encoded, not clinical validation** (above). One key author, no
   dentist.
2. **Findings are assumed correct.** The detector catches ~29% of carious
   photos at 0.50 (above).
3. **Structured criteria are decided by code.** On triage-level cases,
   `final` is right by construction wherever a structured criterion holds, and
   under v0.2 all criteria are structured. The informative parts are
   `llm_proposed`, the injection cases and the end-to-end set. *(The
   held-out logs print an older wording that mentions "the two narrative
   criteria". Those logs predate the fix: commit a8af8a5 corrected the
   printed caveat, and a test now checks it against the live protocol.)*
4. **Patient text (P7).** Screened texts were used, not raw generator
   output.
   - Blind reader, chat fields: residual 6/420 (triage) and 1/125 (e2e).
   - Census of the 151 not-reached texts, which the blind reader never sees:
     36/151 = 23.8% (CI 17.3–31.4%) errors before fixing. After two
     regeneration rounds and **8 marked hand edits by research-pm (the key
     author)** it was 0/151; 8/151 = 5.3% if hand-edited texts count as
     generator failures.
   - **50-case human read (before the census): 11/50 = 22.0% (CI
     11.5–36.0%)**, 9 of them in not-reached texts. The read was not blind.
   - 7 pairs of triage texts are word-for-word identical. Each pair is a
     no-problem, photo-only SOON key and an all-clear ROUTINE key, with the
     same fact and the same style. The level difference comes from the photo
     findings, which are not in the text, so the duplication is expected, but
     it lowers text variety.
5. **The fallback rule changed after a dev finding** (§9.9, before held-out
   scoring). The 0% fallback depends on it; 16.7% under the rule as first
   registered.
6. **`llm_proposed` is not scored on the 45 floor cases** (triage) or the 15
   EMERGENCY cases (e2e). The red-flag floor decides them before any model
   call, so nothing is known about the model's own judgement on red flags.
7. **Stability:** 1 of the 20 cases (an injection case) has no paraphrases,
   so it ran 3 times, not 5, and the paraphrase share is out of 19. The cause
   is a harness gap, not a generation failure: its paraphrases were never
   generated, and the regenerate step does not create paraphrases that are
   missing. qa-engineer is
   fixing this for future sets only; the held-out set stays as run.
8. **Known `verify()` gaps** found on held-out text were deliberately not
   fixed before scoring (`decisions.md`, 2026-09-26). All of them can only
   drop a value, never add one. They may account for some of the e2e
   extraction differences.
9. **Hosted blind reader.** P7's model B ran on the paid Gemini API, so the
   held-out text exists at a third party, and that check may not be exactly
   repeatable.
10. **H001 exposure:** 6 keys; sensitivity as in §3. No change.
11. **Small n.** 60 end-to-end cases give a 0/60 upper bound of 6.0%; 3
    severe keys cannot test missed severe.

## 7. Open items for the lead

- Decide how the paper frames the LLM's role: under v0.2 its own level does
  not beat rules. Its value, if any, is in the explanation, not the level.

Resolved in commit a8af8a5:
- the official §9.5 sensitivity output;
- the never-asked vs skipped-already-settled split in `check_e2e`;
- the cause of the missing paraphrases;
- the stale printed caveat 3, now checked against the live protocol by a
  test.
