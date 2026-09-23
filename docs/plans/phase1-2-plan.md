# Phases 1–2 plan: triage protocol, datasets, evaluation

Status: **PROPOSAL for the user's review. Nothing here is built or decided.**
Author: research-pm, 2026-09-22. Companion to llm-dev's technical design
(`docs/plans/llm-triage-design.md`, "the design"); this file owns the clinical
content, the data plan, the evaluation design and the task order. The protocol
below is **DRAFT-UNREVIEWED**: a dentist must sign it off before any result
from it is reported as clinical (CLAUDE.md rules 4–5).

Everything is a screening aid, not a diagnosis. Levels below are
"how soon to see someone", never "what the patient has".

**Language: English only** (user decision, 2026-09-22, `docs/decisions.md`).
The protocol, question topics, headlines, disclaimer, emergency screen, the
required finding phrase ("Based on the image, there is an indication of…"),
the vignettes and the dentist forms are all written in English. All primary
sources in §1 are English-language guidelines.

---

## 1. Literature review

"Read" = I read the text or flowchart myself on 2026-09-22. "Citation only" =
the reference is confirmed but I did not read the full text.

| # | Source | Status | What it gives us |
|---|---|---|---|
| S1 | SDCEP, *Management of Acute Dental Problems*, **2nd edition, March 2026**. Scottish Dental Clinical Effectiveness Programme (NHS Education for Scotland). Web-only: https://www.acutedentalproblems.sdcep.org.uk/ | **Read**: "Timescales for treatment", pain and swelling flowcharts (images), pulpitis, symptomatic apical periodontitis, acute apical abscess, dentine hypersensitivity, spreading/systemic infection (sepsis) pages. Trauma, bleeding and ulceration flowcharts **read** 2026-09-22 (task P3; the PNGs have transparent backgrounds and were flattened onto white to read them). | The triage levels, time frames and decision questions (§1.1). The primary source for the protocol. |
| S2 | SDCEP, *Management of Acute Dental Problems — Quick Reference Guide*, 1st edition, March 2013. ISBN 978 1 905829 16 3. https://www.sdcep.org.uk/media/ejknwfj0/sdcep-madp-quick-reference-guide.pdf | **Read** in full (all six flowcharts as text). | The 2013 version of the same flowcharts; used for the trauma and bleeding endpoints I could not read in S1. Superseded by S1 where they differ. |
| S3 | NHS England, *Clinical guidance: unscheduled urgent and non-urgent dental care*, version 1.0, published 1 May 2025, updated 3 Oct 2025. https://www.england.nhs.uk/long-read/clinical-guidance-unscheduled-urgent-and-non-urgent-dental-care/ | **Read** §1–5 (via the Internet Archive copy of 13 Jun 2026; the live page blocks scripts). | Adopts SDCEP's categories and adds explicit example lists per level (§1.1); recommends SOCRATES for pain history. Replaces NHSE's Nov 2023 clinical standard. |
| S4 | American Dental Association, *What Constitutes a Dental Emergency?* (COVID-19 guidance), updated 30 Mar 2021. https://www.ada.org/-/media/project/ada-organization/ada/ada-org/files/resources/coronavirus/covid-19-practice-resources/ada_covid19_dental_emergency_dds.pdf | **Read** (one page). | Emergency vs urgent vs non-emergency lists. **No time frames.** Written for rationing care during office closures, not for patient triage; use as corroboration only. |
| S5 | AAE, *AAE Consensus Conference Recommended Diagnostic Terminology*. J Endod 2009;35(12):1634. Background paper: Glickman GN, J Endod 2009;35(12):1619–20, doi:10.1016/j.joen.2009.09.029 (PMID 19932336). AAE one-page PDF: https://www.aae.org/specialty/wp-content/uploads/sites/2/2017/07/aaeconsensusconferencerecommendeddiagnosticterminology.pdf | **Read** the one-page terminology table (Internet Archive copy; aae.org blocks scripts). PMID record confirmed. | Diagnostic categories only — **no urgency levels, no time frames**. "Lingering thermal pain, spontaneous pain, referred pain" describe symptomatic irreversible pulpitis; **no duration in seconds is given.** Symptomatic apical periodontitis = painful response to biting/percussion. Acute apical abscess = rapid onset, spontaneous pain, pus, swelling. |
| S6 | Pitts NB, Ismail AI, Martignon S, et al. *ICCMS™ Guide for Practitioners and Educators* (and Quick Reference Guide). ICDAS Foundation, 2014. https://www.iccms-web.com/uploads/asset/5928404ea4df6343406124.pdf | **Read** the Quick Reference Guide. Year taken from the KCL repository listing, not the PDF. | Lesion staging (initial / moderate / extensive = ICDAS 1–2 / 3–4 / 5–6) and management by stage and risk. **No urgency levels or time frames**; it starts "having ensured that there are no urgent pain related issues". |
| S7 | Fouad AF, Abbott PV, Tsilingaridis G, et al. IADT guidelines for the management of traumatic dental injuries: 2. Avulsion of permanent teeth. Dent Traumatol 2020;36(4):331–342 (PMID 32460393). Part 1 fractures and luxations: Bourguignon C et al., doi:10.1111/edt.12578. | **Abstract read** (Europe PMC); full text not open access, not read. | Clinical management of avulsion and luxation. Only needed for the statement that an avulsed permanent tooth is time-critical, which S1–S3 already state. |
| S8 | SDCEP, *Emergency Dental Care: Dental Clinical Guidance*, November 2007. https://www.sdcep.org.uk/media/wfrjkqax/edc-guidance.pdf | **Read** §2.1 (categories of need). | The origin of S1's timescales. Emergency (clinician contact within 60 min): trauma incl. avulsed permanent tooth, significant and worsening swelling, uncontrollable post-extraction bleeding, "acute systemic illness or raised temperature as a result of dental infection", severe trismus. Urgent (24 h): infection without systemic effect, "severe dental and facial pain … that cannot be controlled by the patient following self-help advice", fractured tooth with pulp exposure. Routine (7 days): mild/moderate pain that responds to pain relief, minor trauma, bleeding gums, lost fillings/crowns. |

