# Form A — triage protocol review

Protocol: `llm/protocol/triage_protocol.yaml` v0.3, review_status `DRAFT-UNREVIEWED`.
Generated from the file on 2026-09-29 by `make_form_a.py` (research-pm). Do not edit the YAML;
write in this form and we will apply the changes.

For each row: **Agree / Change / Remove**, and if Change, what it should say.
"Source" is what we read; "our call" means no guideline sets it and the
project decided it. The wording in *Statement* is what the patient's result
may be based on, not what they are shown.

## 1. Levels and time frames

| Level | Time frame we use | On-screen headline | Agree / Change |
|---|---|---|---|
| EMERGENCY | now | "This may be an emergency. Please go to a hospital as soon as possible." | |
| URGENT | within 24 hours | "See a dentist within 24 hours." | |
| SOON | within 7 days | "See a dentist within 7 days." | |
| ROUTINE | next routine check-up | "No urgent dental visit is needed. Keep up your routine check-ups." | |

Source for all four: SDCEP *Management of Acute Dental Problems* 2nd ed.
(March 2026), "Timescales for treatment", and NHS England's 2025 unscheduled
dental care guidance §3. EMERGENCY shows one screen with no phone number
(user's decision); ROUTINE has no window in any source.

## 2. Criteria

Level = how soon. **floor** means code forces EMERGENCY on this alone, before
the model sees anything. **checklist** means the criterion is decided by a
Yes/No row the patient answers; **narrative** means the model must find it in
the patient's own words.


### EMERGENCY

| id | Statement | Decided from | floor | how | Agree / Change / Remove |
|---|---|---|---|---|---|
| E1 | Difficulty breathing or swallowing | SDCEP 2026 Swelling pathway (difficulty breathing / swallowing -> Emergency Medical Care); SDCEP 2026 Acute apical abscess (airway compromise -> emergency department); NHS England 2025 §3.2 | yes | checklist / photo | |
| E2 | Swelling of the face, jaw or gums | project owner, 22 Sep 2026 (decision 4) (any swelling stays EMERGENCY). SDCEP 2026 Swelling pathway grades swelling: only rapidly increasing / airway / eye-closing / systemically unwell is Emergency; slowly increasing, hot or firm is Urgent; otherwise Non-urgent. Deliberate over-triage, to revisit with a dentist. | yes | checklist / photo | |
| E3 | Fever with a dental problem | project owner, 22 Sep 2026 floor. SDCEP 2026 Swelling pathway ('increasing temperature' as a sign of being systemically unwell -> Emergency Medical Care); SDCEP 2026 Management of spreading or systemic infection; SDCEP 2007 §2.1.1 ('raised temperature as a result of dental infection' is a dental emergency). | yes | checklist / photo | |
| E4 | A recent knock or injury to the mouth or teeth | project owner, 22 Sep 2026 (decision 4) (any trauma stays EMERGENCY). SDCEP 2026 Trauma pathway grades trauma: head injury, loss of consciousness, significant facial trauma, uncontrollable bleeding, airway -> Emergency Medical; bite changed, inhaled tooth, large lacerations -> Emergency Care (NHS24/111); knocked-out adult tooth -> Emergency Care: Dental; moved adult tooth or pulp exposed -> Urgent; fracture into dentine -> Non-urgent; enamel chip, small lacerations -> Self care. Deliberate over-triage, to revisit with a dentist. | yes | checklist / photo | |
| E5 | Feeling very unwell, shivery or very tired along with the dental problem | project owner, 22 Sep 2026 (decision 3). SDCEP 2026 Swelling pathway (systemically unwell: rigors, dehydrated, lethargic -> Emergency Medical Care); SDCEP 2026 Management of spreading or systemic infection (sepsis signs). | yes | checklist / photo | |
| E6 | Chest pain or shortness of breath along with jaw or tooth pain | project owner, 22 Sep 2026 (decision 3). SDCEP 2026 Pain pathway, first step (atypical jaw pain with signs of myocardial infarction -> Emergency Medical Care). | yes | checklist / photo | |
| E7 | Bleeding in the mouth that does not stop with pressure | project owner, 22 Sep 2026 (decision 3). SDCEP 2026 Bleeding pathway (bleeding after dental treatment not stopped by pressure -> Emergency Care: Dental or NHS24/111; brisk and persistent bleeding -> Emergency Care); SDCEP 2007 §2.1.1; NHS England 2025 §3.2 (intra-oral bleeding the patient cannot control with local measures). | yes | checklist / photo | |
| E8 | More pain relief taken than the packet says is safe | project owner, 22 Sep 2026 (decision 3). SDCEP 2026 Pain pathway, first step (exceeded the recommended dose of pain relief -> Emergency Medical Care). | yes | checklist / photo | |

### URGENT

| id | Statement | Decided from | floor | how | Agree / Change / Remove |
|---|---|---|---|---|---|
| U1 | Tooth pain that pain relief has not controlled | SDCEP 2026 Pain pathway ('Has analgesic controlled the pain?' No -> Urgent Care: Dental); SDCEP 2026 Pulpitis (urgent if analgesia ineffective); SDCEP 2007 §2.1.2; NHS England 2025 §3.3. |  | checklist / photo | |
| U2 | Severe pain that stops normal sleeping or eating | project owner, 22 Sep 2026 (decision 2) (unbearable pain is URGENT, not the emergency department). NHS England 2025 §3.3 lists severe pain not controlled by self-help as Urgent; severity alone, without relief tried, is the user's extension. |  | checklist / photo | |
| U3 | Pain when biting on or pressing a tooth | SDCEP 2026 Symptomatic apical periodontitis (tender to pressing; seek urgent dental care); AAE 2009 terminology Symptomatic apical periodontitis (painful response to biting). |  | checklist / photo | |
| U4 | Pain after a tooth was taken out recently | SDCEP 2026 Pain pathway ('Has the patient recently had a tooth extracted?' Yes -> Urgent Care: Dental). |  | checklist / photo | |
| U7 | A possible cavity seen in the photo, together with tooth pain | OUR CALL - no source sets this. Kept from rules.py R4 so the protocol is not less urgent than the rules baseline. SDCEP 2026 would give Non-urgent (7 days) when pain relief works. |  | checklist / photo | |
| U8 | Pus, a gum boil or a bad-tasting discharge from the gum or a tooth | SDCEP 2026 Acute apical abscess (without airway compromise: seek urgent dental care); AAE 2009 terminology Acute apical abscess (pus formation). OUR CALL - no source sets this: v0.2 applies it with or without pain; a painless draining sinus may be chronic apical abscess, which SDCEP may place lower. Deliberate over-triage until a dentist decides. |  | checklist / photo | |
| U9 | A mouth ulcer, sore or lump that has lasted more than 3 weeks | project owner, 22 Sep 2026 (ulcer question added). SDCEP 2026 Ulceration pathway (ulcer present more than 3 weeks -> dental assessment for possible urgent-suspicion-of-cancer referral -> Urgent Care: Dental); SDCEP 2013 Altered sensation or abnormal appearance pathway (red, white or pigmented lesion present more than 3 weeks -> Urgent Care: local rapid access pathway). |  | checklist / photo | |
| U10 | Tooth pain, and it is not known whether pain relief has helped | project owner, 26 Sep 2026 (the user delegated 'the one closest to SDCEP'; ruled by the lead; provisional). SDCEP 2026 Pain pathway flowchart (re-read 2026-09-26): both Non-urgent exits need a known answer ('Has analgesic been taken?' No, or 'Has analgesic controlled the pain?' Yes); the pathway has no branch for an unknown answer, so URGENT here is the project's conservative reading, not SDCEP wording. Project rule: an unanswered question is never treated as reassuring (user decision 2026-09-26; awaiting a dentist's decision, Form C, C12). |  | checklist / photo | |

