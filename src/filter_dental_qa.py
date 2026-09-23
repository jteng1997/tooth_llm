"""P8: filter ChatDoctor-HealthCareMagic-100k and LiveQA TREC 2017 to dental QA.

    python src/filter_dental_qa.py                # filter, print counts, write outputs
    python src/filter_dental_qa.py --samples 5    # also print a few rows per drop reason

Plan: docs/plans/phase1-2-plan.md §3. Stages, each counted:

  0. load            ChatDoctor rows; LiveQA exploded to (question, answer) pairs
  1. dedupe          exact duplicate (question, answer) pairs dropped
  2. English         patient text AND answer must pass `is_english`
  3. topic           dental / oral / gum / jaw keywords on the patient text
  4. answer          drop the pair if the answer names a drug, a dose or a
                     definitive diagnosis. Rows are dropped, never edited.

Outputs (dataset/ is gitignored, so none of this is ever committed; neither
dataset declares a licence and ChatDoctor is academic-research-only):

  dataset/dental_qa/dental_topic.jsonl   stages 0-3 passed, with answer flags
                                         (the "dental subset": silver labels come
                                         from these answers, never shown to users)
  dataset/dental_qa/dental_clean.jsonl   stage 4 passed as well.
                                         NOT a fine-tuning target as it stands:
                                         research-pm's P9 audit found 12.5% of
                                         these answers (25/200, 95% CI 9-18%)
                                         still name a medicine, give a dose or
                                         state a diagnosis, several of them
                                         mangled by the dataset's own spelling
                                         correction, which no word list catches.
                                         It needs an LLM or human pass first.
  dataset/dental_qa/filter_counts.json   the counts printed below

Input files (downloaded by qa-engineer, 2026-09-22):
  dataset/chatdoctor-healthcaremagic-100k/train.jsonl  (converted from the HF
      parquet, sha256 8a7c2759...f04f8c; .venv has no pyarrow)
  dataset/liveqa-medical-trec2017/{TREC2017-LiveQA-Medical-Train1,-Train2,test}.jsonl

Deviations from the plan's keyword list, for precision (research-pm audits
precision and recall in P9): "filling", "crown" and "braces" need a tooth word
nearby, like "cavity", "extraction" and "abscess" already did; "you have
(a|an)" is matched but "you have to/been" is not. Everything else as written.

Changes after the P9 audit (2026-09-23, lead's instruction):
- topic: oral soft tissue added (tongue, palate, lip, "inside my mouth",
  canker sore, saliva). Recall was 7% of rejected mouth/face rows. Rows that
  match only here carry the tag `oral_soft_tissue`; "mouth" also counts as
  the nearby word for loose terms ("fillings ... side of my mouth").
- answers: a frequency only counts as a dose away from rinsing/brushing;
  a medicine named as a cause or an allergy is not advice; generic
  over-the-counter wording (mouthwash, anti-inflammatory, painkiller) is
  recorded as `generic_product` and no longer drops the row; "calcium" and
  "vitamin" are no longer drug names.
Topic precision was 76.5% at the audit, below the plan's 90% bar, so the LLM
topic stage is required before these rows carry any claim.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "dataset"
CHATDOCTOR = DATA / "chatdoctor-healthcaremagic-100k" / "train.jsonl"
LIVEQA = DATA / "liveqa-medical-trec2017"
OUT = DATA / "dental_qa"

# --- Stage 2: English -----------------------------------------------------
# No language-ID package in .venv; a script check plus a function-word check
# is enough to catch non-Latin script and romanised non-English (Hinglish,
# Indonesian), which are the two ways a row can be non-English here.

EN_FUNCTION_WORDS = set("""
a an the and or but if of to in on at for from with by about as into over after
before under between is are was were be been being am do does did have has had
i me my mine we our you your he him his she her it its they them their this that
these those what which who whom when where why how not no yes can could will would
should may might must shall there here so than then very just also too all any some
please thank thanks doctor sir madam hi hello dear
""".split())

# Function words of the romanised languages that actually occur in these
# rows (Hindi/Urdu, Indonesian/Malay) plus Spanish/Portuguese. Words that are
# also English ("me", "main", "par", "to") are left out on purpose.
FOREIGN_FUNCTION_WORDS = set("""
hai hain mein mai mera meri mere mujhe aur nahi nhi nahin kya kuch bahut hu hun raha rahi
gaya gaye tha thi jata jati karne kar bhi lekin abhi sath liye ek ko se ka ki ke ji ho
saya dan yang tidak sudah ini itu ada dengan untuk gigi sakit bisa apa kalau karena sekali
juga dok
el la los las que por con una es mi muy pero tengo dolor estoy diente muela nao uma com
""".split())

MIN_LATIN_SHARE = 0.90       # of alphabetic characters
MIN_FOREIGN_SHARE = 0.15     # of word tokens, for texts of >= 8 tokens
MIN_TOKENS_FOR_WORD_CHECK = 8
MIN_DISTINCT_FOREIGN = 4     # distinct foreign function words -> code-switched


def _is_latin_letter(ch: str) -> bool:
    return ch.isascii() or "À" <= ch <= "ɏ"   # Latin-1 + Latin Extended


def is_english(text: str) -> tuple:
    """(ok, reason). reason is None when ok.

    Terse English (lab reports, "semen analysis volume 3 ml ...", textspeak)
    has few English function words but no foreign ones, so it is kept: an
    earlier version that required English function words dropped 120 such
    rows as "non-English" (2026-09-22 run), of which only ~10 were not English.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False, "empty"
    if sum(_is_latin_letter(c) for c in letters) / len(letters) < MIN_LATIN_SHARE:
        return False, "non_latin_script"
    tokens = re.findall(r"[a-z]+", text.lower())
    if len(tokens) >= MIN_TOKENS_FOR_WORD_CHECK:
        foreign = sum(t in FOREIGN_FUNCTION_WORDS for t in tokens)
        english = sum(t in EN_FUNCTION_WORDS for t in tokens)
        if foreign / len(tokens) >= MIN_FOREIGN_SHARE and foreign > english:
            return False, "romanised_non_english"
    # English sentences with whole Hindi/Urdu clauses in them ("mere frount
    # teeth me chot lag gai thi jiske karan mujhe ..."): not English-only.
    if len({t for t in tokens if t in FOREIGN_FUNCTION_WORDS}) >= MIN_DISTINCT_FOREIGN:
        return False, "code_switched"
    return True, None