**P3 re-read findings (2026-09-22):**
- S1 trauma (2nd ed.): head injury, loss of consciousness, significant facial
  trauma, uncontrollable bleeding or airway → Emergency Medical; degloving or
  large lacerations, teeth no longer meet, suspected inhaled tooth →
  Emergency Care (NHS24/111); knocked-out adult tooth → Emergency Care:
  Dental or NHS24/111 (a dental, not medical, emergency; "hospital emergency
  departments may not be able to provide timely or appropriate dental care");
  pulp exposed, adult tooth moved, or intrusion/safeguarding concerns → Urgent;
  fracture into dentine, primary tooth knocked out → Non-urgent; enamel chip,
  small lacerations → Self Care. Confirms S2; E4's floor over-triages all but
  the first two groups.
- S1 bleeding: after dental treatment, not stopped with pressure →
  Emergency (Dental or NHS24/111); brisk and persistent without recent
  treatment or trauma → Emergency; low-level bleeding, not unwell →
  Non-urgent.
- S1 ulceration: ulcer present > 3 weeks → Urgent dental (possible
  urgent-suspicion-of-cancer referral); severe dehydration → Emergency
  Medical. **Gap:** the interview never asks about ulcers or lumps; a
  long-standing ulcer would get no more than the default level. Out of scope
  for a caries screen, but the app should not imply it covers this (Q14).
- S3 figure 1 (appendix diagram) not opened; the §3 text it summarises was read.

Not used: WHO *Oral Health Surveys: Basic
Methods*, which `rules.py` cites for R8 — it is an epidemiological recording
manual, not a triage source, so it cannot justify an urgency level.

### 1.1 What the sources define

**Levels and time frames (S1 "Timescales for treatment", verbatim in substance; S3 §3.1 identical):**

| SDCEP / NHSE level | Time frame | Examples (S1 flowcharts, S3 §3.2–3.4) |
|---|---|---|
| Emergency Care – **Medical** | Now: emergency department or 999 | Airway compromise; swelling rapidly increasing, likely to obstruct the airway or close the eye; systemically unwell (rigors, increasing temperature, dehydrated, lethargic); sepsis signs; significant facial injury, head injury, loss of consciousness; suspected MI (jaw pain + chest pain/breathlessness); pain-relief overdose; facial pain with visual disturbance (giant cell arteritis); suspected inhaled tooth. |
| Emergency Care – **Dental** | Contact with a dental adviser ideally within **60 minutes**, treatment as severity requires | Avulsed permanent tooth; intra-oral bleeding the patient cannot control. |
| **Urgent** Care | Within **24 hours** or as soon as practicable | Tooth pain not controlled by analgesia; pain on biting (symptomatic apical periodontitis); acute apical abscess without airway compromise; swelling slowly increasing, hot or firm; spreading/recurrent swelling with lymph nodes but no airway risk (S3); fractured tooth involving the pulp; displaced (moved) adult tooth; pain after a recent extraction; bleeding controlled with local measures (S3). |
| **Non-urgent** Care | Within **7 days** if required | Tooth pain controlled by analgesia, or analgesia not yet tried; localised, non-spreading swelling without pain (S1) or without lymph nodes (S3); fracture into dentine; dentine hypersensitivity; lost filling or crown; minor trauma needing review. |
| **Self Care** | No professional needed unless it persists or worsens | Pain from an erupting tooth in a child; minor soft-tissue trauma; post-extraction bleeding that has stopped. **An adult with tooth pain never ends at Self Care in S1's pain pathway** — the minimum is Non-urgent. |

**Decision questions in S1's pain pathway, in order:** signs of MI or
pain-relief overdose → pain due to trauma → swelling → pain in a tooth →
erupting tooth → analgesic taken → analgesic controlled the pain → (not a
tooth) recent extraction → face or mouth / visual disturbance → appliance or
denture → ulcer.

**Swelling pathway:** difficulty breathing; difficulty swallowing; floor of
mouth raised; mouth opening restricted; swelling closing the eye; worsened in
the last hour; sudden and unexplained (angioedema) → rapidly increasing /
airway / eye → Emergency medical; systemically unwell → Emergency medical;
slowly increasing, hot or firm → Urgent; otherwise, if in pain → pain pathway,
if not → Non-urgent.

**What none of the sources give us:** a time frame for a *possible cavity seen
in a photo with no symptoms*. S1–S3 are about acute presentations; S4 lists
"treatment of asymptomatic carious lesions" as non-emergency; S6 manages
caries by stage and risk at recall. The SOON/ROUTINE windows for photo-only
findings are therefore a dentist's call, not a literature fact.

---

## 2. Proposed triage protocol (v0.1, DRAFT-UNREVIEWED)

Format: llm-dev's YAML in the design §3.1 (agreed by message). This section
is the content; llm-dev encodes it. Level names stay as in `rules.py`
(EMERGENCY, URGENT, SOON, ROUTINE), so LLM, rules and dentist labels are
scored on one scale. The time frames change.

**Mapping onto the four levels:** SDCEP Emergency (medical and dental) →
EMERGENCY; Urgent (24 h) → URGENT; Non-urgent (7 days) → SOON; Self Care →
ROUTINE. A photo-only finding with no symptoms → **SOON** (user decision
2026-09-22 item 6); a missing tooth with no symptoms → ROUTINE (item 7). The medical/dental split is a sub-field of
EMERGENCY, not a fifth level.

### 2.1 Levels

| Level | Proposed time frame | Source | Headline (draft, needs sign-off) |
|---|---|---|---|
| EMERGENCY-MEDICAL | Now: emergency department or emergency number | S1, S3 | "Go to an emergency department or call emergency services now" |
| EMERGENCY-DENTAL | Today, within the hour if possible | S1, S3 | "Contact a dentist or emergency dental service now" |
| URGENT | Within 24 hours | S1, S3 | "See a dentist within 24 hours" |
| SOON | Within 7 days | S1, S3 (non-urgent) | "See a dentist within a week" |
| ROUTINE | At the next routine check-up | S4 (non-emergency); window unsourced | "No urgent action; mention this at your next check-up" |
| RETAKE | not a triage level — photo quality only | — | unchanged |

EMERGENCY may stay one level in code with a `medical: true/false` sub-field
(design §2.3) rather than two levels; the patient-facing distinction is what
matters, because "dental or medical care today" is **too weak** for an airway
problem. Which option: llm-dev's call, subject to the user.

**Photo-only finding, no symptoms:** SOON, decided by the user (2026-09-22
item 6). No source sets it; it stays a dentist's call to revisit.

**As built (2026-09-22):** the user's decisions supersede the table above for
headlines: EMERGENCY shows one screen, "This may be an emergency. Please go to
a hospital as soon as possible." (no route split; route recorded for research
only). The encoded protocol is `llm/protocol/triage_protocol.yaml` v0.1; where
it differs from §2.2–2.3 below (field names, no follow-up questions 2a/4a,
18 questions), the YAML is current.

### 2.2 Criteria (each becomes one protocol entry)

`S` = structured (code can evaluate), `N` = narrative (needs patient words).
Fields marked * are new (symptoms 1.1).

