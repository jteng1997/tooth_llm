# Checkpoint — 2026-09-24, wave 2 paused

Written before a `/clear`. Read this first, then `docs/decisions.md`,
`docs/architecture.md` and `CLAUDE.md`. Supersedes
`checkpoint-2026-09-23.md`.

## Where the work lives

- **Branch `llm-triage-wave2`**, pushed to `origin`. Worktree:
  `D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2`. It has
  junctions for `.venv weights vendor dataset runs` into the main checkout.
- **Held-out data is gitignored.** The worktree's `labels/heldout/` is a real
  local copy (v0.2-rebuilt keys plus everything added in wave 2). A full
  backup of it is at
  `D:\jonathan\tooth-llm\labels\heldout\wave2_backup_2026-09-24\` (42 files,
  byte-identical at backup time). The main checkout's
  `labels/heldout/*.json` are still the **v0.1** keys. On resume in a new
  worktree, copy the backup in, not the v0.1 files.
- `runs/` (eval outputs, run logs, P7 outputs, the Gemini smoke file) is in
  the main checkout via the junction: `D:\jonathan\tooth-llm\runs\`.
- `GEMINI_API_KEY` is in `D:\jonathan\tooth-llm\.env` and in the worktree
  `.env`, both gitignored. Never print it.
- llm-dev's prepared, **not applied** drafts are in
  `docs/plans/wave2-pending/`, with probe and dry-run scripts in
  `llmdev-scratch/`.

## Test state at pause

- Unit tests: all pass except 1 expected failure, `test_check_e2e`
  HeldoutMockRun. It expects Q20/Q21, which arrive with protocol v0.2.
  check_rules 20/20.
- Test 2 (explanation faithfulness):
  - Legacy path on the 60 synthetic cases: 0/0/0 hallucination, omission,
    contradiction. That run found the missing-tooth-called-decay bug, now
    fixed (#13).
  - New triage-2.0 mode: seed 8 is complete at 0/8 on all four rates.
  - The 60-case triage-2.0 run was **stopped at 5/60**. Its log is renamed
    `.partial-paused`; discard it and restart.
- Test 3 (symptom extraction):
  - Dev: 60/60, but tuned on those dialogues.
  - Blind set A: 88/95 = 92.6% (CI 85.4–97.0), 0 guessed nulls. Now spent:
    it counts as dev after #15.
  - Blind set B: 20 dialogues, **not yet run**. Run it once only.
- Test 5 (triage, held-out): no-model baseline only. rules.py under-triages
  51/200 (25.5%); protocol check 8/200 (4.0%). The LLM is not yet scored.
- P7: Gemini smoke test passed (3/3, schema enforced, key in no file).
  llama3.1:8b is pulled. No text has been generated yet.

## Tasks (wave 2)

| # | Task | Owner | State |
|---|---|---|---|
| 11 | Follow-up echo fix | llm-dev | code done; awaits Test 2 |
| 12 | Protocol v0.2 (Q20 broken filling → S3 SOON, Q21 pus → U8 URGENT) | research-pm / llm-dev | draft + rebuilt keys done; wording **approved by user**; not live |
| 13 | Missing tooth never called decay | llm-dev | code done; awaits Test 2 (misstated 0/60) |
| 14 | Test 2 triage-2.0 mode | qa-engineer | built; 60-case run to redo |
| 15 | verify() fixes (bare No on Q10, idioms, slang arch, "at night") | llm-dev | code done; awaits dev Test 3 + set B |
| 17 | Never deny a tooth cause (all cases) | llm-dev | prepared in `wave2-pending/`, not applied |
| 4 | P7 text generation (llama writes, Gemini checks) | qa-engineer + research-pm | waits for v0.2 |
| 5 | Held-out Test 5 | qa-engineer | waits for P7 |

## Resume order (one GPU job at a time)

1. Re-spawn the team (research-pm, llm-dev, app-dev, qa-engineer), briefed
   from this file.
2. qa-engineer checks the hashes in `runs/evals/test2_v2_hashes.txt`, then
   re-runs `check_faithfulness.py --model qwen3:14b --synthetic 60 --seed 0
   --mode both` from scratch and reports. This closes #11, #13 and #14.
3. qa-engineer runs dev Test 3 (must stay 60/60), then the **single** blind
   run on set B with exact CIs. This closes #15.
4. llm-dev applies v0.2 + #17 in one pass:
   - schema 1.2;
   - copy the protocol draft over `llm/protocol/triage_protocol.yaml`;
   - run `make_form_a.py`;
   - update `interface.md` to 1.2 (app-dev has agreed);
   - update the tests;
   - add prompt rule 13 and `denies_tooth_cause`.
5. qa-engineer re-runs Test 2 and the v0.2 verification
   (`labels/heldout/_scratch/qa_verify_v02.py`). app-dev re-runs the
   offline (40) and browser (21) web tests and checks the 12-row checklist
   at 360 and 320 px.
6. P7: dev first, then held-out and e2e. Model B is gemini-3.5-flash-lite,
   with gemma3:12b as the documented local fallback. research-pm
   adjudicates model-B disagreements and reads 50 cases.
7. Held-out Test 5, scored once per configuration: headline `--opening
   drop`, plus the H001 sensitivity analysis.

## Decisions made in wave 2 (all logged in `docs/decisions.md`)

- **User:**
  - Stay on qwen3:14b.
  - S3/U8 become checklist rows (option 2), with the Q20/Q21 wording
    approved.
  - Pus → URGENT with or without pain (provisional; C11 for the dentist).
  - Explanation sentence A (a hedged tooth link) is allowed.
  - Sentence B changes: the explanation must never deny a tooth cause.
  - P7 model B via the paid Gemini API (a scoped exception, also noted in
    CLAUDE.md).
- **Lead:**
  - Topic cleanup deferred until after Test 5.
  - End-to-end headline scoring uses the app's real behaviour (no free-text
    opening).
  - The denial guardrail applies to all cases.
- **Incident:** held-out case H001 was shown to llm-dev by a stray scratch
  file. It's handled by a pre-declared sensitivity analysis on 194 keys; the
  triage code was unchanged.
- **Rule:** held-out-derived files live only under `labels/heldout/`, and
  no scratch file may be named after a stdlib module.

## Open with the user or a dentist

No user decision is pending. For a dentist: the caries threshold, the
near-miss symptoms (trismus, visual disturbance, voice change), pus without
pain, and U7. The dentist review packet is in `docs/dentist-review/`.
