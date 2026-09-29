# Protocol v0.3 — pain relief decides the pain level (final draft)

research-pm, 2026-09-26. The YAML in this folder is **final** for the switch.
The live file (`llm/protocol/triage_protocol.yaml`, v0.2) is untouched;
llm-dev switches it. Still `DRAFT-UNREVIEWED`: every level below is
provisional until a dentist signs it off (Form C, C2 and C12).

## 1. Decisions encoded

All in `docs/decisions.md`, 2026-09-26.
- **Decision 3 (user):** lingering, night or spontaneous pain with effective
  pain relief follows SDCEP (SOON). Supersedes USER-2026-09-22-5.
- **Decision 4a (user):** pain relief **not tried** → SOON, per SDCEP.
- **Decision 4b (user delegated; lead ruled; provisional):** pain with pain
  relief **unanswered or unclear** (Q10 null) → URGENT. New criterion **U10**.
- **Research-pm, under 4a:** **U5 and U6 are retired.** Their ids are not
  reused.

## 2. What SDCEP says, and how v0.3 encodes it

Source: SDCEP *Management of Acute Dental Problems*, 2nd ed. (March 2026).
- **Pain pathway flowchart**, re-read on 2026-09-26 from the image on the
  site (`/media/mzabsxwu/pain-flowchart.png`; the page text itself carries no
  pathway):
  - "Has analgesic been taken?" No → "Advise optimal analgesia. Avoid
    stimuli." → Non-urgent Care: Dental.
  - Yes → "Has analgesic controlled the pain?" Yes → Non-urgent Care: Dental.
  - No → Urgent Care: Dental.
  - The flowchart has **no node** for lingering, night or spontaneous pain,
    and **no branch for an unknown answer**.
- **Pulpitis page:** it could not be re-opened on 2026-09-26 (404). The
  reading that lingering, night and spontaneous pain are pulpitis symptoms
  and not level criteria rests on the 2026-09-22 notes
  (`docs/plans/phase1-2-plan.md` §1, §2.2, D6). The flowchart is consistent
  with that reading.

**Unknown relief (U10).** SDCEP does not cover it. Both of its Non-urgent
exits need a *known* answer: relief not taken, or relief that controlled the
pain. So SDCEP gives no warrant for a 7-day answer when relief is unknown.
URGENT is the project's conservative reading, backed by hard rule 7 (a
blank is never reassuring). It is not SDCEP wording, and the YAML source line
says so.

### Levels for a patient with tooth pain, by the pain relief answer (Q10)

Assuming no other criterion holds (no red flag, no biting pain, no severe
pain, no photo finding, and so on).

| Pain relief answer | v0.2 (live), no lingering/night pain | v0.2 (live), with lingering, night or spontaneous pain | **v0.3** (any of these) | Criterion (v0.3) | SDCEP pain pathway |
|---|---|---|---|---|---|
| helped | SOON | URGENT (U5/U6) | **SOON** | S1 | Non-urgent |
| not helped | URGENT | URGENT | **URGENT** | U1 | Urgent |
| not tried | SOON | URGENT (U5/U6) | **SOON** | S1 | Non-urgent |
| unanswered or unclear (null) | SOON | SOON | **URGENT** | U10 | not covered |

Lingering, night and spontaneous pain no longer change the level at all.
Q13 and Q14 are still asked; their answers go to the explanation and the
dentist review.

### Criteria changes

| | v0.2 (live) | v0.3 |
|---|---|---|
| U5 | `pain_lingers_over_30s == true` → URGENT | **retired** (comment in the YAML) |
| U6 | `pain_wakes_at_night == true OR pain_triggers contains spontaneous` → URGENT | **retired** |
| U10 | — | `pain_present == true AND pain_relief_effect is null` → URGENT. "Tooth pain, and it is not known whether pain relief has helped". Source: USER-2026-09-26 + SDCEP-2026 pain pathway + hard rule 7 |
| Grammar | 5 operators | + `field is null` (the only test true on an unanswered field; not allowed on floor criteria). llm-dev's `src/protocol.py` |

**Why U5/U6 are retired rather than kept:**
- Under 4a, "not tried" leaves them, so they would read
  `... AND pain_relief_effect == not_helped`. Q10 is asked only when
  `pain_present == true`, so every such case already meets U1. They could
  never change a level. On the 100 dev keys and 20 sanity cases, no key has
  a pain relief answer without `pain_present == true` (checked 2026-09-26).
- SDCEP's pathway has no lingering or night node. A criterion listing these
  symptoms tells the triage model they are an URGENT reason. That is the v0.2
  behaviour the user has reversed.
- Keeping them would give the explanation nothing that U1 does not: the
  symptom answers are still in the symptoms JSON.
- A dentist can reinstate them (Form C, C2).

**U10 side effect:** a red flag stops the interview before Q10, so relief is
null and U10 holds alongside the EMERGENCY criterion. The level is unchanged
(EMERGENCY dominates), but these keys' `criteria_met` gain U10 on rebuild
(20 dev keys, listed in §4).

## 3. Everything that mentions U5/U6 or the relief answer (checked 2026-09-26)