| id | Level | Criterion | Fields | Kind | Source |
|---|---|---|---|---|---|
| EM1 | EMERGENCY-M | Difficulty breathing or swallowing | difficulty_swallowing_or_breathing | S, floor | S1 swelling; S1 abscess page |
| EM2 | EMERGENCY-M | Swelling spreading to eye or neck, or getting worse quickly | swelling_features* contains spreading_to_eye_or_neck OR worsening_fast | S | S1 swelling; S3 §3.2 |
| EM3 | EMERGENCY-M | Can't open the mouth normally, or tongue/floor of mouth raised | swelling_features* contains limited_mouth_opening OR tongue_raised | S | S1 swelling |
| EM4 | EMERGENCY-M | Fever, shivering or feeling very unwell (with a dental problem) | fever == true OR systemically_unwell* == true | S, floor (fever) | S1 swelling; S1 sepsis page |
| EM5 | EMERGENCY-M | Head injury or passed out | trauma_features* contains head_injury_or_passed_out | S | S1/S2 trauma |
| EM6 | EMERGENCY-M | Jaw pain with chest pain or breathlessness | chest_pain_or_breathless* == true | S | S1 pain |
| EM7 | EMERGENCY-M | Took more pain relief than the packet allows | exceeded_pain_relief_dose* == true | S | S1 pain |
| EM8 | EMERGENCY-M | Teeth no longer meet after an injury; tooth piece may have been breathed in | trauma_features* contains bite_changed; inhaled tooth is narrative | S / N | S2 trauma |
| ED1 | EMERGENCY-D | Adult tooth knocked out | trauma_features* contains tooth_knocked_out | S | S1/S2 trauma; S3; S7 |
| ED2 | EMERGENCY-D | Bleeding in the mouth that pressure does not stop | bleeding_uncontrolled* == true | S | S1/S2 bleeding; S3 |
| U1 | URGENT | Tooth pain not controlled by pain relief the patient has taken | pain_relief_effect* == not_helped | S | S1 pain; S1 pulpitis; S3 §3.3 |
| U2 | URGENT | Pain on biting or pressing on a tooth | pain_on_biting == true OR pain_triggers contains biting | S | S1 SAP page; S5 SAP |
| U3 | URGENT | Swelling (not spreading) that is growing slowly, hot or firm | swelling_features* contains worsening_slowly; "hot/firm" narrative | S / N | S1 swelling |
| U4 | URGENT | Pain after a recent tooth extraction | recent_extraction* AND pain_present | S | S1 pain |
| U5 | URGENT | Adult tooth moved or broken to the nerve after injury | patient words | N | S2 trauma |
| N1 | SOON | Any tooth pain not meeting U1–U5 (controlled, or relief not tried) | pain_present | S | S1 pain |
| N2 | SOON | Localised swelling, no pain, not spreading | swelling | S (overridden by floor, see D3) | S1 swelling; S3 §3.4 |
| N3 | SOON | Broken or lost filling/crown, chipped tooth, sensitivity | patient words | N | S1 hypersensitivity; S3 §3.4 |
| P1 | SOON or ROUTINE (Q3) | Possible cavity flagged in the photo, no symptoms | visual_summary.flagged_teeth | S | none — dentist's call |
| P2 | ROUTINE (Q4) | Tooth appears missing, no symptoms | unexpected_missing_teeth | S | none — dentist's call |
| R0 | ROUTINE | None of the above | — | S | S4 |

Pain descriptors (lingering, night pain, spontaneous) are **not** level
criteria in S1: pulpitis is non-urgent unless analgesia fails. They stay in
the interview because the explanation uses them and a dentist may want them
(Q2).

### 2.3 Question list (Python owns order; red flags first)

Follow-ups are asked only on "yes", to keep the turn count close to today's 9.

| # | Asks about | Fields | Asked if | Stops on yes |
|---|---|---|---|---|
| 1 | Difficulty breathing or swallowing | difficulty_swallowing_or_breathing | always | yes |
| 1b | Chest pain or breathlessness with the jaw pain | chest_pain_or_breathless* | always | yes (if floor extended, Q12) |
| 2 | Swelling of face or gums | swelling | always | yes (floor) |
| 2a | Spreading to eye or neck; getting worse fast or slowly; can't open mouth; tongue raised | swelling_features* | swelling | **conditional** — asked only if Q13 = one route follow-up |
| 3 | Fever | fever | always | yes (floor) |
| 3b | Shivering or feeling very unwell | systemically_unwell* | always | yes (if floor extended) |
| 4 | Recent knock or injury to the mouth | recent_trauma | always | yes (floor) |
| 4a | Head injury or passed out; tooth knocked out; teeth no longer meet | trauma_features* | trauma | **conditional** — as 2a |
| 5 | Bleeding that won't stop with pressure | bleeding_uncontrolled* | always | yes (if floor extended) |
| 6 | Pain now | pain_present | always | |
| 7 | Taken more pain relief than the packet says (no drug or dose named) | exceeded_pain_relief_dose* | pain | yes |
| 8 | Has pain relief helped / not helped / not tried | pain_relief_effect* | pain | |
| 9 | How bad (stops sleeping or eating?) | pain_severity* | pain | |
| 10 | Triggers incl. biting | pain_triggers, pain_on_biting | pain | |
| 11 | Fades quickly or keeps aching | pain_lingers_over_30s | pain | |
| 12 | Wakes at night | pain_wakes_at_night | pain | |
| 13 | Tooth taken out recently | recent_extraction* | pain | |
| 14 | Where | location | pain | |
| 15 | How long | duration_days | pain | |

Field names follow llm-dev's evidence-checkable versions (array fields
`swelling_features`, `trauma_features`; see the design §2.2). Questions are
split so each groups only floor items or only non-floor items: a bare "yes"
to a mixed question cannot fill one field.

**Follow-ups 2a and 4a are conditional on Q13.** Under the user's floor any
swelling or trauma is already EMERGENCY, so these follow-ups cannot change the
level, only the route (emergency department vs emergency dentist). If the
user chooses to stop at once and show a fixed screen with both routes, 2a and
4a are never asked in live sessions, and EM2, EM3, EM5, EM8, ED1 and U3 are
used only to word that screen and to score vignettes.

The questions without follow-ups add about five to a patient without red
flags (up to 17 plan items). Latency (~17 s/turn today) makes this a real
cost; pre-written English question text (design decision 4) would offset it.

### 2.4 Discrepancies with the current `llm/rules.py`

"Over" = sends the patient sooner than the source; "under" = later (unsafe).

