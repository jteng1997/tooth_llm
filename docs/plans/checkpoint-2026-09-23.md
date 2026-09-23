# Checkpoint — 2026-09-23, end of llm-triage wave 1

Written before a `/clear` so a fresh session (and a fresh team) can resume
without re-deriving context. Read this, `docs/decisions.md` and
`CLAUDE.md` first; they are kept current and this file will go stale.

## What this checkpoint is

Everything below was committed in one commit on branch `llm-triage` right
after this file was written. `git log -1` on that commit is the exact state.
Tests at commit time: **202/202** (`python -m unittest discover -s tests`),
**check_rules.py 20/20**. Server was left running at `http://localhost:8000`
(PID may have died with the session — check before relying on it).

## Architecture as it stands (supersedes the old rules.py-decides design)

```
photos -> src/pipeline.py                          -> findings JSON
user  <-> src/interview.py (checklists + chat)      -> symptoms JSON (1.1)
findings + symptoms + transcript -> src/triage.py   -> assessment JSON (2.0)
   - red_flag_floor() in rules.py fires first, no model call, forces EMERGENCY
   - otherwise the LLM proposes a level, citing protocol criteria as evidence
   - every citation is evidence-checked (quote really in transcript, field
     really has that value); 2 invalid attempts -> falls back to rules.py
   - the protocol's own structured criteria can only RAISE the model's level
     (never lower it) — "code guards the floor, model proposes, code can
     only raise"
   - src/protocol.py loads+validates llm/protocol/triage_protocol.yaml
     (DRAFT-UNREVIEWED, 21 criteria, 19 questions, all patient-facing text)
findings + symptoms + assessment + knowledge -> src/explain.py -> text
   - a red flag raised mid follow-up (keyword scan, then evidence-check on a
     hit only) recomputes the assessment and can escalate to EMERGENCY
```

## The interview is now checklist + chat, not free chat

- **Checklist A** (10 rows, always first): the 8 red flags, "any pain",
  "mouth ulcer/sore/lump > 3 weeks" (persistent_ulcer). Any red-flag Yes ->
  stop at once, EMERGENCY, no model call. No pain -> done.
- **Checklist B** (4 rows, only if pain): lingering pain (>30s, with a
  "Not sure" option), night pain, pain on biting, recent extraction.
- **Chat** (5 questions): pain_relief_effect, pain_severity, pain_triggers,
  location, duration_days. Only these are LLM-extracted, and every extracted
  value needs a verified quote from the patient's own words.
- Every checklist row is an explicit Yes/No (or Yes/No/Not sure), no default;
  the server rejects an incomplete submission (400) and refuses a result
  before checklist A is answered (409).

## Web app (src/webapp.py + webapp_index.html)

Endpoints: `/api/analyse`, `/api/checklist` (new), `/api/answer`,
`/api/result`, `/api/ask`, `/api/reset`. Full live end-to-end run (real GPU,
real Ollama, tests/sample_images) passed: URGENT result, correct wording,
5 flagged teeth, zero 500s. 41/41 offline test, 21/21 browser (headless
Edge) test, both in `tests/`.

## What's DONE (verified by the lead, not just claimed)

- T2–T9 from the original task list (interface.md 2.0/1.1, red-flag floor,
  protocol loader, triage.py, interview checklists, explain.py guardrails,
  webapp wiring) — all done and tested.
- §1.6 (follow-up red-flag escalation) — done: keyword pre-screen, evidence
  check only on a hit, zero extra cost on ordinary follow-ups.
- Guardrail: garbled/mangled drug names caught by prescription-*shape*
  regex, not just a word list (0 false positives on 60 stored explanations).
- Dataset filter (`src/filter_dental_qa.py`): topic recall improved with
  oral/soft-tissue terms (+2,388 rows), 3 over-removal causes fixed. Caveat:
  those +2,388 rows are only ~20% actually dental per the LLM topic
  classifier trial (20/20 agreement with hand labels) — **the 2.5h
  oral_soft_tissue classifier cleanup run was approved but not yet executed
  or was mid-run when the session paused; check `dataset/dental_qa/` for
  whether it finished.**
- Silver-label secondary check (ChatDoctor doctor-answer urgency): **closed,
  negative result.** κ 0.406 tuned / 0.269 blind (bar 0.60), EMERGENCY
  precision 16.7–20% (bar 90%). Documented, not used for anything downstream.
  Do not resurrect without a genuinely new idea.