# --- Stage 3: dental topic --------------------------------------------------

# Phrases removed before matching, so they can neither include nor exclude.
FALSE_HIT_PHRASES = re.compile(
    r"\b(chewing|nicotine|bubble|nicorette)\s+gums?\b"
    r"|\b(nasal|abdominal|chest|pleural|peritoneal|thoracic|pelvic|sinus|uterine|body)\s+cavit(y|ies)\b"
    r"|\bgum\s+(arabic|tree|boots?)\b"
    r"|\blip\s+(balm|stick|gloss|service)\b|\blipstick\b|\bchapstick\b"
    r"|\bmother\s+tongue\b|\btongue\s+of\s+(the|my|his|her)\s+\w+"
    r"|\btongue[- ]in[- ]cheek\b",
    re.I,
)
TOOTH_WORD = (r"(tooth|teeth|toothache|dental|dentist|dentists|molars?|premolars?|incisors?"
              r"|gums?|gingiva\w*|wisdom|mouth)")
STRONG = re.compile(
    r"\b(tooth|teeth|toothaches?|dental|dentists?|gums?|gingiv\w*|molars?|premolars?"
    r"|incisors?|canine\s+tooth|wisdom\s+(tooth|teeth)|root\s+canals?|jaws?|tmj|tmd"
    r"|temporomandibular|mouth\s+ulcers?|ulcers?\s+(in|on)\s+(my|the|his|her)\s+mouth"
    r"|dentures?|periodont\w*|orthodont\w*)\b",
    re.I,
)
# Oral soft tissue: research-pm's P9 recall audit found most misses here
# (tongue, palate, lip, "inside my mouth"). Wider than the plan's list, so
# rows that match only on these carry `oral_soft_tissue` for the audit and
# for the LLM topic stage to clean up.
ORAL_SOFT = re.compile(
    r"\btongues?\b|\bpalate\b|\blips?\b"
    r"|\b(inside|roof|floor)\s+(of\s+)?(my|the|his|her)?\s*mouth\b"
    r"|\bin\s+(my|his|her)\s+mouth\b|\boral\s+(cavity|mucosa|thrush|ulcers?)\b"
    r"|\bcanker\s+sores?\b|\bsalivary?\s+glands?\b|\bsaliva\b",
    re.I,
)
# Ambiguous words: count only with a tooth word within 10 words either side.
NEEDS_CONTEXT = ["cavity", "cavities", "extraction", "extracted", "abscess", "abscesses",
                 "filling", "fillings", "crown", "crowns", "braces"]
