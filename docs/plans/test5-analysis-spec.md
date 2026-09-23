# Test 5 analysis spec (pre-registered)

Status: **pre-registered 2026-09-23 by research-pm, before any held-out run.**
Agreed with the lead. Anything decided after seeing held-out numbers is a
post-hoc choice and must be labelled as one in the report.

Implementation is qa-engineer's (`src/check_triage.py`); this file fixes what
is measured, how it is reported and what it may change. The point of writing
it first is simple: with one held-out set and a target of zero under-triage,
it is otherwise too easy to pick the flattering cut after the fact.

---

## 1. Data

| Set | File | Size | Who may see it |
|---|---|---|---|
| Held-out, triage-level | `labels/heldout/triage_heldout_keys.json` | 200 (EMERGENCY 45, URGENT 55, SOON 55, ROUTINE 45; 84 boundary) | qa-engineer, to run. Never llm-dev. |
| Held-out, end-to-end | `labels/heldout/e2e_keys.json` | 60 (15 per level) | same |
| Dev | qa-engineer + llm-dev's set | 100 | anyone; all tuning happens here |

The key is the level the protocol gives, computed from the criteria and
checked against the loader (0 mismatches at v0.1). **It is not a dentist's
label.** Every report of these numbers carries the sentence: *"agreement with
SDCEP as encoded in protocol v0.1, including the user's 2026-09-22 decisions;
not a clinical validation."*

**Scored once per configuration.** A configuration = model + prompt + protocol
version + composition options. Each held-out scoring is logged in
`docs/decisions.md` (date, configuration, who ran it) whether or not the
result is used. Re-running the same configuration after a code fix is allowed
and must be logged as a re-run.

## 2. Systems compared, on the same cases

1. `final` — `assessment.urgency` as the patient would see it (LLM + floor +
   protocol check + retake rule).
2. `llm_proposed` — the model's own level before any code override. This is
   what says whether the LLM adds anything.
3. `rules` — `rules.assess()` shadow baseline, unchanged.
4. `protocol_check` — code's own level from the structured criteria.
5. `key` — the answer key.

Report all four against the key, and `final` against `rules` head to head.

## 3. Metrics

Levels are ordered EMERGENCY > URGENT > SOON > ROUTINE. RETAKE is excluded
from every level metric and reported separately as a photo-quality count; no
held-out key has RETAKE as its level.

**Primary — under-triage.** A case is under-triaged when the system's level is
less urgent than the key. Report the count and rate with an exact
(Clopper-Pearson) 95% CI, for `final` and for `llm_proposed`. Target 0.
With 0/200 the upper bound is 1.5%; state that bound every time rather than
writing "no under-triage".

Also report, as pre-declared sub-counts:
- severe under-triage: two or more levels below the key;
- missed EMERGENCY: key EMERGENCY, system anything else (this is the one that
  can hurt someone);
- under-triage among boundary cases vs the rest.

**RETAKE.** RETAKE is not a level, but a system can emit it, so the rule is
fixed here (added 2026-09-23 after the dry run, §8): with an EMERGENCY or
URGENT key, a RETAKE counts as **under-triage and as severe** — asking for new
photos when the patient needs care today delays it, and names no urgency at
all. With a SOON or ROUTINE key it is neither under- nor over-triage: the case
is excluded from the level metrics and the exclusions are reported as a count.
Without this rule a system could dodge the primary endpoint by asking for
photos.

**Paired tests** are computed only on cases scored for both systems (the two
may exclude different RETAKE cases).

**Secondary.**
- Over-triage rate, same method.
- Exact agreement.
- Linearly weighted κ (weights 1 − |i − j| / 3), with a percentile bootstrap
  95% CI, 2,000 resamples, seed 20260923.
- Per-level recall and precision, as a 4×4 confusion matrix.

**Head-to-head (`final` vs `rules`).** Exact McNemar on the discordant pairs
for under-triage, two-sided, α = 0.05. If fewer than 10 discordant pairs,
report the counts and the exact CI only and say the comparison is
underpowered; do not report a p-value alone.

**Operational.** Valid-output rate, retry rate, fallback-to-rules rate (bar:
≤ 1%), the `decided_by` distribution (how often the LLM's own level decided
the outcome), latency p50/p95 for the triage call, and stability: each of 20
pre-chosen held-out cases run 3 times plus 2 paraphrases, reporting the share
with an identical level.

**End-to-end set.** Same metrics, plus error attribution for every case that
misses the key, into exactly one bucket:
1. interview — a needed question was never put;
2. extraction — the field came back null or wrong although the patient said
   it;
3. triage — fields correct, level wrong;
4. protocol gap — the key itself needed a criterion the protocol lacks.

Attribution is mine, from the logs, and I will have seen which system produced
the case, so it is not blind. Buckets 1–3 are counted against the system;
bucket 4 is counted against the protocol and sent to the dentist queue.

## 3a. The code ceiling, and what is left for the model