- Test 5 (held-out) analysis spec pre-registered (`docs/plans/
  test5-analysis-spec.md`) and dry-run validated against rules.py alone:
  rules.py 51/200 under-triage (25.5%, κ 0.595), protocol-check-only 8/200
  (4.0%, κ 0.967, all 8 misses are narrative-only cases by construction).
  **Caveat that must travel with these numbers**: rules.py is scored against
  a key built from criteria written after it, so this is not a fair fight;
  and 96% is code agreeing with a key written from the same protocol, not
  clinical correctness.
- P10: 200 real patient messages hand-labelled for red-flag presence (46
  positive). Found 3 SDCEP-covered near-misses we don't ask about (can't
  open mouth/trismus, double vision + jaw numbness, hoarse/changed voice) —
  logged in `docs/decisions.md` Open section, **needs a dentist**.
- Dentist review packet ready in `docs/dentist-review/` (4 forms). Nothing
  sent yet — **no dentist has been found**. Form B needs P7 (vignette text)
  before it can print real cases.
- P7 method spec written (`docs/plans/p7-vignette-text-spec.md`) but
  **generation itself had not started** as of this checkpoint.

## Known open bugs / unfinished, in priority order

1. **Test 3 (symptom extraction) on the real checklist flow: 90.0% field
   accuracy (54/60)**, down from the old (now-meaningless) 97.1% that scored
   fields no longer extracted. 4 faults reported to llm-dev, not yet fixed:
   - `location` invents a side from partial evidence (2 cases) — the
     clearer bug, llm-dev called it a contract rule that belongs in code
     ("location needs arch and side together"), not just the prompt.
   - re-ask-then-null path fails on its last step (D12).
   - a trigger the patient never named gets added alongside a real one
     (D13) — checklist fields were NOT overwritten, which is good.
   - "Hot tea makes it worse" mis-scored as `["unknown"]` (D04) — arguable,
     lower priority.
2. **check_triage.py has not yet been aligned with the pre-registered Test 5
   spec** (bootstrap seed 20260923, boundary split, McNemar underpowered
   handling, run log). qa-engineer flagged this as needed before any real
   held-out run, and wanted to do it before P7. Not started.
3. **P7 vignette generation** (heavy, GPU, needs a second model family for
   blind extraction) — spec ready, execution not started.
4. **Dataset topic-precision cleanup**, 2.5h GPU run on the 2,388
   oral_soft_tissue rows — approved, status at pause unknown, check
   `dataset/dental_qa/` timestamps.
5. Minor: `test_webapp_offline.py`'s sys.exit-masks-discovery bug — **fixed**
   already (verify: `python -m unittest discover -s tests` should say
   `Ran 202 tests ... OK` with no separate error).

## Pending user decisions — NONE outstanding

Every open item that reached the "needs the user" bar was resolved before
this checkpoint (ulcer question, silver labels, finding wording, Q13
checklist, all logged in `docs/decisions.md` 2026-09-22/23 entries). The
next thing that will need the user is a dentist for the review packet, or
if qa-engineer's Test 5 alignment surfaces a scoring-rule question.

## Team state at pause

All 4 teammates (research-pm, llm-dev, app-dev, qa-engineer) were **idle**,
not mid-task, when paused — session limits had been hit and reset (8pm
Taipei) had not yet been reached for the last cycle before the user asked to
stop. Nothing was mid-write. A fresh session should re-spawn the team fresh
(same 4 roles, `.claude/agents/`) rather than try to resume the old
teammate IDs, and brief each from this file + `docs/decisions.md` rather
than re-deriving priorities.

## Immediate next steps for whoever resumes

1. Re-run `python -m unittest discover -s tests` and `check_rules.py` to
   confirm nothing bit-rotted.
2. Check whether the 2.5h topic-classifier run and the P7 generation ever
   started/finished (see §4 above).
3. Fix the 4 Test 3 faults (llm-dev), starting with `location`.
4. Align `check_triage.py` with the Test 5 spec (qa-engineer), then run the
   real held-out Test 5 (still needs the GPU scheduled — one job at a time).
5. Keep looking for a dentist; the packet is ready the moment one exists.