Retired in v0.3: U5, U6 (ids not reused) - see Form C, C2.

### SOON

| id | Statement | Decided from | floor | how | Agree / Change / Remove |
|---|---|---|---|---|---|
| S1 | Tooth pain or sensitivity | SDCEP 2026 Pain pathway (analgesic controlled the pain, or not yet taken -> Non-urgent Care: Dental); NHS England 2025 §3.4 (mild or moderate pain that responds to pain relief). |  | checklist / photo | |
| S2 | A possible cavity seen in the photo | project owner, 22 Sep 2026 (decision 6) (photo-only finding with no symptoms: SOON). OUR CALL - no source sets this: no guideline gives a time frame for a symptom-free finding. |  | checklist / photo | |
| S3 | A broken, chipped, loose or lost filling, crown or tooth | NHS England 2025 §3.4 (fractured, loose or displaced fillings; loose or displaced crowns); SDCEP 2026 Trauma pathway (fracture involving dentine -> Non-urgent); SDCEP 2007 §2.1.3. |  | checklist / photo | |

### ROUTINE

| id | Statement | Decided from | floor | how | Agree / Change / Remove |
|---|---|---|---|---|---|
| R1 | A tooth appears to be missing in the photo | project owner, 22 Sep 2026 (decision 7) (missing tooth, no symptoms: ROUTINE). OUR CALL - no source sets this. |  | checklist / photo | |

