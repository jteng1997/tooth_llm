# Checkpoint — 2026-09-29, protocol v0.3 switched, not yet verified

## Update 2026-09-29 (evening) — read this section first

Committed as a second WIP commit on `llm-triage-wave2`. Suite: **552 run, OK**.
Test 1: **20/20**. The GPU evaluations of v0.3 are only partly done (below).

Done and verified by qa (resume steps 1–3):
- The 8 failing tests are fixed. Held-out paths are explicitly pinned to
  `docs/plans/protocol-v0.2/triage_protocol.yaml` (`load_protocol_for(split)`
  in `check_triage.py`). The held-out fingerprints are unchanged.
- `src/protocol.py`: unquoted null in any case is a parse error. Literals are
  type-checked. `contains` needs a list field. `render_predicate` is
  quote-aware.
- `llm/interface.md` has the null-evidence line.
- Dev keys rebuilt on v0.3: 106 = the existing 100 plus V101–V106. qa verified
  them byte-identical on re-run, and the diff matches README §4. P7 text for
  V101–V106 exists.
- Form A is regenerated, with a retired-U5/U6 note.
- U10 `source` text reworded. The statement is unchanged (user decision
  2026-09-29).
- `docs/decisions.md` has the 2026-09-29 entries, including the adjudication
  of 8 Gemini cells.

New guards (`src/explain.py`, `system_explain.md` rule 12):
- Every null symptom counts as "not answered".
- Relief-claim post-check: on the fresh held-back probe
  (`llm/eval/heldback/` — **llm-dev must never read it**) it catches 9/20
  claims with 0/20 false positives, and 0/568 FP on the knowledge base and
  prompts. Recall is weak. Decide whether to widen it after Test 2 shows
  whether real explanations make such claims.

`src/interview.py` (sha256 157228ca…):
- The EXTRACTION line for the not_tried ruling is in.
- The HEDGE exception is in: the ruled phrase "don't know what to take/use"
  is no longer nulled when the value is not_tried. Before this, the HEDGE
  test at verify() nulled it and so forced U10 URGENT.
- **Not yet added:** the lead-approved synonyms "no idea what to take/use" and
  "not sure what to take/use" (a one-line alternation in `NOT_TRIED_PHRASE`).

Phrase sets, qwen3:14b, on the config BEFORE the HEDGE exception (interview
d57780c5, extraction prompt d3f40b3b, protocol 6f933104). Results are in
`runs/evals/phrases_2026-09-29/`.
- Severity A: 79/86. 6/50 severe phrases were read as moderate (SV05, SV16,
  SV17, SV21, SV24, SV30). SP07 was read as severe.
- Severity B: 27/36. 9/22 severe phrases were read as moderate.
- Relief: 7/8 independent and 1/2 tuned. RP01 and RP03 are null: that is the
  HEDGE bug, now fixed, so re-run.