_NEAR = r"(?:\W+\w+){0,10}?\W+"
CONTEXTUAL = re.compile(
    r"\b(" + "|".join(NEEDS_CONTEXT) + r")\b" + _NEAR + r"\b" + TOOTH_WORD + r"\b"
    r"|\b" + TOOTH_WORD + r"\b" + _NEAR + r"\b(" + "|".join(NEEDS_CONTEXT) + r")\b",
    re.I,
)
LOOSE_ONLY = re.compile(r"\b(filling|fillings|crown|crowns|braces)\b", re.I)
JAW = re.compile(r"\bjaws?\b", re.I)
CARDIAC = re.compile(r"\b(chest\s+(pain|tightness|pressure)|short(ness)?\s+of\s+breath"
                     r"|breathless\w*|heart\s+attack)\b", re.I)


def topic(text: str) -> dict:
    """{'dental': bool, 'via': str|None, 'tags': [...]}."""
    clean = FALSE_HIT_PHRASES.sub(" ", text)
    tags = []
    if JAW.search(clean) and CARDIAC.search(clean):
        tags.append("jaw_with_cardiac_symptoms")   # kept: MI red-flag cases (plan §3)
    m = STRONG.search(clean)
    if m:
        return {"dental": True, "via": m.group(0).lower(), "tags": tags}
    m = CONTEXTUAL.search(clean)
    if m:
        return {"dental": True, "via": "context:" + m.group(0).split()[0].lower(), "tags": tags}
    m = ORAL_SOFT.search(clean)
    if m:
        return {"dental": True, "via": "oral:" + m.group(0).lower(),
                "tags": tags + ["oral_soft_tissue"]}
    if LOOSE_ONLY.search(clean):
        tags.append("loose_term_only")             # would pass under the plan's looser list
    return {"dental": False, "via": None, "tags": tags}


# --- Stage 4: answer guardrails ---------------------------------------------

