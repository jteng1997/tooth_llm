# Form C — open clinical questions

Twelve questions no guideline settles for us. Each says what the system does
today, why, and what we know. Please mark **Keep / Change**, and write the
change. If a question needs the project owner rather than you, say so.

---

## C1. Any swelling counts as an emergency

**Today:** any swelling of face, jaw or gums forces EMERGENCY in code, before
the model sees anything. Same for any recent injury to the mouth.

**Why:** the project owner chose the safe direction while the tool is
unproven.

**What SDCEP does:** grades it. Rapidly increasing, airway or eye involvement,
or systemically unwell → emergency; slowly increasing, hot or firm → urgent
(24 h); localised and not spreading → non-urgent (7 days). Injury is graded
the same way, from self-care for a chipped enamel edge to emergency for a
knocked-out adult tooth.

**Cost of keeping it:** most people with a gum boil or a chipped tooth are
told to go to hospital today. That is safe and wrong, and enough false alarms
will teach people to ignore the tool.

Keep / Change: ................................................

## C2. Lingering or night pain no longer changes the level; pain relief does

**Today (protocol v0.3, the project owner's provisional decisions of
2026-09-26):**
- For tooth pain, the pain relief answer alone sets the level:
  - pain relief not helped → within 24 hours;
  - pain relief helped → within 7 days;
  - pain relief not yet tried → within 7 days.
- Pain that keeps aching for more than about half a minute, wakes the
  patient, or starts on its own is still asked about. It no longer changes
  the level. Until 2026-09-26 it was "within 24 hours" whenever present.

**What SDCEP does:** the pain pathway asks "Has analgesic been taken?" and
"Has analgesic controlled the pain?". Only failed pain relief leads to urgent
care. Lingering, night and spontaneous pain are pulpitis symptoms, not steps
on the pathway.

**Questions for you:**
- Should lingering, night or spontaneous pain raise the level on its own,
  for example to 24 hours when pain relief has not been tried?
- If they should matter, is "about half a minute" the right line? It is a
  convention of ours; the AAE terminology says "lingering thermal pain" with
  no duration at all.

Keep / Change: ................................................

## C3. A possible cavity in the photo with no symptoms → within 7 days

**Today:** SOON (7 days). No guideline sets a window for a symptom-free
finding; the ADA's list calls asymptomatic decay non-urgent.

**Relevant:** at the threshold in use the detector flags 3% of healthy photos
and misses 71% of carious ones. So this level fires on a fair number of people
with nothing wrong, and stays silent for most people with something wrong.

Keep / Change: ................................................

## C4. A missing tooth with no symptoms → routine

**Today:** ROUTINE, mentioned at the next check-up. The rule ignores wisdom
teeth. It cannot know about children, mixed dentition, or a tooth extracted
years ago, because we do not ask about age or dental history.

Keep / Change (including whether to ask about age): .............

## C5. A cavity in the photo plus any tooth pain → within 24 hours

**Today:** URGENT. This was research-pm's conservative choice so that the new
system is never less urgent than the old rules, not a guideline requirement.
SDCEP would give 7 days when pain relief works.

Keep / Change: ................................................

## C6. Symptoms we never ask about

Each of these appeared repeatedly in real patient messages and has an SDCEP
pathway; none has a question in our form. Each extra question costs the
patient effort, so this is a trade-off, not a free addition.

| Symptom | SDCEP | Add a question? |
|---|---|---|
| Cannot open the mouth (trismus) | cardinal sign of spreading infection; emergency with swelling | |
| Double vision or visual disturbance with jaw/face pain | emergency medical (giant cell arteritis) | |
| Hoarse or muffled voice | listed with airway compromise | |
| Ulcer, sore or lump lasting over 3 weeks | urgent dental, possible cancer referral | **already added**, checklist row Q19 |

## C7. "Recent" extraction means the last two weeks

**Today:** the question asks whether a tooth was taken out "in the last two
weeks", and if so, pain after it is URGENT. SDCEP says "recently" without a
number; the two weeks is ours.

Keep / Change: ................................................

## C8. Detector threshold

**Today:** confidence 0.50. Measured on 4,929 labelled photos:

| Threshold | Carious photos caught | Healthy photos wrongly flagged |
|---|---|---|
| 0.50 | 29% | 3% |
| 0.25 | 62% | 14% |

A screening tool usually prefers sensitivity. Neither setting is good. Which
error would you rather the prototype made, and does either make the tool worth
using at all?

Keep 0.50 / Change to ......... / Neither is usable because ...........

**Related wording:** the third limitations line says "A cavity can be there
even when the photos show nothing." That is our plain-English rendering of the
miss rate above. Is it strong enough, or should the result say outright that a
clear photo does not mean healthy teeth?

## C9. Wording shown to every patient

Approved provisionally by the project owner; your view is on the clinical
safety of the words, not the style.

