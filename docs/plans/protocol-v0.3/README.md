# Protocol v0.3 draft — lingering, night or spontaneous pain with effective relief

research-pm, 2026-09-26. The draft YAML is in this folder. The live file
(`llm/protocol/triage_protocol.yaml`, v0.2) is untouched; llm-dev switches it
once the lead gives the go. Still `DRAFT-UNREVIEWED`.

## 1. Decision

User, 2026-09-26: lingering or night pain **with effective pain relief**
follows SDCEP. This supersedes item 5 of the 2026-09-22 decisions ("stays
URGENT for now"). It is provisional until a dentist confirms it (Form C, C2).

## 2. What SDCEP says, and how the draft encodes it

Source: SDCEP *Management of Acute Dental Problems*, 2nd ed. (March 2026),
pulpitis page and pain pathway, as read by research-pm on 2026-09-22
(`docs/plans/phase1-2-plan.md` §1, §2.2 and discrepancy D6). I could not
re-open the site's pages today (fetch returns navigation only), so the
confirmation rests on that recorded reading:
- pulpitis is **Non-urgent (7 days) unless analgesia fails**; failing pain
  relief is the discriminator (pain pathway: "Has analgesic controlled the
  pain?" No → Urgent Care: Dental);
- lingering, night and spontaneous pain are symptoms of pulpitis, **not
  level criteria** in themselves;
- so **night and spontaneous pain are treated the same way as lingering
  pain**. The user's decision names "lingering or night pain", and U6
  (night or spontaneous) moves together with U5.

**Level with effective relief: SOON** ("See a dentist within 7 days"). S1
(any tooth pain) already gives that, so nothing new is added at SOON.

| | v0.2 (live) | v0.3 draft |
|---|---|---|
| U5 predicate | `pain_lingers_over_30s == true` | `pain_lingers_over_30s == true AND (pain_relief_effect == not_tried OR pain_relief_effect == not_helped)` |
| U5 statement | Pain that keeps aching after the hot, cold or sweet trigger has gone | … has gone, and pain relief has not been tried or has not helped |
| U6 predicate | `pain_wakes_at_night == true OR pain_triggers contains spontaneous` | `(…same…) AND (pain_relief_effect == not_tried OR pain_relief_effect == not_helped)` |
| U6 statement | Pain that starts on its own or wakes you at night | … and pain relief has not been tried or has not helped |
| Sources | USER-2026-09-22-5 | USER-2026-09-26, SDCEP-2026 Pulpitis + Pain pathway |

Resulting levels for a patient with lingering, night or spontaneous pain:

| Pain relief answer | v0.2 | v0.3 draft | SDCEP |
|---|---|---|---|
| helped | URGENT | **SOON** | Non-urgent |
| not helped | URGENT | URGENT (U1, and U5/U6) | Urgent |
| not tried | URGENT | **URGENT** | Non-urgent |
| unanswered (null) | URGENT | **SOON** | — |

**Two points for the user, not decided here:**
1. **"Not tried" stays URGENT** in the draft, because the decision covers
   only *effective* relief. SDCEP's pain pathway gives Non-urgent when
   analgesia has not yet been taken. If the user meant "follow SDCEP" in
   full, drop the relief condition and remove U5/U6 as level criteria. For
   the current keys the effect is the same (all affected keys have relief
   that helped).
2. **Unanswered relief now gives SOON.** The predicate grammar treats an
   unanswered field as never evidence, so it cannot express "not helped,
   not tried *or unknown*". An unclear relief answer therefore no longer
   triggers U5/U6. That matches SDCEP's default. Keeping it URGENT would need
   a grammar change (llm-dev) and a user call.

## 3. Everything else that mentions U5/U6 (checked 2026-09-26)

| Place | Change needed | Owner |
|---|---|---|
| `llm/protocol/triage_protocol.yaml` | replace with this draft | llm-dev |
| Question wording Q10, Q13, Q14 | none: the same fields are asked, and Q10 (relief) already comes first | — |
| `llm/prompts/system_triage.md` | none: it shows predicates from the YAML (`holds_when`) and has no U5/U6 example | llm-dev to confirm |
| `llm/prompts/system_explain.md`, `src/explain.py` | none found; urgency wording comes from the level headline | llm-dev to confirm |
| `llm/knowledge/06_tricky_questions.md` | none: "If pain lingers, wakes you at night … that needs to be seen" gives no time frame (still DRAFT-UNREVIEWED) | — |
| `llm/interface.md` | none (same fields) | — |
| `llm/rules.py` R3 | **none**: rules.py is the frozen shadow baseline. From v0.3 it is more urgent than the protocol on these cases; say so wherever rules is compared | — |
| `llm/eval/triage_sanity_cases.json` | 1 case changes URGENT → SOON (S007) | qa-engineer |
| Form C, C2 | updated today (the provisional decision recorded; the question to the dentist stays open) | research-pm |
| Form A | regenerate from the live file after the switch (`make_form_a.py`) | research-pm |
| Dev keys | rebuild (§4) | research-pm |

## 4. Effect on evaluations

- **Held-out Test 5 is spent on v0.2 and stays reported as v0.2.** Under v0.3,
  **12/200 triage keys** (6 lingering, 6 night or spontaneous; all with relief
  that helped) and **4/60 end-to-end keys** would change URGENT → SOON. They
  are **not re-keyed or re-scored**. Held-out keys stay frozen as v0.2
  artefacts, and the held-out builder is pinned to v0.2.
  Note: on the v0.2 run, `llm_proposed` said SOON on all 6 lingering cases
  (scored as under-triage). Those would be agreements under v0.3. That must
  **not** be reported as a v0.3 result: it is post hoc on a spent set.
- **v0.3 numbers come from dev only.** Dev keys rebuilt from v0.3: **6/100
  change URGENT → SOON**, namely V021, V048, V072, V077, V081, V087 (3
  lingering, 3 night or spontaneous, all with relief that helped). Their P7
  text does not change, only the key level.
- **Coverage gap after the change:** no dev key would then exercise U5 or U6
  (every lingering or night key has relief that helped). Proposal: append 4
  dev keys with relief "not tried" (2 lingering, 2 night or spontaneous; key
  URGENT), built from a separate seed so the existing 100 keys and their
  texts stay byte-identical. They need P7 text (a small job). Also 2 with
  relief unanswered (key SOON), to pin down point 2 above.
- Test 1 (`rules.py`) is unaffected.