# Brand and generic names; lower case, matched on word boundaries. Includes
# OTC analgesics, antibiotics, antifungals, antivirals, steroids,
# mouthwash and toothpaste brands, local anaesthetics and common pharmacy
# products that appear in HealthCareMagic answers.
DRUGS = """
paracetamol acetaminophen tylenol panadol calpol crocin dolo ibuprofen advil motrin brufen
nurofen combiflam naproxen aleve naprosyn diclofenac voveran voltaren aceclofenac zerodol
ketorolac toradol ketorol aspirin disprin ecosprin mefenamic meftal nimesulide nise etoricoxib
celecoxib celebrex tramadol ultram codeine hydrocodone vicodin norco oxycodone percocet
morphine dihydrocodeine co-codamol cocodamol pregabalin gabapentin lyrica neurontin
carbamazepine tegretol amitriptyline serrapeptase chymoral trypsin
amoxicillin amoxycillin amoxil augmentin clavam moxikind mox novamox co-amoxiclav
amoxiclav penicillin phenoxymethylpenicillin cloxacillin ampicillin metronidazole flagyl
metrogyl tinidazole ornidazole clindamycin cleocin dalacin azithromycin zithromax azee
azithral clarithromycin erythromycin doxycycline tetracycline minocycline cephalexin
cefalexin keflex cefuroxime cefixime cefadroxil cefpodoxime ceftriaxone ciprofloxacin cipro
ofloxacin levofloxacin norfloxacin linezolid cotrimoxazole bactrim septran nitrofurantoin
vancomycin gentamicin rifampicin
fluconazole diflucan clotrimazole candid nystatin miconazole ketoconazole itraconazole
terbinafine amphotericin acyclovir aciclovir zovirax valacyclovir valtrex famciclovir
prednisolone prednisone dexamethasone hydrocortisone triamcinolone kenacort kenalog
betamethasone methylprednisolone medrol budesonide
chlorhexidine hexidine corsodyl peridex listerine betadine povidone hexetidine
benzydamine difflam tantum orahex clohex
lidocaine lignocaine xylocaine benzocaine orajel anbesol bonjela zytee dologel
sensodyne colgate pepsodent thermoseal
cetirizine loratadine allegra fexofenadine benadryl diphenhydramine chlorpheniramine
avil levocetirizine montelukast
omeprazole pantoprazole pantocid rabeprazole esomeprazole ranitidine famotidine rantac
antacid gelusil digene domperidone ondansetron emeset
metformin insulin glimepiride amlodipine atenolol losartan telmisartan warfarin
clopidogrel heparin statin atorvastatin rosuvastatin
diazepam valium alprazolam xanax lorazepam clonazepam zolpidem
becosules zincovit supradyn
""".split()
# "calcium", "vitamin" and "multivitamin" were in this list until 2026-09-23;
# research-pm's P9 over-removal audit found "calcium level" (a blood result)
# being read as a drug. Supplement brands stay.
DRUG_RE = re.compile(r"\b(" + "|".join(re.escape(d) for d in sorted(set(DRUGS), key=len, reverse=True))
                     + r")\b", re.I)
# Prescription-only classes the brief forbids: these drop the row.
DRUG_CLASS_RE = re.compile(
    r"\b(antibiotics?|antibacterials?|anti-?biotics?|nsaids?|antifungals?|antivirals?"
    r"|steroids?|corticosteroids?|opioids?|opiates?|muscle\s+relaxants?"
    r"|prescription[- ](strength|only|medicines?|drugs?|painkillers?))\b",
    re.I,
)
# Generic, non-prescription wording. Flagged for the record but NOT dropped:
# the brief allows a general over-the-counter mention, and research-pm's P9
# over-removal audit found "mouthwash" and "anti-inflammatory" throwing away
# otherwise clean answers (2026-09-23, lead's instruction).
GENERIC_PRODUCT_RE = re.compile(
    r"\b(analgesics?|painkillers?|pain\s+killers?|anti-?inflammator(y|ies)|antihistamines?"
    r"|mouthwash(es)?|mouth\s+wash(es)?|mouth\s+rinses?|gargles?|lozenges?|ointments?"
    r"|creams?|gels?)\b",
    re.I,
)
# A medicine named as a cause or a history ("stains from antibiotics") is not
# advice to take one. Advice wording in the same window wins.
CAUSE_CONTEXT = re.compile(
    r"\b(due\s+to|because\s+of|caused?\s+by|causing|side[- ]effects?\s+of|after\s+taking"
    r"|history\s+of|allergic\s+to|allergy\s+to|reaction\s+to|induced|stains?\s+from"
    r"|(are|is|was|were|comes?|came|results?|resulting)\s+from|from\s+the"
    r"|taken\s+(in|as|during|for)\b|resistant\s+to|overuse\s+of)\b", re.I)
ADVICE_CONTEXT = re.compile(
    r"\b(take|taking|takes|use|using|apply|applying|prescrib\w+|recommend\w*|advis\w+"
    r"|suggest\w*|start|started|continue|rinse\s+with|gargle\s+with|swallow|chew|give|put)\b",
    re.I)