| # | Current | Sources say | Direction |
|---|---|---|---|
| D1 | URGENT headline "within a few days" | Urgent = within 24 h (S1, S3) | **under** |
| D2 | SOON headline "in the next few weeks" | Non-urgent = within 7 days for symptomatic cases (S1, S3) | **under** for R6 (pain, nothing visible) |
| D3 | R1: any swelling → EMERGENCY | Graded: localised non-spreading → Non-urgent; slowly growing/hot/firm → Urgent; spreading/airway/eye/systemic → Emergency medical | over (safe); the user's floor keeps this deliberately |
| D4 | R1 headline "Seek dental or medical care today" for breathing difficulty | Emergency medical: ED or 999 **now** | **under** (wording) |
| D5 | R2: any trauma → EMERGENCY | Graded: minor → Self care/Non-urgent; moved adult tooth or pulp exposed → Urgent; avulsion → Emergency dental | over (safe); floor keeps it |
| D6 | R3: lingering / night / spontaneous pain → URGENT | Pulpitis → Non-urgent unless analgesia fails (S1) | over |
| D7 | `LINGERING_PAIN_SECONDS = 30` | S5 says "lingering", no duration | unsourced |
| D8 | Analgesic control is never asked | S1's main pain discriminator | **under**: uncontrolled pain with nothing visible gets R6 SOON (weeks) instead of Urgent (24 h) |
| D9 | Not asked: uncontrolled bleeding, MI signs, overdose, eye-closing swelling, trismus, avulsion, inhaled tooth, recent extraction | Emergency or Urgent in S1 | **under** (not detected) |
| D10 | R5 caries, no symptoms → SOON | No source gives a time frame | unsourced (Q3) |
| D11 | R8 missing teeth → SOON, citing WHO survey methods | WHO manual is not triage; no source | unsourced (Q4) |
| D12 | Fever alone is not in R1 | The floor adds it; S1 treats fever as a systemic sign | floor raises (safe) |
| D13 | `rules.py` docstring cites SDCEP for R1/R2 | SDCEP grades both (D3, D5) | citation overstated |

`rules.py` stays the unedited baseline for the paper comparison; these
discrepancies are **not** fixes to make there without the user's sign-off
(rule 4). The one to raise now is D4: an airway problem must tell the patient
to go to an emergency department, whichever system decides.

### 2.5 The brief's three levels vs the sources

| Brief | Sources | Fit |
|---|---|---|
| "See a dentist urgently" | Emergency (medical/dental) + Urgent | Fits, but the brief's red flags go to "emergency department or nearest dentist" — S1 splits these: airway/systemic → ED, avulsion/bleeding → dentist. |
| "Routine observation" | Non-urgent (7 d) + ROUTINE | Fits. |
| "Safe self-care" | SDCEP Self Care | **Conflict for this app**: S1 never ends adult tooth pain at Self Care, and our symptomatic patients all have tooth complaints. Self Care in S1 covers erupting teeth in children, minor soft-tissue injury, stopped extraction bleeding. Proposal: no separate SELF_CARE level; ROUTINE carries prevention advice. Q5. |
| "Unbearable pain" as a red flag → ED | Uncontrolled pain = **Urgent dental, 24 h** (S1, S3), not ED | Conflict. Q1. |
| "Swelling to the neck", fever, shortness of breath | Emergency medical (S1, S3) | Fits. |

S1's self-care advice includes chlorhexidine mouthwash and "optimal
analgesia"; S1 also tells non-dental settings to consider prescribing
antibiotics. Our guardrails forbid naming prescription drugs, so knowledge
passages built from S1 must strip those parts.

---

## 3. Dataset plan

Read from the Hugging Face cards and API metadata only; nothing downloaded.

| | lavita/ChatDoctor-HealthCareMagic-100k | hyesunyun/liveqa_medical_trec2017 |
|---|---|---|
| Size | 112,165 rows, one `train` split, 70.5 MB download | 634 training QA pairs (Train1 388 from 200 questions; Train2 246) + 104 test questions |
| Language | Card declares **none**. The upstream ChatDoctor README and its sample are English, but that is not a check of every row: the filter adds an English check (P8) and reports how many rows it drops. | Card declares `language: en`. |
| Fields | `instruction` (fixed prompt), `input` (patient message), `output` (doctor reply) | Question, sub-questions with focus and type (23 types), reference answers with URL (test answers validated by experts) |
| Licence on card | **None declared** (card is a stub) | **None declared**; GitHub repo abachaa/LiveQA_MedicalTask_TREC2017 has no licence file |
| Upstream terms | ChatDoctor repo code is Apache-2.0, but its README says the work is "for academic research only and any commercial use and clinical use is prohibited". Conversations were scraped from HealthCareMagic.com; that site's terms not checked. | NLM consumer questions; cite Ben Abacha et al., TREC 2017. |
| Dental size | Unknown until filtered. HF search hits (any field, **not dental-specific**): "jaw" 1,978, "abscess" 1,852, "wisdom" 1,299, "cavity" 1,144; other terms timed out. Rough guess: 2–5k dental dialogues. | Search found 1–2 test questions per dental term: **a handful at most**. Not worth a pipeline; hand-pick. |
| Triage labels | **None** | **None** |
| Answer quality | Online doctors, unverified; answers typically name drugs and doses and state diagnoses — the filter will remove most answers. | Reference answers from trusted sites; still no urgency. |

**What these datasets can and cannot show.** They have no urgency labels, so
they **cannot** measure triage accuracy, and they cannot pick "the best model"
for triage. Scoring model answers against the online doctors' answers would
reward exactly what our guardrails forbid. Their honest uses:

1. **Guardrail stress test**: filtered patient messages as inputs; count
   drug/dose/diagnosis/DIY/missing-disclaimer violations per model. No
   reference answer needed.
2. **Red-flag detection**: a hand-labelled subset of patient messages
   (red flag present yes/no) tests the interview's keyword pre-screen and
   extraction on real phrasing.
3. **Phrasing realism** for vignettes (style only; no text copied into the
   eval set, given the licence gap).
4. **QLoRA data**, only if the design §6 trigger fires, and only after
   dentist-audited labels.

**Topic filter (dental/oral/gum/jaw), on the patient `input`:**
- Stage 1, keyword include (case-insensitive, word-boundary): tooth, teeth,
  toothache, dental, dentist, gum(s), gingiv*, molar, premolar, incisor,
  canine tooth, wisdom tooth, cavity/cavities *with a tooth word within 10
  words*, filling, crown, root canal, extraction *with a tooth word*, abscess
  *with a tooth/gum word*, jaw, TMJ, mouth ulcer, braces, denture,
  periodont*, orthodont*.
- Exclude: "chewing gum", nasal/abdominal/chest/pleural cavity, "jaundice"
  false hits, jaw pain with chest pain *kept* but tagged (MI red-flag cases
  are useful for item 2).
- Stage 2 (only if stage 1 precision < 90%): local LLM yes/no classifier on
  stage-1 hits. Heavy job — scheduled.

**Answer filter (drop the row if the `output` contains):**
- a drug name from a fixed list (antibiotics, analgesics incl. OTC names,
  antifungals, steroids, mouthwash brands; brand and generic);