## 3. Questions the patient is asked

Checklist rows are a Yes/No form, all rows at once. Chat rows are answered in
their own words. Nothing here names a drug or a dose.

| id | Input | Question as the patient sees it | Agree / Change |
|---|---|---|---|
| Q1 | yesno_checklist A | Are you having any difficulty breathing or swallowing? | |
| Q2 | yesno_checklist A | Do you have any chest pain, or do you feel short of breath? | |
| Q3 | yesno_checklist A | Is there any swelling in your face, jaw or gums? | |
| Q4 | yesno_checklist A | Do you have a fever or a high temperature? | |
| Q5 | yesno_checklist A | Do you feel very unwell in yourself, for example shivery, faint or unusually tired? | |
| Q6 | yesno_checklist A | Have you recently had a knock, fall or other injury to your mouth, teeth or face? | |
| Q7 | yesno_checklist A | Is there any bleeding in your mouth that does not stop when you press on it? | |
| Q8 | yesno_checklist A | In the last few days, have you taken more pain relief than the packet says is safe? | |
| Q9 | yesno_checklist A | Do you have any pain or discomfort in your teeth or gums at the moment? | |
| Q19 | yesno_checklist A | Do you have a mouth ulcer, sore or lump that has lasted more than 3 weeks? | |
| Q20 | yesno_checklist A | Do you have a filling, crown or tooth that has broken, chipped, come loose or come out, and has not been fixed yet? | |
| Q21 | yesno_checklist A | Have you noticed pus, a pimple-like bump on the gum, or a salty or bad-tasting fluid coming from around a tooth? | |
| Q10 | chat | Have you taken any pain relief for it? If so, did it help? | |
| Q11 | chat | How bad is the pain? Is it mild, moderate, or so bad that it stops you sleeping or eating? | |
| Q12 | chat | What sets the pain off: cold, hot, sweet things, biting, or does it come on by itself? | |
| Q13 | yesno_checklist B (options: Yes / No / Not sure) | After the pain is set off, does it keep aching for more than about half a minute? | |
| Q14 | yesno_checklist B | Does the pain ever wake you up at night? | |
| Q15 | yesno_checklist B | Does it hurt when you bite down or press on the tooth? | |
| Q16 | yesno_checklist B | Have you had a tooth taken out in the last two weeks? | |
| Q17 | chat | Where is the pain: upper or lower, left or right side, or at the front? | |
| Q18 | chat | How long have you had this pain? | |

## 4. Fixed text shown to every patient

| Where | Text | Agree / Change |
|---|---|---|
| Limitations line 1, shown with every result | These photos show the biting surfaces only. They cannot show the sides between your teeth. | |
| Limitations line 2, shown with every result | They cannot show anything under the gum or inside a tooth. | |
| Limitations line 3, shown with every result | A cavity can be there even when the photos show nothing. | |
| Safety net, on every result | If you develop swelling, a fever, bleeding that will not stop, or trouble breathing or swallowing, go to a hospital as soon as possible. | |
| disclaimer | This is an AI screening tool, not an examination by a dentist. It cannot diagnose any condition. If you are worried, contact a dentist. | |
| routine_advice | Brush twice a day with fluoride toothpaste, cut down on sugary food and drinks, and see a dentist for regular check-ups. | |
| photo_finding_phrase | Based on the image, there is an indication of tooth decay on: | |
| Shown above each Yes/No checklist | Please answer every row - nothing is filled in for you. Answer what is true right now; you can describe anything else in your own words afterwards. | |
| Answer buttons | Yes / No / Not sure | |
| Re-ask, when a chat answer is unclear | Sorry, I need a clearer answer to keep you safe. {question} | |

## 5. Sign-off

Nothing in the product may be described as reviewed until this is signed.
Only you may set `review_status`; research-pm will not.

- [ ] I have reviewed the levels, criteria, questions and fixed text above.
- [ ] Changes required are written in this form.
- Name, registration number, date:

_________________________________________________