# Frequencies that belong to self care, not to a dose ("rinse with warm salt
# water two to three times a day", "brush twice a day").
SELF_CARE_CONTEXT = re.compile(
    r"\b(salt|saline|warm\s+water|luke\s?warm|rinse\w*|gargl\w+|brush\w*|floss\w*|swish"
    r"|mouthwash|mouth\s+wash|baking\s+soda|ice\s+pack|cold\s+compress|water)\b", re.I)
CONTEXT_WINDOW = 70   # characters either side of a match
# An amount or prescription shorthand: a dose whatever the context.
DOSE_ABSOLUTE_RE = re.compile(
    r"\b\d+(\.\d+)?\s?(mg|mcg|µg|ug|gm|gms|g|ml|iu|units?)\b"
    r"|\b(bd|b\.d\.?|tds|t\.d\.s\.?|qid|q\.i\.d\.?|tid|t\.i\.d\.?|bid|b\.i\.d\.?|sos|stat)\b"
    r"|\btabs?\.\s*[a-z]"            # "Tab. X" prescription shorthand; "cap"
    r"|\bcaps?\.\s*[a-z]",           # without the dot is a crown, not a capsule
    re.I,
)
# A frequency or a spoonful: a dose only away from self care, because
# "rinse with salt water three times a day" and "brush twice a day" are not
# doses (research-pm's P9 over-removal audit, 2026-09-23).
DOSE_FREQUENCY_RE = re.compile(
    r"\b(\d+|once|twice|thrice|one|two|three|four|five|six)\s*(times|x)\s*(a|per|/)\s*day\b"
    r"|\b(once|twice|thrice)\s+(daily|a\s+day)\b"
    r"|\bevery\s+(\d+|two|three|four|five|six|eight|twelve)(\s*(-|to)\s*\d+)?\s*(hours?|hrs?|hourly)\b"
    r"|\b(\d+|one|two|three)\s+(tablets?|tabs?|capsules?|caps?|pills?|teaspoons?|tsp|drops?)\b",
    re.I,
)
DOSE_RE = re.compile(DOSE_ABSOLUTE_RE.pattern + "|" + DOSE_FREQUENCY_RE.pattern, re.I)
CONDITIONS = (r"(infection|abscess|cyst|tumou?r|cancer|caries|cavity|cavities|decay|pulpitis"
              r"|gingivitis|periodontitis|pericoronitis|dry\s+socket|alveolar\s+osteitis|tmj\w*"
              r"|tmd|ulcers?|aphthous\w*|thrush|candidiasis|leukoplakia|lichen\s+planus"
              r"|cellulitis|fracture|sinusitis|neuralgia|mucocele|fibroma|granuloma|stomatitis"
              r"|bruxism|impaction|impacted\s+\w+)")
DIAGNOSIS_RE = re.compile(
    r"\byou\s+(have|had|have\s+got|'ve\s+got|ve\s+got)\s+(a|an)\b"
    r"|\byou\s+(have|have\s+got)\s+(\w+\s+){0,2}" + CONDITIONS + r"\b"
    r"|\byou\s+are\s+suffering\s+from\b"
    r"|\b(you'?re|you\s+are)\s+having\s+(a|an)?\s*(\w+\s+){0,2}" + CONDITIONS + r"\b"
    r"|\bthis\s+is\s+(a|an|definitely)\b"
    r"|\bit\s+is\s+(a|an)\s+(\w+\s+){0,4}?(infection|abscess|cyst|tumou?r|cancer)\b"
    r"|\bdiagnosed\s+with\b"
    r"|\bconfirms?\b"
    r"|\b(most\s+likely|probably|definitely|surely|certainly)\s+(it\s+is\s+|it'?s\s+|this\s+is\s+)?(a|an)?\s*(\w+\s+){0,2}"
    + CONDITIONS + r"\b",
    re.I,
)


def _window(text: str, match) -> str:
    return text[max(0, match.start() - CONTEXT_WINDOW):match.end() + CONTEXT_WINDOW]


def _medicine_is_advice(text: str, pattern) -> bool:
    """True if any match reads as advice rather than a cause or a history."""
    for m in pattern.finditer(text):
        window = _window(text, m)
        if CAUSE_CONTEXT.search(window) and not ADVICE_CONTEXT.search(window):
            continue        # "the stains are from antibiotics" is not a prescription
        return True
    return False


