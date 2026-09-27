# Abstract and Introduction — draft for the master's dissertation

Draft, 2026-09-27. Numbers come from `docs/reports/system-report-2026-09-26.md`
on branch `llm-triage-wave2` (protocol v0.2, held-out Test 5). References are
numbered in Vancouver style; see the list at the end and the verification
notes below it.

---

## Abstract

**Background.** Oral diseases affect an estimated 3.5 billion people, and
untreated dental caries is the most common health condition worldwide [1].
Deep learning can now locate and number teeth in ordinary intraoral
photographs with high accuracy [2], and can detect visible lesions such as
caries with promising results [3,4]. A photograph, however, captures only
what is visible. Pain, its severity and triggers, fever, feeling unwell or a
recent injury cannot be seen, yet these are what dental triage guidelines use
to decide how soon a patient must be seen [5,6]. Patients also need their
result explained in plain language. Large language models (LLMs) can hold
such a conversation, but they can produce fluent, wrong statements [7,8] and
have performed inconsistently when asked to triage [9].

**Aim.** To design and evaluate a locally run dental screening assistant that
combines what a photo can show with what only the patient can tell. The
urgency decision stays auditable and safe, and is not left to the language
model.

**Methods.** Two occlusal photographs are processed by SegmentAnyTooth, for
tooth segmentation and FDI numbering [2], and by a YOLOv8 caries detector
applied to each tooth crop. A short structured interview (a Yes/No red-flag
checklist and five free-text questions) is controlled by deterministic code.
A quantised open-weight LLM (Qwen3-14B, Q4_K_M) [10] extracts each symptom
only together with the patient's verbatim words, and code verifies every
quote against the transcript. Urgency (EMERGENCY, URGENT within 24 hours,
SOON within 7 days, ROUTINE) follows a 21-criterion protocol encoded from
the SDCEP and NHS England guidance [5,6]. Red flags trigger EMERGENCY
without any model call. The LLM proposes a level with cited criteria; code
checks every citation and may only raise the level. The LLM then explains
the result in plain English, grounded in a retrieved knowledge base [11]
and checked by code guardrails. The whole system runs on one consumer PC
(12 GB GPU), so no patient data leaves the machine. We pre-registered a
held-out evaluation on 200 guideline-derived vignettes. Their patient text
was written by a different model family and blind-checked by a third.

**Results.** Segmentation found a median of 12 teeth per photograph. The
caries detector identified 29% of carious photographs at the deployed
threshold (62% at a lower threshold). On the held-out set, the final urgency
level under-triaged 0 of 200 cases (95% CI 0–1.8%), with weighted κ = 1.000
against the guideline-derived keys. The LLM's own proposals under-triaged
19.4%, which shows that the safety came from the code guards and not from
the model. Symptom extraction reached 92.6–97.0% field accuracy on blind
dialogue sets. No explanation invented or contradicted a finding (0/60).

**Conclusions.** Computer vision and conversation are complementary in
dental screening: the photo shows what the patient cannot describe, and the
interview captures what no photo can show. An architecture in which the LLM
interviews and explains, while deterministic code guarantees the urgency
decision, reached zero under-triage against the guideline as encoded. The
system is a screening aid, not a diagnosis. Review by dentists, a stronger
caries detector and evaluation on real patients remain necessary before any
clinical use.

**Keywords:** dental caries; teledentistry; triage; computer vision; large
language models; patient safety; intraoral photographs

---

## Chapter 1. Introduction

### 1.1 Background

Oral diseases are among the most widespread conditions in the world. The
World Health Organization's *Global Oral Health Status Report* estimates
that almost half of the world's population, about 3.5 billion people, is
affected. Untreated caries of the permanent teeth alone accounts for around
2 billion cases, and three quarters of those affected live in middle-income
countries [1]. Caries is painless in its early stages and becomes harder and
more expensive to treat the longer it is left. By the time pain drives a
patient to seek help, the problem may already need more invasive care.