- a dose pattern: `\d+(\.\d+)?\s?(mg|mcg|µg|g|ml|iu)`, "x times a day",
  "twice/thrice daily", bd/tds/qid, "every N hours", "N tablets";
- a definitive-diagnosis phrase: "you have (a|an)?", "you are suffering
  from", "this is (a|an|definitely)", "it is (a|an) … (infection|abscess|
  cyst|tumou?r|cancer)", "diagnosed with", "confirms".
- Rows are dropped, not edited.

**Spot checks (research-pm, by hand, results in `labels/`):**
- Topic precision: 200 random kept rows → share truly dental, with 95%
  Wilson CI. Target ≥ 95%.
- Topic recall: 200 random *rejected* rows that mention mouth, face, jaw or
  swelling → share that are dental. Report, no target.
- Answer filter residual: 200 random kept answers → any drug, dose or
  definitive diagnosis. Target 0 (with 200, 0 found bounds the rate at ≤1.5%).
- Over-removal: 100 random dropped answers → share dropped wrongly.
- Report counts at each stage.

### 3.0 P9 filter audit results (research-pm, 2026-09-22)

These are hand audits of qa-engineer's P8 output (`dataset/dental_qa/`: 7,553
topic rows, 2,829 clean rows). Labels are in `labels/dental_filter_audit.csv`
(ids and labels only, no dataset text). There was one reader and no second
rater, so the rates carry one person's judgement. Seeds are fixed (9001–9004).

| Audit | Result | 95% CI | Target | Met? |
|---|---|---|---|---|
| A1 topic precision, 200 kept rows | 153/200 = 76.5% dental (85.0% counting 17 borderline as dental) | 70–82% | ≥ 95% | **no** |
| A2 topic recall, 200 rejected rows mentioning mouth/face/jaw/swelling (pool 10,128) | 14/200 = 7.0% were dental/oral (26/200 with borderline) | 4–11% | report | ≈ 700 missed rows in the pool |
| A3 residual in clean answers, 200 rows | 25/200 = 12.5% still name a medicine, give a dose, or state a definitive diagnosis (medicine 15, dose 3, diagnosis 12; some rows have more than one) | 9–18% | 0 | **no** |
| A3 truncated or empty answers | 12/200 = 6.0% ("Hello", or text that stops mid-sentence) | 4–10% | — | they pass only because they say nothing |
| A4 over-removal, 100 dropped rows | 16/100 dropped wrongly (27/100 counting borderline) | 10–24% | report | — |

What drives the errors:
- **A1:** these are systemic or non-dental questions that mention a dental
  word in passing: "feels like a toothache in my leg", teething blamed for
  diarrhoea, "I am a dental hygienist", or blood pressure taken at the ER
  during a tooth visit.
- **A2:** the include list has no oral-mucosa terms (tongue, inside of the
  mouth, palate, lip). One miss is "a few fillings on the left side of my
  mouth", where the loose-term rule wanted a tooth word nearby.
- **A3, medicine names:** 8 of the 15 leaks are medicine names garbled by the
  dataset's own automatic text correction: "petrol DT", "erosion forte",
  "choral forte", "stolen gum paint" (twice), "Evil, Lyrics & Polite",
  "Mention violet", "President 5000 plus", "Humor HP 75". No word list can
  catch these.
- **A3, diagnoses:** definitive diagnoses mostly use "is due to", "is because
  of", "indicates", "This should be a case of", or "YOUR two front teeth are
  affected with…". The "you have a/an" pattern misses them.
- **A4:** the wrong drops come from the dose regex hitting saline-rinse or
  brushing frequencies, from generic words ("mouthwash",
  "anti-inflammatory"), and from antibiotics named as a *cause* ("stains
  from some antibiotics") rather than advised.

**Consequences:**
1. The clean set is **not guardrail-clean**: about 1 in 8 answers still
   breaks a guardrail. It must not be used as a fine-tuning target without an
   LLM or human pass. This does not affect silver labels, which read the
   answer only for urgency (§3.2).
2. For guardrail stress tests (§3, use 1) only the *questions* are used, so
   answer residuals don't matter there. Topic precision does: about 1 in 4
   rows isn't dental. Stage 2 of the topic filter (a local LLM yes/no
   classifier, planned for precision below 90%) is now triggered.
3. Garbled medicine names also matter for our own output check: the model
   could echo a garbled name from retrieved text. This is not a risk today,
   because none of this data is in the knowledge base.

### 3.1 Hugging Face search for urgency-labelled data (2026-09-22)

I searched the Hub API for dental, tooth, toothache, dental pain, dental
triage, oral health, triage, urgency, emergency triage, medical triage,
acuity and symptom checker. I read only the cards, API metadata and the
first rows through the datasets-server; nothing was downloaded.

| Dataset | Size | Labels | Licence | Fit |
|---|---|---|---|---|
| `daveancheta/denta_urgency` | 20,000 rows (one JSON file, 2026-05) | HIGH / MEDIUM / LOW urgency inside templated answers (first 100 rows: 35 / 36 / 29) | **no card, no licence**, provenance unknown | **The only dental urgency set found. Not usable as a reference.** It is synthetic: condition phrases are slotted into fixed templates ("X is MEDIUM URGENCY… within 48–72 hours"). Its windows (MEDIUM 48–72 h, LOW 1–6 months) match no source. Some labels conflict with SDCEP: night pain is HIGH ("seek emergency care today"), while SDCEP says Non-urgent if pain relief works. Answers suggest "home remedies" and "pain relievers". Possible use: a list of condition phrases for vignette variety. |
| `sweatSmile/medical-symptom-triage-conversational` | 1,390 (train 1,112 / val 278) | Emergency / Urgent / Routine + specialty | none declared | General medicine, synthetic. "tooth" 0 hits, "jaw" 82 (mostly cardiac). No dental use. |
| `syntech-ai/medical-triage-500` | 500 | urgency + red flags | CC BY-NC 4.0 | Synthetic, rule-generated general triage. The viewer fails on it. No dental content found. |
| `TimotheeB/triage-medical-dataset` | 100k+ (SFT/DPO) | none per case | CC BY 4.0 | Built from exam MCQs and MedQuAD. Not triage-labelled. |
| `kondratevakate/hospital-triage-and-patient-history-data` | 560,486 ED visits | ED triage (ESI) + admission | Apache-2.0 re-host of Hong et al. 2018 (Yale) | Real hospital ED tabular data. Not dental, not patient text. |
| `jonathankang/dental_QA` and other dental Q&A sets | ≤10k | none | mostly none declared ("forum crawled") | No urgency labels. |

**Conclusion.** No credible dental triage dataset with urgency labels exists
on the Hub. The one dental set with labels is templated and unlicensed, and
its levels disagree with SDCEP. The primary key therefore stays with the
SDCEP-derived held-out vignettes (decision 12), and the silver labels (§3.2)
remain the only real-patient-text check.