def _is_dose(text: str) -> bool:
    """True if the answer gives a dose. Amounts always count; a frequency
    counts only when it is not about rinsing, brushing or flossing."""
    if DOSE_ABSOLUTE_RE.search(text):
        return True
    return any(not SELF_CARE_CONTEXT.search(_window(text, m))
               for m in DOSE_FREQUENCY_RE.finditer(text))


def answer_flags(answer: str) -> list:
    """Reasons an answer breaks the guardrails; empty list = clean.

    `generic_product` is recorded but is not a reason to drop the row
    (see GENERIC_PRODUCT_RE).
    """
    flags = []
    if _medicine_is_advice(answer, DRUG_RE):
        flags.append("drug_name")
    if _medicine_is_advice(answer, DRUG_CLASS_RE):
        flags.append("drug_class")
    if _is_dose(answer):
        flags.append("dose")
    if DIAGNOSIS_RE.search(answer):
        flags.append("definitive_diagnosis")
    if GENERIC_PRODUCT_RE.search(answer):
        flags.append("generic_product")
    return flags


DROPPING_FLAGS = ("drug_name", "drug_class", "dose", "definitive_diagnosis")


def _looks_truncated(answer: str) -> bool:
    """Answer ends without terminal punctuation, or is very short. A superset
    of "truncated": it also catches complete answers that just miss a final
    full stop, so it reads higher than the 6% research-pm counted by hand."""
    text = (answer or "").strip()
    return len(text) < 80 or text[-1] not in ".!?\"')"


def _starts_mid_sentence(answer: str) -> bool:
    """Some ChatDoctor answers are cut at the start as well ("gion with any
    massage oil ...")."""
    text = (answer or "").lstrip()
    return bool(text) and text[0].islower()


# --- Loading ----------------------------------------------------------------

def load_chatdoctor() -> list:
    rows = []
    with open(CHATDOCTOR, encoding="utf-8") as f:
        for i, line in enumerate(f):
            r = json.loads(line)
            rows.append({"source": "chatdoctor", "id": f"cd{i:06d}",
                         "question": r["input"] or "", "answer": r["output"] or ""})
    return rows