| Place | Change needed | Owner |
|---|---|---|
| `llm/protocol/triage_protocol.yaml` | replace with this YAML | llm-dev |
| `src/protocol.py` | `is null` in the grammar, protocol_check and the `holds_when` rendering (already in progress) | llm-dev |
| Question wording Q10, Q13, Q14 | none. The same fields are asked. Q10 is a chat question with one re-ask, so "unclear" means null after the re-ask | — |
| `llm/prompts/system_triage.md` | confirm there is no U5/U6 example, and that `holds_when` renders `is null` readably ("not answered") | llm-dev |
| `llm/prompts/system_explain.md`, `src/explain.py` | none found. Urgency wording comes from the level headline. Confirm that the U10 statement reads well in an explanation | llm-dev |
| `llm/knowledge/06_tricky_questions.md` | none. "If pain lingers, wakes you at night … that needs to be seen" gives no time frame (still DRAFT-UNREVIEWED) | — |
| `llm/interface.md` | none: the fields are the same. The criterion ids are protocol content | — |
| `llm/rules.py` R3 | **none**. rules.py is the frozen shadow baseline. From v0.3 it is more urgent than the protocol on lingering/night pain with relief helped or not tried. On unanswered relief with mild pain it is less urgent. Say so wherever rules is compared | — |
| `llm/eval/triage_sanity_cases.json` | S007 URGENT → SOON (cites U5 → S1 only). No sanity case has pain with null relief | qa-engineer |
| `tests/test_triage.py`, `tests/fixtures.py` | none: they use their own fixture U5 (narrative), not the live YAML | — |
| Form C, C2 and new C12 | updated 2026-09-26 | research-pm |
| Form A | regenerate from the live file after the switch (`make_form_a.py`) | research-pm |
| Dev keys | rebuild after the switch (§4) | research-pm |

## 4. Effect on evaluations

### Dev keys (`llm/eval/triage_vignettes_dev.json`, 100): v0.2 → v0.3

Computed 2026-09-26 by evaluating both YAMLs on the key symptoms. Every key
matches its v0.2 level (0/100 mismatches). **Not rebuilt yet**: that waits
for llm-dev's switch.

**9/100 change level:**

| Id | v0.2 | v0.3 | Criterion responsible | Relief |
|---|---|---|---|---|
| V021 | URGENT | SOON | U5 retired (lingering) | helped |
| V048 | URGENT | SOON | U5 retired (lingering) | helped |
| V072 | URGENT | SOON | U5 retired (lingering) | helped |
| V077 | URGENT | SOON | U6 retired (night/spontaneous) | helped |
| V081 | URGENT | SOON | U6 retired (night/spontaneous) | helped |
| V087 | URGENT | SOON | U6 retired (night/spontaneous) | helped |
| V005 | SOON | URGENT | U10 new | null |
| V017 | SOON | URGENT | U10 new | null |
| V031 | SOON | URGENT | U10 new | null |

That is 6 down (URGENT → SOON) and 3 up (SOON → URGENT).

**20/100 change `criteria_met` only** (EMERGENCY stays; U10 is added
because the red-flag stop leaves Q10 null): V004, V014, V019, V022, V028,
V030, V035, V037, V040, V047, V052, V053, V054, V055, V069, V075, V076, V084,
V095, V096.

**Point for the lead: the three U10 keys.** V005, V017 and V031 are the
`s_pain_missing_answers` stratum: mild sweet sensitivity with relief left
null in the key.
- This is the cost of 4b. A mild twinge with a vague relief answer now
  gets "within 24 hours".
- The P7 texts of **V005 and V031 say "I don't know what to take for it"**.
  A reader, or the extractor, could take that as *not tried* (→ SOON) rather
  than unanswered (→ URGENT). Under v0.2 both readings gave SOON, so it did
  not matter. Under v0.3 the choice decides the level.
- V017 ("took some painkillers but I'm not really sure if it made a
  difference") is unclear, and U10 fits it.
- Before the rebuild, the lead should choose one of two options:
  1. Keep the keys null and accept that an extraction of not_tried scores
     as under-triage.
  2. Adjudicate V005/V031 now. They are dev keys, so this is allowed.
     research-pm can do it.
  I recommend adjudicating. The ruling also fixes the extraction rule for
  the pattern "don't know what to take", which matters more now than before.

**Coverage after the switch.** Relief not tried then reaches SOON on dev
(V002 and the rest of the `s_pain_not_tried` stratum), and U10 is covered
by the 3 keys above. The planned 6 extra keys (4 not tried → SOON, 2
unanswered → URGENT, separate seed, the existing 100 byte-identical) test
the lingering and night variants of both. Their key levels are fixed by the
table in §2.

### Held-out: not rescored

Held-out Test 5 is spent on v0.2 and stays reported as v0.2. The keys stay
frozen, and the held-out builder is pinned to v0.2. Under the final v0.3,
the level would differ on:
- **18/200 triage keys**: 12 URGENT → SOON (U5/U6 retired, all with relief
  that helped) and 6 SOON → URGENT (U10).
- **6/60 end-to-end keys**: 4 URGENT → SOON and 2 SOON → URGENT.

These are counts only, computed 2026-09-26 without re-keying or re-scoring.
They supersede the earlier "12/200 and 4/60", which predate 4b. This is a
documented limitation, not a result. The v0.2 run's SOON answers on the
lingering cases must not be reported as v0.3 agreements (post hoc on a spent
set).

Test 1 (`rules.py`) is unaffected.