- **Open for the user:**
  - Under-reading severe → moderate loses U2 URGENT (under-triage).
  - Separately, HEDGE also nulls pain_severity ("I can't describe it, it's
    unbearable"). A proposal is pending from llm-dev.

Remaining, in order (qa runs every GPU job, one at a time; never held-out):
1. Add the two synonyms. Then qa turns llm-dev's HEDGE cases
   (`hedge/cases.py`, 25) into unit tests and re-runs `relief_phrases.json`.
2. `p7_generate.py regenerate --file dev --ids ["V104","V106"]` (both are text
   faults, adjudicated), then extract, writeback, `--write-vignettes` and
   validate.
3. Dev Test 3. Watch V005/V031 (not_tried), V017 (null), and V077 ("no idea
   what caused it" on a spontaneous key).
4. Dev Test 5 on v0.3.
5. Test 2, last.
6. Bring the user the severity evidence and a decision. Then commit the
   verified state and update `CLAUDE.md`.

Teammate names: a bare `llm-dev` or `qa-engineer` resolves to OLD instances
from earlier days. Address the current ones by full name.

---

Written before a `/clear`. Read this first. For background (held-out backup,
Test 5 results, user decisions 1–4), read `checkpoint-2026-09-26.md`, then
the 2026-09-26 entries in `docs/decisions.md`, then
`docs/plans/protocol-v0.3/README.md`.

## Where the work lives

- **Branch `llm-triage-wave2`**, pushed to `origin`. This checkpoint is
  committed together with the v0.3 work-in-progress as a **WIP commit**. It
  holds unverified work and 8 known test failures (below).
- Worktree: `D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2`.
- The held-out data and its backup are unchanged. See the 09-26 checkpoint.
  Held-out Test 5 is **spent on v0.2: never re-run or rescore it.**

## State of protocol v0.3

Decisions (all logged in `docs/decisions.md`, 2026-09-26):
- U5/U6 are retired and their ids are not reused.
- New criterion **U10**, URGENT: `pain_present == true AND pain_relief_effect
  is null`.
- Pain relief decides the pain level:

  | Pain relief | Level | Criterion |
  |---|---|---|
  | helped | SOON | S1 |
  | not tried | SOON | S1 |
  | not helped | URGENT | U1 |
  | unanswered | URGENT | U10 |

- The lead's ruling (provisional, Form C C12):
  - V005/V031 ("I don't know what to take for it") = not tried → SOON.
  - V017 ("not really sure if it made a difference") = unknown → URGENT.
- Severity phrasings: SP01–SP06 count as severe and SP07–SP09 do not.

### Done (by the owners; not yet verified by qa)

- **research-pm**:
  - Decision 4 is logged, including the V005/V031/V017 ruling.
  - The v0.3 draft YAML and README are final (18/200 and 6/60 held-out
    counts).
  - Form C: C2 is rewritten and a new C12 is added ("Twelve" questions).
- **llm-dev**:
  - `src/protocol.py` has the `is null` atom. It is true only on a null or
    missing field. `== null`, `!= null` and `is not null` are parse errors,
    and floor criteria may not use it.
  - The same file has `Criterion.null_fields()`, `holds_when()` and
    `render_predicate()`. The LLM sees "x not answered".
  - `src/triage.py`: check_proposal accepts a null citation only for a
    criterion that tests that field with `is null`. `_code_reasons` lists the
    null fields.
  - `llm/prompts/system_triage.md` has 3 "not answered" lines.
  - `src/interview.py` EXTRACTION_INSTRUCTION has the SP01–SP09 phrase
    rulings.
  - **The live `llm/protocol/triage_protocol.yaml` is switched to v0.3.**
  - New tests: `tests/test_protocol.py` IsNull (13) and `tests/test_triage.py`
    IsNullCriterion (7).
- **qa-engineer, PARTIAL**. It stopped while rewriting the SanityRun class
  and adjusting counts. Edited so far:
  - `llm/eval/severity_phrases.json` (the pending set is merged in and
    `severity_phrases_pending.json` is deleted);
  - `llm/eval/triage_sanity_cases.json`;
  - `llm/eval/triage_vignettes.schema.json`;
  - `src/check_triage.py`;
  - `tests/test_check_triage.py`.

### Not done

- `llm/interface.md` needs one line (owner llm-dev; app-dev already said
  AGREE): "in `assessment.reasons[].evidence`, `value` may be null, only for
  a field the criterion tests with `is null`."
- Dev keys are **not rebuilt** on v0.3. The plan is to keep the existing 100
  byte-identical and add 6 new keys from a separate seed:
  - 4 with relief not tried → SOON;
  - 2 with relief unanswered → URGENT;
  - P7 text for them via Gemini.
- Form A is not regenerated (`make_form_a.py`).
- No Tests 2, 3 or 5 have been run on v0.3 (dev), and the phrase sets have
  not been run. The prompt changes are a new configuration with new prompt
  hashes.

## Measured on 2026-09-29 (at this commit)

- Test 1 `check_rules.py`: **20/20**.
- Suite: `.venv/Scripts/python -m unittest discover -s tests` (pytest is not
  installed). **502 run: 6 failures and 2 errors.**
- All 8 come from tests still pinned to v0.2 behaviour after the live switch.
  No product regression was found.
  - `test_check_triage.Caveats.test_caveat_matches_the_live_protocol`: the
    CAVEATS text says v0.2.
  - `test_check_triage.HeldoutDryRun` (3 tests: keys, mcnemar,
    protocol_check): the v0.2 held-out keys are scored against the live
    v0.3, which gives 12 under-triage and a missing U10. Fix: pin the
    held-out dry-run to the v0.2 protocol. The held-out builder is already
    pinned.
  - `test_check_e2e` (4 tests):
    - `HeldoutMockRun` raises `KeyError: 'U5'`;
    - the fixtures expect SOON where v0.3 now gives URGENT (U10);
    - an attribution test gets `None`.
    - Fix: pin to v0.2 for held-out, or update the dev fixtures to v0.3.

## Held-out under v0.3: counts only, not a result

Held-out would change level on:
- **18/200 triage keys**: 12 URGENT → SOON and 6 SOON → URGENT.
- **6/60 e2e keys**: 4 URGENT → SOON and 2 SOON → URGENT.

These replace the 09-26 counts (12/200 and 4/60). This is a documented
limitation, and Test 5 stays reported on v0.2.

## Resume order

The teammates hit their limits again on 2026-09-29: qa hit the weekly limit,
and research-pm and llm-dev hit the monthly spend limit. Check which are
available before sending briefs.

1. **qa-engineer**:
   - Fix the 8 failing tests: pin the held-out dry-run and e2e mock to v0.2,
     and move the dev fixtures to v0.3.
   - Finish the SanityRun rewrite, S007 (URGENT → SOON) and the severity
     set.
   - Review llm-dev's IsNull and IsNullCriterion tests.
   - Done when the suite has 0 failures.
2. **llm-dev**: add the `interface.md` null-evidence line. Confirm that the
   U10 statement reads well in an explanation.
3. **research-pm**:
   - Rebuild the dev keys on v0.3: the 100 byte-identical except the
     level/criteria changes listed in the v0.3 README §4, plus the 6 new
     keys.
   - V005/V031 are re-keyed not_tried.
   - Regenerate Form A.
4. **qa-engineer**, one GPU job at a time:
   - the phrase sets;
   - dev Test 3, then Test 2, then Test 5 (dev) on v0.3.
5. **Lead**: commit the verified work, then update `CLAUDE.md` and this file.