def _read_jsonl(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_liveqa() -> list:
    """One row per (question, answer) pair, as ChatDoctor rows are."""
    rows = []
    for r in _read_jsonl(LIVEQA / "TREC2017-LiveQA-Medical-Train1.jsonl"):
        q = f"{r.get('SUBJECT') or ''}\n{r.get('MESSAGE') or ''}".strip()
        for a in r.get("ANSWERS") or []:
            rows.append({"source": "liveqa_train1", "id": a.get("_answerid"),
                         "question": q, "answer": a.get("__text") or ""})
    for r in _read_jsonl(LIVEQA / "TREC2017-LiveQA-Medical-Train2.jsonl"):
        q = f"{r.get('SUBJECT') or ''}\n{r.get('MESSAGE') or ''}".strip()
        rows.append({"source": "liveqa_train2", "id": f"t2-{r.get('QUESTION_ID')}",
                     "question": q, "answer": r.get("ANSWER") or ""})
    for r in _read_jsonl(LIVEQA / "test.jsonl"):
        q = (f"{r.get('ORIGINAL_QUESTION_SUBJECT') or ''}\n"
             f"{r.get('ORIGINAL_QUESTION_MESSAGE') or ''}").strip()
        for a in r.get("REFERENCE_ANSWERS") or []:
            rows.append({"source": "liveqa_test", "id": a.get("_aid"),
                         "question": q, "answer": a.get("ANSWER") or ""})
    return rows


# --- Pipeline ---------------------------------------------------------------

def run(rows: list, samples: int = 0) -> tuple:
    counts = {"loaded": len(rows)}
    shown = Counter()

    def show(reason, row, text):
        if shown[reason] < samples:
            shown[reason] += 1
            print(f"  [{reason}] {row['id']}: {text[:200]!r}")

    seen, stage = set(), []
    for r in rows:
        key = (r["question"].strip(), r["answer"].strip())
        if key in seen:
            continue
        seen.add(key)
        stage.append(r)
    counts["after_dedupe"] = len(stage)
    counts["dropped_duplicate"] = len(rows) - len(stage)

    english, lang_reasons = [], Counter()
    for r in stage:
        ok_q, why_q = is_english(r["question"])
        ok_a, why_a = is_english(r["answer"])
        if ok_q and ok_a:
            english.append(r)
            continue
        reason = ("question:" + why_q) if not ok_q else ("answer:" + why_a)
        lang_reasons[reason] += 1
        show(reason, r, r["question"] if not ok_q else r["answer"])
    counts["after_english"] = len(english)
    counts["dropped_empty"] = sum(v for k, v in lang_reasons.items() if k.endswith(":empty"))
    counts["dropped_non_english"] = len(stage) - len(english) - counts["dropped_empty"]
    counts["dropped_language_by_reason"] = dict(lang_reasons)

    dental, tags = [], Counter()
    via = Counter()
    for r in english:
        t = topic(r["question"])
        for tag in t["tags"]:
            tags[tag] += 1
        if t["dental"]:
            r = {**r, "topic_via": t["via"], "topic_tags": t["tags"]}
            dental.append(r)
            via[t["via"].split(":")[0] if t["via"].startswith("context") else t["via"]] += 1
    counts["after_topic"] = len(dental)
    counts["dropped_not_dental"] = len(english) - len(dental)
    counts["topic_tag_counts_all_english_rows"] = dict(tags)
    counts["topic_first_match_top20"] = dict(via.most_common(20))
    counts["dental_tagged_jaw_with_cardiac"] = sum(
        "jaw_with_cardiac_symptoms" in r["topic_tags"] for r in dental)
    counts["dental_via_oral_soft_tissue_only"] = sum(
        "oral_soft_tissue" in r["topic_tags"] for r in dental)

    clean, flag_counts, only_class = [], Counter(), 0
    for r in dental:
        flags = answer_flags(r["answer"])
        r["answer_flags"] = flags
        for f in flags:
            flag_counts[f] += 1
        dropping = [f for f in flags if f in DROPPING_FLAGS]
        if dropping == ["drug_class"]:
            only_class += 1
        if not dropping:
            clean.append(r)
        else:
            show("answer:" + dropping[0], r, r["answer"])
    counts["after_answer_filter"] = len(clean)
    counts["dropped_answer"] = len(dental) - len(clean)
    counts["answer_flag_counts"] = dict(flag_counts)
    counts["dropped_only_for_drug_class_word"] = only_class
    counts["kept_with_generic_product_word"] = sum(
        "generic_product" in r["answer_flags"] for r in clean)
    counts["kept_answer_no_terminal_punctuation_or_very_short"] = sum(
        _looks_truncated(r["answer"]) for r in clean)
    counts["kept_answer_starts_mid_sentence"] = sum(
        _starts_mid_sentence(r["answer"]) for r in clean)
    return dental, clean, counts


def write_jsonl(path: Path, rows: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--samples", type=int, default=0, help="rows to print per drop reason")
    args = ap.parse_args()
    for path in (CHATDOCTOR, LIVEQA / "test.jsonl"):
        if not path.exists():
            print(f"missing {path} — see this file's docstring for how it was obtained")
            return 1
    OUT.mkdir(parents=True, exist_ok=True)

    report, all_dental, all_clean = {}, [], []
    for name, loader in (("chatdoctor", load_chatdoctor), ("liveqa", load_liveqa)):
        print(f"\n== {name}")
        dental, clean, counts = run(loader(), args.samples)
        report[name] = counts
        all_dental += dental
        all_clean += clean
        for k, v in counts.items():
            print(f"  {k}: {v}")

    write_jsonl(OUT / "dental_topic.jsonl", all_dental)
    write_jsonl(OUT / "dental_clean.jsonl", all_clean)
    (OUT / "filter_counts.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {len(all_dental)} dental and {len(all_clean)} clean rows to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