| Where | Text |
|---|---|
| Emergency screen | "This may be an emergency. Please go to a hospital as soon as possible." (no phone number, no separate dental route) |
| Safety net on every result | "If you develop swelling, a fever, bleeding that will not stop, or trouble breathing or swallowing, go to a hospital as soon as possible." |
| Disclaimer | "This is an AI screening tool, not an examination by a dentist. It cannot diagnose any condition. If you are worried, contact a dentist." |
| Finding wording | "Based on the image, there is an indication of tooth decay on: ..." |
| Above each Yes/No checklist | "Please answer every row - nothing is filled in for you. Answer what is true right now; you can describe anything else in your own words afterwards." |
| Limitations, with every result | These photos show the biting surfaces only. They cannot show the sides between your teeth. / They cannot show anything under the gum or inside a tooth. / A cavity can be there even when the photos show nothing. |
| Routine advice | "Brush twice a day with fluoride toothpaste, cut down on sugary food and drinks, and see a dentist for regular check-ups." |

Keep / Change: ................................................

## C10. The one sentence we may say about pain relief

**Today:** the assistant is allowed to mention over-the-counter pain relief
only in general terms, and never a drug name or a dose. What "general terms"
means is not written down anywhere, so the guardrail has to work by listing
forbidden words — which misses garbled names and risks blocking safe advice
(llm-dev measured both, 2026-09-23).

**What would fix it:** one approved sentence in the reviewed knowledge file,
which the assistant may use verbatim and which the check can match exactly.
Something of this shape, for you to accept or rewrite:

> "Ordinary pain relief from a pharmacy, taken as the packet says, may help
> until you are seen."

- Is that sentence safe to show every patient, including children's carers and
  people who cannot take common painkillers?
- Should it name no medicine at all, as written, or should it say "ask the
  pharmacist what is suitable for you"?
- Should the assistant say anything about pain relief at all?

Approved wording: ..............................................

## C11. Broken fillings and pus: two new checklist rows (protocol v0.2)

**Why they were added:** a patient with no pain skipped every question after
the first checklist, so a broken filling without pain (S3) or pus without pain
(U8) could never be reported. Protocol v0.2 adds two Yes/No rows to the first
checklist:

- Q20: "Do you have a filling, crown or tooth that has broken, chipped, come
  loose or come out, and has not been fixed yet?" → within 7 days.
- Q21: "Have you noticed pus, a pimple-like bump on the gum, or a salty or
  bad-tasting fluid coming from around a tooth?" → within 24 hours.

**What we would like you to decide:**
- **Pus without pain.** We send every Yes on Q21 to "within 24 hours", with or
  without pain, following SDCEP's acute apical abscess advice. A painless
  draining sinus may be a chronic abscess, which may not need 24 hours. The
  project owner kept "within 24 hours" for now (2026-09-23), as deliberate
  over-triage until you decide. Should pus without pain be within 24 hours,
  within 7 days, or something else?
- **Bad taste alone.** Q21 includes "a salty or bad-tasting fluid". Does that
  catch too many people with ordinary bad breath or trapped food, or is it
  worth keeping for the people it helps?
- **A broken tooth with pain.** S3 is "within 7 days"; pain questions then
  decide whether it is sooner. Is anything about a broken tooth itself (sharp
  edge cutting the tongue, a large piece lost) more urgent than 7 days?
- Are the two questions worded so a patient answers them correctly?

Keep / Change: ................................................

## C12. Tooth pain, but we do not know whether pain relief helped

**Today (protocol v0.3, provisional; the project owner delegated this, and
the project lead ruled it on 2026-09-26):**
- The patient has tooth pain, but gives no usable answer to "Have you taken
  any pain relief for it? If so, did it help?", even after one re-ask.
  Examples: "not sure if it made a difference", or no answer at all.
- We then send them to **within 24 hours**, however mild the pain.

**Why:** both of SDCEP's 7-day routes need a known answer: relief not taken,
or relief that controlled the pain. SDCEP has no route for "unknown". Our rule
is that a missing answer is never treated as reassuring.

**Cost:** someone with a mild twinge from sweet food, who answers the relief
question vaguely, is told 24 hours. In our 100 practice cases, 1 mild case
moved from 7 days to 24 hours this way (3 before the ruling below).

**A borderline answer:** "I don't know what to take for it." The project
lead's provisional ruling (2026-09-26) reads this as relief **not tried**,
so the answer is 7 days. The patient is telling us they have taken nothing,
which is an answer, not a blank. "I took something but I'm not sure if it
helped" stays *unknown*, so the answer is 24 hours.

**Questions for you:**
- Should unknown pain relief with pain be within 24 hours, within 7 days, or
  depend on how bad the pain is?
- Do you agree that "I don't know what to take for it" means *not tried*?

Keep / Change: ................................................

---

## Anything we have not asked about

If something in this prototype worries you that no form covers, write it here.
That is the most valuable box on the page.

....................................................................

Name, registration number, date: ....................................
