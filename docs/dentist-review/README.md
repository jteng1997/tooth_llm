# Dentist review packet

Prepared by research-pm, 2026-09-23. Nothing here has been reviewed by a
dentist yet; that is what this packet is for.

## What the tool is

A research prototype. A patient photographs their upper and lower biting
surfaces with a phone. Software finds the teeth, a detector flags possible
decay, the patient answers a short symptom form, and the system says **how
soon to see a dentist** and why. It never names a condition as a diagnosis,
never names a medicine or a dose, and never suggests a home procedure.

It runs entirely on one machine; no patient data leaves it. It has never been
used with a real patient, and it must not be until this review is done.

Two limits worth knowing before you read anything else:
- **The detector is weak.** On 4,929 labelled photos it catches 29% of the
  carious ones at the threshold we use (3% false alarms), or 62% at a lower
  threshold (14% false alarms). A "nothing found" result means very little.
- **Occlusal photos show biting surfaces only** — not between teeth, not below
  the gum, not soft tissue.

## What we need from you

| Form | What it asks | Time |
|---|---|---|
| `form-a-protocol.md` | Are the levels, time frames, criteria, questions and patient-facing wording clinically acceptable? | ~60–90 min |
| `form-b-vignettes.md` | Label short patient descriptions with how soon they should be seen, blind to what our system said | ~1 min each; 220 cases ≈ 4 h, and a 60-case subset is useful on its own |
| `form-c-open-questions.md` | Twelve decisions no guideline settles, which the project made provisionally | ~30 min |
| `form-d-knowledge.md` | 6 plain-language fact sheets (32 sections) that the explanations are built from: correct, and safely worded? | ~2 h |

Forms A and C are the blocking ones: until they are signed, every result the
system produces is marked draft and unreviewed.

## Ground rules we have set ourselves

1. **You decide clinical content.** The team prepares evidence; thresholds,
   wording and urgency are yours and the project owner's.
2. **Only you may mark anything reviewed.** No one on the team sets
   `review_status`, in the protocol or in the knowledge files.
3. **Label before you see our answers.** Form B is blind on purpose: if you
   see the system's output first, the comparison is worthless.
4. **Disagreement is the useful result.** If our protocol is wrong, the
   evaluation that follows is measuring the wrong thing, and we would rather
   find that now.

## What we have already checked, so you don't have to

- The levels and time frames come from SDCEP's *Management of Acute Dental
  Problems* (2nd edition, March 2026) and NHS England's 2025 unscheduled
  dental care guidance, both read in full by research-pm, plus SDCEP's 2007
  *Emergency Dental Care* guidance for the original timescales.
- Where a rule has no source, the form says so ("our call").
- The AAE 2009 terminology and ICCMS were read: neither gives urgency levels
  or time frames, so neither is used for timing.

Everything cited is listed in `docs/plans/phase1-2-plan.md` §1, with what was
read in full and what was not.