At that point the patient faces a second difficulty. Most people cannot tell
whether a dental problem needs attention today, within the week, or at the
next routine check-up. Clinical guidance for exactly this decision exists.
The Scottish Dental Clinical Effectiveness Programme (SDCEP) guidance on the
management of acute dental problems, which NHS England has adopted, sorts
patients into emergency, urgent (within 24 hours), non-urgent (within 7 days)
and self-care categories [5,6]. Applying it, however, needs a trained person
to ask the right questions and interpret the answers. Teledentistry has
shown that remote assessment is feasible and reasonably accurate for
referral decisions [12], but it still depends on a clinician at the other
end.

### 1.2 What computer vision can see

Advances in deep learning have made automated analysis of dental images
practical. For intraoral photographs, which a patient can take with a
consumer camera or phone, two capabilities matter.

The first is **finding and identifying teeth**. SegmentAnyTooth, an
open-source framework trained on 5,000 annotated intraoral photographs,
segments and numbers teeth in FDI notation. It reports mean Dice
coefficients of 0.983 on upper and 0.973 on lower occlusal views [2].

The second is **detecting visible disease**. Kühnisch et al. trained a
convolutional neural network on intraoral photographs and reached more than
90% agreement with expert caries assessment under ideal conditions [3].
Zhang et al. screened for caries in photographs taken with consumer cameras,
with an area under the curve of 85.7% and image-wise sensitivity of 81.9% at
a high-sensitivity operating point [4]. These results suggest that a
photograph can support a first, low-cost screen for visible problems, even
where no dentist is present.

### 1.3 What a photograph cannot show

A photograph records only what is visible on the surfaces it captures. An
occlusal photo does not show the surfaces between teeth, anything below the
gum line, or the inside of a tooth. More importantly, the information that
most often decides **how urgently** a patient needs care is not visual at
all.

SDCEP's decision pathways turn on questions such as these [5]:
- Is the patient having difficulty breathing or swallowing?
- Do they have a fever or feel systemically unwell?
- Has there been recent trauma?
- Is the pain severe enough to stop them sleeping or eating?
- Does it linger after a stimulus, or wake them at night?
- Has pain relief helped?

A small, visible cavity in a patient with a fever and spreading swelling is
an emergency. A similar cavity with no symptoms can wait for a routine
appointment. The image alone cannot tell these two patients apart; only the
patient can. A screening tool that relies on vision alone therefore risks
under-triage, the error that harms patients: telling someone to wait when
they need care now.

### 1.4 Why language, and why language models are not enough