### 3.2 Silver labels from ChatDoctor doctors' answers (rubric for qa-engineer)

**Goal.** For each dental HealthCareMagic row, record the urgency the doctor's
answer *implies*. These are weak labels: an online doctor's advice, not a
triage decision, and not a dentist's. They are reported separately from the
primary key and never used for tuning.

**Unit.** One row = patient `input` + doctor `output`. The label comes only
from `output`. The system under test sees only `input`.

**Which rows.** Rows after the topic filter, *before* the drug/dose/diagnosis
answer filter. The doctor's text is only read to derive a label; it is never
shown to a model or used as a training target, so the guardrail reason for
the answer filter does not apply. Removing those rows would also drop most
answers and bias the sample. **This departs from the letter of decision 13**
and needs the lead's agreement. The alternative is labelling only filtered
rows, with coverage reported.

**Labels:** `EMERGENCY`, `URGENT`, `SOON`, `ROUTINE`, `UNSPECIFIED`.

**Rule stage (deterministic; case-insensitive; phrase lists are versioned in the script):**

| Label | Answer contains (examples) |
|---|---|
| EMERGENCY | "emergency", "casualty", "ER", "A&E", "go to (the) hospital", "immediately", "right away", "call an ambulance"; or a warning that swelling can reach the airway/neck/eye paired with an instruction to seek care now |
| URGENT | "as soon as possible", "asap", "at the earliest", "urgently", "without delay", "today", "tomorrow", "within 24 hours", "don't delay" |
| SOON | "within a few days", "this week", "in the next few days", "soon", "within a week" |
| ROUTINE | "nothing to worry", "no need to (worry\|see)", "at your next (check-up\|visit)", "routine", "can wait", "normal and will settle"; or self-care advice with no visit recommended |
| UNSPECIFIED | only "consult / visit / see a dentist" with **no timing word**, or no recommendation at all |