`protocol_check` against the key measures what code alone achieves. Everything
above that line is the LLM's contribution; everything below is a code bug.
Report the gap explicitly, because on triage-level cases it is small by
construction.

Dry-run numbers, `rules.py` and the protocol check against the 200 held-out
keys, measured 2026-09-23 with no model involved (`runs/review/dryrun_test5.py`):

| | under-triage | severe | missed EMERGENCY | over-triage | exact | weighted κ |
|---|---|---|---|---|---|---|
| rules.py (old baseline) | 51/200 = 25.5% (CI 19.6–32.1) | 31 | 25 | 10/200 = 5.0% | 69.5% | 0.595 (CI 0.50–0.68) |
| protocol check (code only) | 8/200 = 4.0% (CI 1.7–7.7) | 0 | 0 | 0/200 | 96.0% | 0.967 (CI 0.94–0.99) |

Both figures are explained entirely by what each system cannot see:

- **rules.py** misses the material added since it was written: the four
  extended floor flags (uncontrolled bleeding 5, feeling very unwell 5, fever
  5, pain-relief overdose 5) and chest pain 5 — that is all 25 missed
  emergencies — plus severe pain (7), pain after a recent extraction (5),
  persistent ulcer (3), pus (3), broken filling (5) and unusable photos (3).
  It is the correct baseline and it is *expected* to lose; the paper should say
  so rather than present it as a fair contest.
- **the protocol check** misses exactly the 8 narrative cases: 5 broken
  filling or crown without pain (S3), 3 pus or bad taste (U8). Nothing else.

**So on the triage-level held-out set the LLM can only change the outcome on
those 8 cases (4%), plus any case where it proposes something code then has to
override.** That is the honest size of the contribution this set can measure,
it was known before the run, and the report must state it next to any headline
agreement figure. The end-to-end set is where more is at stake, because the
interview and extraction can fail there.

## 4. Reporting template

One table per system: n, under-triage (count, rate, CI), severe under-triage,
missed EMERGENCY, over-triage, exact agreement, weighted κ (CI). Then the
operational table, then the attribution table for the end-to-end set. Every
table states n. No rate is reported without its denominator.

Alongside, three sentences that must appear:
1. the "SDCEP as encoded" caveat above;
2. "The vignettes assume the photo findings are correct; the detector catches
   about 29% of carious photos at the current threshold, so end-to-end
   accuracy on real patients is not measured here";
3. whichever of the caveats in §6 applies.

## 5. What the numbers may change (decided now)

- **Under-triage on held-out > 0:** classify by §3's buckets. Protocol gaps go
  to the dentist queue and the protocol, not to prompt tuning. Only
  triage-bucket errors count towards the fine-tuning trigger in the design §6.
- **`final` ≥ `rules` on under-triage, or no κ gain over `rules`:** that is the
  finding and it is reported as the headline. No extra held-out runs to find a
  better number.
- **Fallback rate > 1%:** the configuration fails on reliability regardless of
  its accuracy.
- **κ (key vs `final`) below the user's bar of 0.8:** the protocol or the
  prompt is revised on dev, and the held-out set is re-scored once, as a new
  configuration.
- Prompt or protocol changes made after a held-out run make every later run a
  new configuration; earlier numbers stay in the report.

## 6. Declared limits

- One key author (me) and no dentist: agreement with the protocol, not with
  care.
- Four of the protocol's levels rest on the user's decisions rather than a
  source (any swelling, any trauma, lingering or night pain, photo-only
  finding). Agreement on those cases measures obedience to a house rule.
- Structured criteria are decided by code, so on triage-level cases the
  `final` level is right by construction wherever a structured criterion
  holds. The informative parts are `llm_proposed`, the two narrative criteria,
  the injection cases and the end-to-end set.
- Synthetic patient words, written by a local model from my keys: phrasing is
  ours, not patients'. The P10 message set (§3.3 of the phase 1–2 plan) is the
  only real-phrasing check, and its flag mix is skewed.
- No exclusions after scoring. The only pre-declared exclusion is RETAKE from
  level metrics.

## 7. Secondary analysis: silver labels

**Closed 2026-09-23: the rubric missed both bars** (κ 0.269 blind, EMERGENCY
precision 8/40 = 20%), so there is no silver-label analysis. The failure is
reported as a negative result — see `docs/decisions.md` and plan §3.2. Nothing
in Test 5 depends on it.

## 8. Dry run, 2026-09-23

`runs/review/dryrun_test5.py` produced every table in this spec from the keys
and `rules.py`, with no model. Three things it changed:

1. **RETAKE had no scoring rule.** rules.py returned RETAKE on 3 held-out
   cases whose key is URGENT. §3 now fixes the rule.
2. **Paired tests need a common index set**, since two systems can exclude
   different cases.
3. **The code ceiling needed reporting** (§3a): without it, a 96% agreement
   figure would be read as the model's achievement.

The dry run is scratch, not the implementation; `src/check_triage.py` is
qa-engineer's and should reproduce these numbers on the same inputs as its
first sanity check.
