# Checkpoint — 2026-09-26, wave 2 paused before protocol v0.3

Written before a `/clear`. Read this first, then the 2026-09-26 entries in
`docs/decisions.md`, `docs/reports/test5-heldout-2026-09-26.md` and
`CLAUDE.md`. Supersedes `checkpoint-2026-09-24.md` (still valid for older
background).

## Where the work lives

- **Branch `llm-triage-wave2`**, pushed to `origin`, HEAD `e6df801` plus this
  checkpoint's commit. Worktree:
  `D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2`. It has
  junctions for `.venv weights vendor dataset runs` into the main checkout.
- **Held-out data is gitignored**, in the worktree's `labels/heldout/`. That
  holds the v0.2 keys, P7 texts, adjudication and census data, and the Test 5
  results. Full backup, byte-identical on 2026-09-26 (152 files):
  `D:\jonathan\tooth-llm\labels\heldout\wave2_backup_2026-09-26\`. The older
  `wave2_backup_2026-09-24\` predates P7 and Test 5.
- `runs/evals/` holds eval outputs and `test5_runlog.jsonl`. `runs/p7/` holds
  the dev P7 outputs.
- `GEMINI_API_KEY` is in `.env` (gitignored). Never print it.

## Done in this stretch (2026-09-25/26)

- **P7 synthetic patient text**, written back into the dev and held-out keys.
  - Dev residual: 0/195.
  - Held-out residual: 6/420 (triage) and 1/125 (e2e).
  - Census of not-reached texts: 0/151 after 8 hand edits.
- **Fallback fix `llm_raised`** (commit 06d3792). A proposal whose level is
  below its own verified citations is raised in code, not sent to fallback
  (spec §9.9).
- **Held-out Test 5, scored once per configuration.** It is spent: never
  re-run it. Results on protocol v0.2:
  - `final`: 0/200 under-triage (CI 0–1.8%), κ 1.000, **PASS**. End-to-end
    drop and prepend: 0/60 each.
  - `llm_proposed`: 30/155, the same as the rules baseline on the same cases
    (26/155, McNemar p = 0.689).
  - Fallback to rules: 0/233. Under the rule as first registered it would be
    39/233 = 16.7% (FINDING).
  - §9.5 sensitivity without the H001 keys: final 0/194.
  - Report: `docs/reports/test5-heldout-2026-09-26.md`, with 4 entries in
    `decisions.md`.
- **Dev Test 2** on the current prompts, triage-2.0 mode:
  - 0/8 hand-written cases and 0/60 synthetic on hallucination, omission,
    contradiction, misstated and unreported;
  - unscoped absence 1/14 (minor);
  - fallback text 1/60.
  - Logs: `runs/evals/test2_dev*_2026-09-26.*`.
- Checker fixes (a8af8a5) and the P7 paraphrase fill (3d358c7). Suite
  **474/474**, check_rules 20/20.

## User decisions, 2026-09-26

1. **Paper framing** (logged). Urgency is guaranteed by code: the red-flag
   floor, the raise-only citation check and protocol_check. The LLM
   interviews and explains.
2. **Partial RETAKE: option 1**, keep current behaviour (logged). No code
   change.
3. **U5/U6** (lingering, night and spontaneous pain) follow SDCEP (logged).
   Draft: `docs/plans/protocol-v0.3/`.
4. **Not yet logged**, given to the team just before every teammate hit the
   weekly limit:
   - (a) **Relief not tried → SOON**, per SDCEP. not_tried comes out of
     U5/U6, which leaves them subsumed by U1 (pain + relief not helped →
     URGENT). research-pm decides whether to keep or retire them.
   - (b) **Q10 unanswered or unclear with pain → URGENT.** The user
     delegated this ("the one closest to SDCEP"), and the lead ruled it:
     SDCEP's non-urgent route needs relief known to work or known not
     tried, and hard rule 7 says a blank is never reassuring. The lead leans
     towards a general criterion, `pain_present AND pain_relief_effect is
     null → URGENT`. research-pm is to confirm it against SDCEP. Provisional;
     add it to Form C.
   - **Severity phrasings**: SP01–SP06 are severe (agony, excruciating,
     worst pain ever, can't take it anymore, killing me, "severe" alone).
     SP07–SP09 are NOT severe (chewing on the other side, sleep position
     only, past disruption only).

## Resume order (teammates reset 2026-09-29 06:00 Taipei)

Nothing had been started when the limits hit. The tree was clean at the
checkpoint. Re-send these briefs:
1. **research-pm**
   - Log decision 4 in `decisions.md`.
   - Finalise `docs/plans/protocol-v0.3/triage_protocol.yaml`. Agree the null
     syntax with llm-dev.
   - List the dev keys affected: the earlier list was V021, V048, V072, V077,
     V081, V087, and (b) may add more.
   - After llm-dev switches the protocol, rebuild the dev keys on v0.3 plus 6
     new ones: 4 with relief not tried (SOON) and 2 with relief unanswered
     (URGENT), from a separate seed so the existing 100 stay byte-identical.
2. **llm-dev**
   - Add a null test to the predicate grammar (`src/protocol.py`),
     protocol_check and the holds_when rendering.
   - Add the severity phrasings to `EXTRACTION_INSTRUCTION`, with no code
     guard.
   - Switch the live protocol to v0.3 once research-pm says the draft is
     final.
   - Check `system_triage.md` and the explanation wording for U5/U6.
3. **qa-engineer**
   - Move `llm/eval/severity_phrases_pending.json` into the ruled set.
   - Update sanity case S007.
   - Verify llm-dev's tests.
   - Run the phrase sets and dev Tests 3, 2 and 5 on the v0.3 dev keys. One
     GPU job at a time.
4. **Lead**: commit the verified work. Held-out stays reported on v0.2 and
   is **not rescored**. Under v0.3, 12/200 triage keys and 4/60 e2e keys
   would change level; that is a documented limitation, not a new result.

## Still open (not blocking)

- The SDCEP pages could not be re-opened on 2026-09-26. The U5/U6 reading
  rests on research-pm's notes from 2026-09-22.
- The caries detector threshold (0.25 vs 0.50), the dentist review of
  `llm/knowledge/` (DRAFT-UNREVIEWED) and the Form C questions all wait for a
  dentist.
- Progress estimate: wave 2 is about 90% done, the whole project about 65%.