- A negated phrase does not count ("not an emergency" is not EMERGENCY; "no
  need to rush" → ROUTINE). The script checks for a negation within 3 words
  before the phrase.
- Several labels in one answer → the most urgent one wins, and the row is
  marked `conflicted: true`.
- A bare "consult a dentist" is **UNSPECIFIED, not SOON.** Almost every answer
  says it, so it carries no urgency.
- Output per row: `silver_label`, `matched_phrase`, `conflicted`.

**Optional LLM stage.** Only if rule coverage is below 30% of rows: a local
model labels the UNSPECIFIED rows with the same five labels and must quote the
phrase it relied on (checked against the answer). This is a heavy job,
scheduled by qa-engineer. Its labels are reported apart from the rule
labels.

**Validation (research-pm, by hand, before any use).** Two batches, both read
blind to the rule's output. **Use bar:** κ ≥ 0.6 and EMERGENCY precision
≥ 90%. Below the bar, the silver labels are not used for any claim.

*Batch 1 — done 2026-09-23, before the rule script existed* (the lead's
instruction: seeing the script's labels first would bias κ). 200 rows drawn at
random (seed 9005) from the pre-filter dental subset, so the distribution is
the corpus's own. Labels: `labels/silver_hand_labels.csv` (ids and labels
only). Distribution:

| Hand label | n |
|---|---|
| UNSPECIFIED | 139 (69.5%) |
| ROUTINE | 40 (20.0%) |
| URGENT | 16 (8.0%) |
| SOON | 3 (1.5%) |
| EMERGENCY | 2 (1.0%) |

This batch gives κ and overall agreement once qa-engineer's script has run on
the same 200 ids. It **cannot** give EMERGENCY precision: 2 cases.

*Batch 2 — done 2026-09-23.* 80 rows: 40 the script called EMERGENCY plus 40
from its other labels, shuffled, read blind, labels saved before the key was
opened (`labels/silver_calibration_hand.csv`).

**EMERGENCY precision: 8/40 = 20% (95% CI 10–35%).** Bar was ≥ 90%.
Of the 32 the script called EMERGENCY and I did not: 12 I read as URGENT, 15
as UNSPECIFIED, 5 as ROUTINE. Agreement across the whole batch was 34/80, but
that batch is deliberately EMERGENCY-enriched and is not an estimate of
corpus agreement.

Where the false emergencies come from, in order of size:
1. **"Immediately" attached to a clinician, not a place.** "You should
   immediately consult your dentist / dermatologist / pulmonologist" is how
   these doctors write "promptly". 12 rows.
2. **"ER" as a venue, not an urgency.** "Consult an Emergency room or an Oral
   Physician and get evaluated" for jaw clicking; "an Emergency room ... and
   get a laryngoscopy done".
3. **Garbled text.** "Consult ER surgeon", "consult ER ENT", "go to ER
   Surgeon" — the dataset's own text correction has mangled ENT into ER. No
   phrase rule can recover that.
4. **Immediacy attached to something else entirely:** "see a dermatologist for
   immediate relief", "stop it [cocaine] immediately", "Immediately start warm
   saline rinses ... then visit your dentist".
5. **Conditionals and negations:** "if symptoms worsen you can immediately
   consult an Emergency room"; "I do not see anything to go to ER ... wait for
   your dentist's next appointment".

Only one row went the other way: an answer raising hospital admission for IV
fluids, which the script called UNSPECIFIED.

**Decision: stop here and report the silver labels as a negative result.**
Reasons, in the order that decided it:
- Both pre-registered bars are missed, and not narrowly: κ 0.269 blind (0.406
  after qa-engineer's two corrections, which are tuned on the same 200 rows
  and must be labelled as such), and EMERGENCY precision 20% against a 90%
  bar.
- The largest remaining disagreement in batch 1 (24 rows) is an ambiguity in
  **my** rubric, not a coding fault: an answer that reassures, gives self-care
  *and* says "see a dentist" with no timing satisfies the ROUTINE clause and
  the UNSPECIFIED clause at once. For the record, the resolution I would apply
  is that **UNSPECIFIED wins whenever any visit is recommended without a time
  frame** (precision over coverage). But a construct whose own author cannot
  apply it consistently across 200 rows is the wrong instrument.
- The remaining fixes — scoping "immediately" to its object, telling a venue
  from an urgency, undoing the corpus's own garbling — are open NLP problems,
  and every fix would be tuned on the only rows we have.
- The ceiling is low even if all of that worked: 24.5% coverage, about 1%
  emergencies, on rows that are ~76% dental (lower since the oral soft-tissue
  terms were added). It could never have tested the EMERGENCY/URGENT boundary,
  which is the boundary that matters for under-triage.
- The construct itself is weak: the label is what a doctor wrote on a Q&A
  site, not how soon the patient needed care.

**What survives.** The corpus description stays as a finding about the data
(coverage 24.5%; EMERGENCY 424, URGENT 349, SOON 305, ROUTINE 1,358,
UNSPECIFIED 7,518 of 9,955). The script, the labels and both hand batches stay
in the repository as the record of a documented, failed attempt. Nothing
downstream depends on them; the evaluation rests on the SDCEP-derived
held-out keys, dentist labels when a dentist is found, and the P10 red-flag
recall on real messages (§3.3).

What batch 1 already shows about the corpus:
- **Coverage is low.** 69.5% of answers recommend a dentist with no timing at
  all, so at most ~30% of rows can carry a silver label.
- **Urgency is thin at the top.** Only 1% read as emergency and 1.5% as "within
  a week". Most timed advice is either "as soon as possible" (URGENT) or
  reassurance (ROUTINE). A comparison against silver labels will therefore say
  almost nothing about the EMERGENCY/URGENT boundary.
- **Phrases the rule will get wrong** (all seen in batch 1): "Though not an
  emergency, … demands immediate … care"; "take her to ER" offered only as a
  way to get a painkiller prescription; "There is no emergency, if she is
  troubled take her to ER"; "the earlier you visit a dentist, the better",
  which has no window. Negation and context handling decide whether κ clears
  the bar.
- One row (`cd011595`) holds the patient's question in the answer field: a
  data fault in the source, not a filter fault.

**How it's scored.** Run the system on `input` alone:
- evidence-checked extraction from that one message;
- visual summary = "no photos", which needs a no-photo input mode (llm-dev);
- missing answers stay null;
- LLM triage and the rules baseline both run.

Report agreement with the silver label on labelled rows only, plus
"system less urgent than silver" as the under-triage proxy. Report it with
its limits:
- one message, not an interview;
- online doctors over-refer;
- the label says what a doctor wrote, not what the patient needed.

### 3.3 P10 red-flag labels on real patient messages (2026-09-23)

200 patient *questions* drawn at random (seed 9006) from the pre-filter dental
subset, hand-labelled for "does this message state a red flag?", using the
protocol's checklist-A rows as the definition. Labels:
`labels/redflag_messages.csv` (ids and labels only). One reader, no second
rater. 9 of the 200 also appear in the P9 topic sample.

| | n |
|---|---|
| Red flag stated | 46 (23.0%) |
| No red flag | 131 (65.5%) |
| Unclear | 23 (11.5%) |

Fields named (46 messages, 9 of them name two or more): swelling 35, fever 6,
systemically unwell 4, chest pain or breathlessness 4, difficulty breathing or
swallowing 3, recent trauma 2, too much pain relief 1, uncontrolled bleeding 0.

**Use.** These messages test extraction and the keyword pre-screen against real
phrasing: does a red flag stated in the patient's own words come back `true`
rather than `null`? Scored as recall on the 46 (a miss is the failure that
matters) and false-positive rate on the 131. The 23 unclear ones are reported
separately and never counted as errors either way.

**Limits, and they are serious:**
- **The flag mix is nothing like the interview's.** Swelling is 76% of all
  flags; uncontrolled bleeding never appears, and overdose and trauma appear
  once or twice. Rare flags still need synthetic cases; this set cannot
  measure them.
- **These are opening messages, not answers to a checklist.** Under the
  2026-09-22 checklist decision, red flags are ticked, not extracted from
  prose. So this set now tests the keyword pre-screen and the free-text
  path (the follow-up Q&A in the explanation step, design §1.6), not the main
  red-flag path.
- **Near misses that our rows do not cover** turned up repeatedly and are
  worth a dentist's eye: trismus alone ("can only open one finger"), double
  vision with jaw numbness, a hoarse or changed voice, and painkillers not
  helping. Only the last is in the protocol at all (U1, URGENT).
- Keyword distractors are common: "swelling" in wrist, knee, leg or collar
  bone, and dog bites to the leg. A pre-screen keyed on the word alone will
  fire on these, which is why a hit may only reorder questions and must never
  set a field.

---

## 4. Evaluation design (Test 5: triage)

Aligned with the design §5.2; this section fixes the data, the labels and the
statistics.

**Vignettes, answer key first.** For each vignette the author writes the key
first: protocol level, the criteria met, and the exact `symptoms` +
`visual_summary`. A local model (not the one under test) then writes patient
words from the key, in English (plain, vague, non-native and
self-correcting styles). Checks: a second local model extracts the fields blind;
disagreements reviewed by hand; code checks for impossible combinations and
near-duplicates; research-pm reads 50 at random and reports the error rate.
Nothing leaves the machine.

**How many.**
- Dev: 100 (llm-dev and qa-engineer may tune on these).
- Held-out: **200**, keys written by research-pm only, never seen by llm-dev,
  scored once per configuration. 0 under-triage in 200 bounds the rate at
  ≤1.5% (rule of three). It does **not** show the rate is zero.
- Stratified: EMERGENCY 45 (≥15 medical, ≥10 dental), URGENT 55, SOON 55,
  ROUTINE 45. At least 40% are boundary cases (e.g. pain controlled vs not;
  localised vs spreading swelling; photo finding with brief sensitivity;
  vague or self-correcting answers; one prompt-injection line).
- Plus 60 end-to-end dialogues (interview → extraction → triage) so an
  under-triage can be traced to the question, the extraction or the triage.
- The 20 `rule_cases.json` cases are rendered as readable vignettes and
  labelled with the rest.

**Dentist blind labels.**
- The dentist sees only the vignette text: patient words and a plain-English
  photo line ("the photo flagged a possible cavity on the upper right first
  molar" / "photos showed nothing"). Not the key, not the LLM or rules
  output. Order randomised.
- Label form: the level (definitions and time frames printed on the form,
  identical to §2.1), the main reason in a few words, and a "not enough
  information" box.
- Two dentists if possible; disagreements resolved by discussion, and the
  consensus is the reference. With one dentist, 20 cases are repeated two
  weeks later for intra-rater agreement.
- Load: ~220 vignettes × ~1 min ≈ 4 h per dentist.
- `dentist_label` in `rule_cases.json` is filled from this, by qa-engineer,
  after labelling is complete.

**Metrics** (levels ordered EMERGENCY > URGENT > SOON > ROUTINE; EMERGENCY
medical/dental counted as one level for κ, and reported separately; RETAKE
excluded — image quality is scored separately):
- Under-triage rate: system level less urgent than the dentist's. Primary,
  with exact 95% CI. Also by level, and "severe under-triage" (≥2 levels, or
  any EMERGENCY missed).
- Over-triage rate, exact agreement, linearly weighted κ with bootstrap CI.
- Three pairs: LLM vs dentist, rules vs dentist, LLM vs rules; plus
  **key vs dentist**, which tests the protocol itself.
- LLM vs rules on under-triage: exact McNemar on the paired discordant cases.
- From the design: how often the LLM's own level decided the outcome vs floor
  or protocol check; fallback rate; stability.

**What it does not show.** Vignettes assume the photo line is correct. The
detector catches ~29% of carious photos at 0.50 (open decision), so an
asymptomatic patient with a missed cavity gets ROUTINE whatever the LLM does.
Triage accuracy here is conditional on the findings; end-to-end accuracy on
real patients is not measured by this test.

**Decisions this changes (pre-registered):**
- Any held-out under-triage → classify the cause (protocol gap, interview,
  extraction, LLM). Protocol gaps go back to the dentist; only LLM-caused
  ones count towards the fine-tuning trigger (design §6).
- If rules.py under-triages less than the LLM, or the LLM gains no κ over
  rules, that is the paper's finding and is reported as such.
- Key-vs-dentist κ below the user's bar → the protocol is revised before any
  model comparison is claimed.

---

## 5. Task breakdown

Heavy jobs (GPU / Ollama) are marked **H** and run one at a time, by
qa-engineer unless stated. T-numbers refer to the design §8.

| # | Task | Owner | Done when | Proved by |
|---|---|---|---|---|
| P1 | User reviews this plan and the design; answers §6 | user via lead | answers recorded in `docs/decisions.md` | decision entries |
| P2 | Protocol v0.1 content (criteria, levels, questions, sources with page/section) → llm-dev encodes (T1) | research-pm (content), llm-dev (YAML) | every criterion has a source or "dentist's call"; every field is filled by a question | T3 coverage test passes |
| P3 | Re-read unreadable sources: S1 trauma, bleeding, ulceration flowcharts; S3 figure 1; S7 full text | research-pm | each marked "read" in §1 or listed as inaccessible | updated §1 |
| P4 | Dentist packet: protocol review form, vignette label form, instructions | research-pm | user approves the packet | — |
| P5 | Held-out vignette keys (200) + 60 end-to-end keys | research-pm | keys stratified per §4; not shared with llm-dev | qa-engineer's schema and duplicate check |
| P6 | Dev vignette keys (100) | llm-dev + qa-engineer | per §4 | same checks |
| P7 | **H** Generate vignette text from keys; blind second-model extraction | qa-engineer | all keys have text; disagreements reviewed | disagreement count + 50-case manual read error rate |
| P8 | Dataset download (after lead approval) + filter script `src/filter_dental_qa.py`: English check, topic filter, answer filter | qa-engineer | counts at each stage reported, incl. non-English rows dropped | — |
| P9 | Filter spot checks (4 audits in §3) | research-pm | `labels/dental_filter_audit.csv`; precision, residual violations with CI | report numbers vs targets |
| P10 | Hand-label red-flag present/absent on 200 filtered patient messages | research-pm | `labels/redflag_messages.csv` | used in P13 |
| P11 | Design T2–T7 (contract, floor, triage step, interview, explain) | llm-dev | per design §8 | Tests 1–3, T5 unit tests, guardrail check |
| P12 | Design T8 (webapp, emergency screen, disclaimer) | app-dev | per design §8 | smoke test |
| P13 | **H** Guardrail stress test on filtered patient messages; red-flag detection on P10 | qa-engineer | violation counts per model; red-flag sensitivity with n | report |
| P14 | Dentist labels collected (vignettes + rule cases) | user arranges; research-pm prepares | all labels in, blind | — |
| P15 | **H** Phase 1: qwen3:14b, Test 5 held-out, LLM vs rules vs dentist | qa-engineer | report per §4 metrics | n, CIs |
| P16 | **H** Phase 2: model benchmark (design §5), same held-out set | qa-engineer | table per design §5.2 | selection rule applied |
| P17 | Interpret P15–P16, decision-log entry, fine-tune trigger yes/no | research-pm | entry with numbers and limits | — |

Order: P1 → P2, P3, P4 in parallel → P5/P6 and P8 → P7 (H) → P9, P10 →
P11/P12 → P13 (H) → P14 → P15 (H) → P16 (H) → P17. P14 is on the critical
path and depends on a dentist's time; P4 should go out as early as P1 allows.
Development can proceed on dev vignettes while labels are pending, but no
accuracy claim is made until P15.

---

## 6. Open questions for the user or a dentist

1. **Unbearable pain.** The brief sends it to the emergency department; S1/S3
   classify uncontrolled pain as urgent dental care within 24 h. Which?
2. **Pain descriptors.** Should lingering, night or spontaneous pain raise to
   URGENT (current R3) when pain relief works? S1 says Non-urgent (7 days).
   And is 30 s kept as the meaning of "lingering"?
3. **Photo-only finding, no symptoms**: SOON (within 7 days) or ROUTINE (next
   check-up)? No source sets this. Note the detector's false-alarm rate
   (3% at 0.50, 14% at 0.25) when deciding.
4. **Missing tooth, no symptoms**: SOON or ROUTINE? No source.
5. **"Safe self-care"**: accept that it becomes ROUTINE with prevention advice
   (no separate level), given S1 never ends adult tooth pain at self care?
6. **Floor over-triage**: the floor sends *any* swelling and *any* trauma to
   EMERGENCY; S1 grades both. Keep as is (safe but many false emergencies),
   or let the protocol grade them with only the S1 emergency features in the
   floor?
7. **Emergency wording**: split medical (emergency department / emergency
   number) from dental (emergency dentist) in the headline? Which emergency
   number and services should the app name, given the user's country?
8. **Time frames on screen**: adopt 24 h / 7 days for URGENT / SOON (fixes D1,
   D2)?
9. **Agreement bar**: the κ below which the protocol or the model is judged
   inadequate, and the held-out size (200 proposed).
10. **Dentists**: who labels, one or two, and who signs off the protocol and
    knowledge files.
11. **Datasets**: proceed with download given no licence is declared on
    either card and ChatDoctor is academic-research-only?
12. **Floor extension** (design decision 8): add uncontrolled bleeding, chest
    pain/breathlessness with jaw pain, pain-relief overdose and
    systemically-unwell-without-fever to the code floor and the interview
    stop? S1 and S3 class all four as emergencies; today none is asked (D9).
13. **Red-flag stop vs one route question** (design decision 9): stop at once
    and show a fixed screen giving both routes (emergency department for
    breathing/swallowing trouble, spreading swelling or feeling very unwell;
    emergency dentist for a knocked-out tooth or bleeding), or ask one route
    follow-up (2a/4a) first? The level is EMERGENCY either way.
14. **Ulcers and lumps** (P3): SDCEP sends an ulcer present > 3 weeks to
    urgent dental care. The interview doesn't ask. Add a question, or state
    on screen that the tool does not check for ulcers or lumps?