Collecting symptoms and explaining a result both require natural language.
Patients describe their problems in their own words ("it keeps aching for a
minute or so after", "I can't sleep because of it"), and they need the
outcome explained in words they understand. Earlier online symptom checkers
relied on fixed decision trees. They listed the correct diagnosis first in
only about a third of cases, and their triage advice was generally risk
averse [13].

Large language models (LLMs) make open-ended conversation possible. They can
answer free-text questions across medical domains without task-specific
training [7]. They also bring well-documented risks. They can generate
fluent statements that are not supported by their input, a failure known as
hallucination [8]. When used directly for triage, their accuracy has varied
with prompt wording, and has fallen short of what clinical use requires: in
one study, GPT-4 reached 63.9% accuracy in simulated disaster triage, with
poor repeatability [9]. For a patient-facing screening tool, a model that
occasionally invents a symptom, a tooth or a lower urgency level is not
acceptable.

### 1.5 Research gap

Prior work tends to treat these problems separately:
- vision models that detect caries from photographs but say nothing about
  urgency [3,4];
- symptom checkers and teledentistry services that assess urgency without
  image analysis, or with a human clinician in the loop [12,13];
- LLM chatbots that converse fluently but whose triage decisions are
  unreliable and hard to audit [7,9].

Few systems combine image findings with patient-reported symptoms in a
single screening pathway. Fewer still keep the urgency decision
**deterministic, traceable to a published guideline, and safe by
construction**, while using an LLM only where language is actually needed.
Most LLM systems in healthcare also depend on cloud services, which raises
privacy concerns. Open-weight models that run on consumer hardware [10]
make a fully local design possible.

### 1.6 Aim and research questions

This dissertation aims to design, build and evaluate a locally run dental
screening assistant. The assistant takes two occlusal photographs and a
short patient interview, and returns in plain English:
- which teeth were found and which may show decay;
- how soon the patient should see a dentist;
- why.

It is framed as a screening aid, not a diagnostic tool.

Each research question below names the data set, the measure and the
comparison used to answer it, so that it can be answered directly from the
experiments in Chapters 4 and 5.

**RQ1 — What can the photo show?**
On a public set of labelled intraoral photographs, how many teeth does
SegmentAnyTooth identify per occlusal photo? What proportion of carious
photos does a per-tooth YOLOv8 caries detector flag at confidence
thresholds of 0.50 and 0.25, and how many healthy photos does it flag
wrongly?
- *Data:* Mendeley carious/non-carious photos (n = 4,929, photo-level
  labels).
- *Measures:* teeth per photo (median); sensitivity and false-positive rate
  at each threshold.

**RQ2 — Can the model capture what the photo cannot?**
When a locally run LLM extracts symptoms from patients' free-text answers,
and each value must be backed by a verbatim quote checked in code:
- what proportion of symptom fields does it extract correctly?
- how often does it fill in a field the patient never answered?
- *Data:* three blind sets of scripted dialogues (19, 20 and 24 dialogues;
  5 fields each), not seen during development.
- *Measures:* field-level accuracy with 95% CI; number of guessed values.

**RQ3 — Who should decide urgency?** *(main question)*
On held-out vignettes with guideline-derived answer keys, how often does
each of the following assign a lower urgency level than the key
(under-triage)?
- the final, code-guarded result;
- the LLM's own proposal;
- a rules-only baseline.
- *Data:* 200 held-out triage vignettes, written before the system was
  tested, and scored once.
- *Measures:* under-triage rate with 95% CI; weighted κ against the keys.
- *Success criterion, fixed in advance:* 0 under-triage and κ ≥ 0.8 for the
  final result.

**RQ4 — Can the result be explained safely?**
When the LLM explains the result in plain English, how often does the
explanation do any of the following?
- name a tooth that is not in the findings;
- leave out a flagged tooth;
- contradict or misstate the urgency level.
- *Data:* 60 generated cases and 8 hand-written cases.
- *Measures:* count of each error type, checked in code.

**Scope.** These questions measure agreement with the SDCEP guideline as
encoded in the project's protocol, and faithfulness to the system's own
findings. They do not ask whether the system is clinically correct for real
patients. Answering that would need dentist labels and real patient
photographs, which are outside the scope of this dissertation (Chapter 6).

### 1.7 Contributions

1. **Vision and conversation combined.** A screening pipeline combining
   image findings (what a photo shows) with a structured interview (what
   only the patient can tell), running entirely on one consumer PC.
2. **An "LLM proposes, code guards" design.**
   - Red flags bypass the model entirely.
   - Every urgency proposal must cite written criteria, and code verifies
     each citation.
   - Code can raise the level but never lower it.
   - Every extracted symptom must be supported by the patient's verbatim
     words.
3. **A 21-criterion triage protocol** encoded from SDCEP and NHS England
   guidance. Each criterion is traced to its source, with every deliberate
   departure documented for clinical review.
4. **A pre-registered evaluation method** for LLM triage:
   - held-out, guideline-derived answer keys;
   - synthetic patient text, written by one model family and blind-checked
     by another;
   - separate measurement of the model's own proposals and of the final,
     code-guarded result.

### 1.8 Structure of the dissertation

- **Chapter 2** reviews the literature on caries epidemiology, dental triage
  guidance, computer vision for dental images, symptom checkers and LLMs in
  healthcare.
- **Chapter 3** describes the system architecture and the triage protocol.
- **Chapter 4** presents the evaluation methods.
- **Chapter 5** reports the results.
- **Chapter 6** discusses limitations, in particular the absence of dentist
  validation and the weakness of the caries detector, and outlines future
  work.

---

## References

1. World Health Organization. *Global oral health status report: towards
   universal health coverage for oral health by 2030.* Geneva: WHO; 2022.
2. Nguyen KD, Hoang HT, Doan TPH, Dao KQ, Wang DH, Hsu ML. SegmentAnyTooth:
   an open-source deep learning framework for tooth enumeration and
   segmentation in intraoral photos. *J Dent Sci.* 2025;20(2):1110–1117.
   doi:10.1016/j.jds.2025.01.003
3. Kühnisch J, Meyer O, Hesenius M, Hickel R, Gruhn V. Caries detection on
   intraoral images using artificial intelligence. *J Dent Res.*
   2022;101(2):158–165. doi:10.1177/00220345211032524
4. Zhang X, Liang Y, Li W, Liu C, Gu D, Sun W, et al. Development and
   evaluation of deep learning for screening dental caries from oral
   photographs. *Oral Dis.* 2022;28(1):173–181. doi:10.1111/odi.13735
5. Scottish Dental Clinical Effectiveness Programme (SDCEP). *Management of
   Acute Dental Problems.* 2nd ed. Dundee: NHS Education for Scotland; 2026.
   Available from: https://www.acutedentalproblems.sdcep.org.uk/
6. NHS England. *Clinical guidance: unscheduled urgent and non-urgent dental
   care.* Version 1.0. London: NHS England; May 2025 (updated October 2025).
7. Thirunavukarasu AJ, Ting DSJ, Elangovan K, Gutierrez L, Tan TF, Ting DSW.
   Large language models in medicine. *Nat Med.* 2023;29(8):1930–1940.
   doi:10.1038/s41591-023-02448-8
8. Ji Z, Lee N, Frieske R, Yu T, Su D, Xu Y, et al. Survey of hallucination
   in natural language generation. *ACM Comput Surv.* 2023;55(12):248.
   doi:10.1145/3571730
9. Franc JM, Hertelendy AJ, Cheng L, Hata R, Verde M. Accuracy of a
   commercial large language model (ChatGPT) to perform disaster triage of
   simulated patients using the Simple Triage and Rapid Treatment (START)
   protocol: gage repeatability and reproducibility study. *J Med Internet
   Res.* 2024;26:e55648. doi:10.2196/55648
10. Qwen Team. Qwen3 technical report. arXiv:2505.09388 [Preprint]. 2025.
11. Lewis P, Perez E, Piktus A, Petroni F, Karpukhin V, Goyal N, et al.
    Retrieval-augmented generation for knowledge-intensive NLP tasks. In:
    *Advances in Neural Information Processing Systems 33 (NeurIPS 2020).*
    2020. p. 9459–9474.
12. Estai M, Kanagasingam Y, Tennant M, Bunt S. A systematic review of the
    research evidence for the benefits of teledentistry. *J Telemed
    Telecare.* 2018;24(3):147–156.
13. Semigran HL, Linder JA, Gidengil C, Mehrotra A. Evaluation of symptom
    checkers for self diagnosis and triage: audit study. *BMJ.*
    2015;351:h3480. doi:10.1136/bmj.h3480

Further sources used by the system, to cite in Chapters 2–3: AAE Consensus
Conference, Recommended Diagnostic Terminology, *J Endod.*
2009;35(12):1634; Ultralytics YOLOv8 (software, 2023); the Mendeley
carious/non-carious intraoral photo dataset; Kirillov et al., Segment
Anything, ICCV 2023.

### Verification notes (delete before submission)

- **Checked by web search on 2026-09-27:** title, authors, journal, year,
  and volume/pages where shown, for refs 1, 2, 3, 4, 7, 8, 9, 10, 11 and 13.
  The quoted numbers were also checked: WHO 3.5 billion and 2 billion;
  SegmentAnyTooth Dice 0.983/0.973; Kühnisch >90%; Zhang AUC 85.65% and
  sensitivity 81.90%; Franc 63.9%.
- **Check against the full text before submission:**
  - ref 4: author list after the fourth author;
  - ref 7: issue number (8);
  - ref 9: author list and DOI;
  - ref 11: page range;
  - ref 12: issue (3);
  - ref 13: article number h3480 and DOI.
- **Refs 5 and 6** are taken from the project's own records
  (`llm/protocol/triage_protocol.yaml`, `docs/reports/system-report-2026-09-26.md`).
  They could not be re-checked online on 2026-09-26, so confirm the edition,
  date and publisher on the SDCEP and NHS England sites.
- **The results rest on the guideline as encoded.** The answer keys were
  written from the same protocol the code applies, and no dentist has
  labelled any case. Keep the phrase "against the guideline as encoded" in
  the abstract, and state this in Chapter 6.
