"""Silver labels: the urgency a ChatDoctor doctor's answer implies (plan §3.2).

    python src/silver_labels.py                       # label dental_topic.jsonl
    python src/silver_labels.py --evaluate labels/silver_hand_labels.csv
    python src/silver_labels.py --calibration-batch 40

Weak labels, not a key: an online doctor's advice, not a triage decision and
not a dentist's. Reported apart from the SDCEP-derived key and never used for
tuning (docs/decisions.md 2026-09-22 #12).

Input is `dataset/dental_qa/dental_topic.jsonl` — after the topic filter,
before the drug/dose/diagnosis answer filter (research-pm's clarification of
decision 13, 2026-09-23). THE DOCTOR'S TEXT IS READ ONLY HERE. It never goes
into a prompt, a model input or a training target: the system under test sees
the patient's question alone.

Rules, all deterministic and case-insensitive except where noted:
- phrase lists per label (RUBRIC_VERSION below), most urgent match wins;
- a phrase negated within 3 words before it does not count ("not an
  emergency", "no need to rush");
- an explicit denial of emergency anywhere in the answer caps the row at
  URGENT, so "Though not an emergency, it demands immediate care" is URGENT,
  not EMERGENCY (research-pm read it that way by hand);
- an emergency-room phrase offered as a way to obtain pain relief is capped at
  URGENT too ("take her to ER" for an injection is not a triage decision);
- a bare "consult a dentist" with no timing word is UNSPECIFIED, never SOON:
  nearly every answer says it, so it carries no urgency;
- more than one label matched -> `conflicted: true`.

Per row: silver_label, matched_phrase, conflicted, capped, and the label each
rule stage found.
"""
import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
DENTAL_TOPIC = REPO_ROOT / "dataset" / "dental_qa" / "dental_topic.jsonl"
OUT = REPO_ROOT / "dataset" / "dental_qa"

RUBRIC_VERSION = "1.1"   # 1.0 = first blind run; 1.1 adds the visit-context gate and the self-care ROUTINE clause
LABELS = ("EMERGENCY", "URGENT", "SOON", "ROUTINE", "UNSPECIFIED")
RANK = {label: i for i, label in enumerate(LABELS)}   # 0 = most urgent

# Rows whose source data is broken (the patient's question sits in the answer
# field). research-pm found this one by hand; it is skipped, not labelled.
SOURCE_FAULTS = {"cd011595"}

# "ER" and "A&E" are matched case-sensitively: lower-case "er" is a word
# ending, and "a&e" does not occur. Everything else is case-insensitive.
PHRASES = {
    "EMERGENCY": [
        r"emergency (room|department|dental service|dentist|care)", r"casualty",
        r"go(ing)? to (the )?(hospital|emergency|casualty)", r"nearest hospital",
        r"call an ambulance", r"911|999|108", r"immediate(ly)?", r"right away",
        r"straight away", r"at once", r"this (very )?(minute|moment)",
        r"life[- ]threatening", r"admitted",
    ],
    "URGENT": [
        r"as soon as possible", r"asap", r"at the earliest", r"urgent(ly)?",
        r"without delay", r"do not delay", r"don'?t delay", r"today", r"tomorrow",
        r"within 24 hours", r"in the next 24 hours", r"same day", r"first thing",
    ],
    "SOON": [
        r"within a few days", r"in a few days", r"in the next few days", r"this week",
        r"within a week", r"in a week", r"within \d+ days", r"soon",
    ],
    "ROUTINE": [
        r"nothing to worry", r"no need to (worry|see|visit|panic|rush)",
        r"not(hing)? serious", r"at your next (check ?-?up|visit|appointment)",
        r"routine (check ?-?up|dental visit|visit)", r"can wait", r"will settle",
        r"settle(s)? (down |on its own)?by itself", r"resolve(s)? on its own",
        r"no treatment (is )?(needed|required)", r"observe", r"wait and watch",
    ],
}
CASE_SENSITIVE = {"EMERGENCY": [r"\bER\b", r"\bA&E\b"]}

NEGATIONS = r"(not|no|never|isn'?t|aren'?t|don'?t|doesn'?t|without|nothing|avoid|unless)"
# A time frame counts only when it is about seeing someone. Doctors use the
# same words for healing ("the lump will dissolve in a few weeks", "it will
# heal in two to three days"), which is not a triage window.
VISIT = re.compile(r"(dentist|dental|doctor|physician|surgeon|clinic|hospital|see|visit|consult"
                   r"|appointment|check ?-?up|review|follow ?-?up|get it (checked|seen)|go to)", re.I)
VISIT_WINDOW = 80
NEEDS_VISIT_CONTEXT = {"SOON": None,      # every SOON phrase
                       "URGENT": {"today", "tomorrow", "same day", "first thing"}}
# The rubric's ROUTINE clause: self-care advice and no visit window.
SELF_CARE = re.compile(
    r"(salt(ed)? water|saline) (rinse|gargle|mouth ?wash)|(rinse|gargle)[^.]{0,30}(salt|warm water)"
    r"|soft diet|soft food|cold compress|ice pack|warm compress|hot fomentation"
    r"|maintain(ing)? (good )?oral hygiene|brush (twice|regularly|gently)|floss"
    r"|do ?n'?t worry|do not worry|no(thing) to panic|don'?t panic|self[- ]limiting"
    r"|will heal|heals? (on its own|by itself)|normal (tissue )?response|subsides?"
    r"|observation|keep (the area|it) clean", re.I)
# ... "with no visit recommended" (the rubric's wording). An answer that tells
# the patient to see someone, even with no time frame, stays UNSPECIFIED.
RECOMMENDS_VISIT = re.compile(
    r"\b(see|visit|consult|contact|approach|go to|report to|show (it |yourself |him |her )?to"
    r"|get (it |yourself )?(checked|examined|evaluated|seen)|refer(red)? to)\b[^.!?]{0,60}"
    r"\b(dentist|dental|doctor|physician|surgeon|specialist|orthodontist|endodontist|periodontist"
    r"|clinic|hospital|gp|practitioner)\b", re.I)
# "Though not an emergency, ... demands immediate care": a stated denial caps
# the whole answer at URGENT.
NO_EMERGENCY = re.compile(r"\b(not|no|isn'?t|nothing of)\s+(an?\s+|any\s+)?"
                          r"(dental\s+|medical\s+)?emergenc(y|ies)\b", re.I)
# An emergency room named as the way to get pain relief, not as triage.
FOR_MEDICATION = re.compile(r"(pain ?killer|analgesi|injection|prescription|prescribe|"
                            r"pain relief|shot|medication)", re.I)
MEDICATION_WINDOW = 90


def _negated(text: str, start: int) -> bool:
    """A negation in the three words before the match."""
    before = text[:start].split()[-3:]
    return any(re.fullmatch(NEGATIONS, w.strip(".,;:()"), re.I) for w in before)


def _matches(answer: str) -> list:
    """[(label, phrase, start)] for every phrase that fires and is not negated.

    A match inside a longer one is dropped: "as soon as possible" is URGENT,
    and the "soon" within it must not also count as SOON.
    """
    found = []
    for label in ("EMERGENCY", "URGENT", "SOON", "ROUTINE"):
        patterns = [(p, re.I) for p in PHRASES[label]]
        patterns += [(p, 0) for p in CASE_SENSITIVE.get(label, [])]
        for pattern, flags in patterns:
            for m in re.finditer(pattern, answer, flags):
                if _negated(answer, m.start()):
                    continue
                gate = NEEDS_VISIT_CONTEXT.get(label, ())
                if gate is None or (gate and m.group(0).lower() in gate):
                    window = answer[max(0, m.start() - VISIT_WINDOW):m.end() + VISIT_WINDOW]
                    if not VISIT.search(window):
                        continue      # a healing time, not a time to be seen
                found.append((label, m.group(0), m.start(), m.end()))
    kept = [f for f in found
            if not any(other is not f and other[2] <= f[2] and f[3] <= other[3]
                       and (other[3] - other[2]) > (f[3] - f[2]) for other in found)]
    return [(label, phrase, start) for label, phrase, start, _ in kept]


def label_answer(answer: str) -> dict:
    """{silver_label, matched_phrase, conflicted, capped, labels_found}."""
    answer = answer or ""
    found = _matches(answer)
    capped = []
    kept = []
    deny_emergency = bool(NO_EMERGENCY.search(answer))
    for label, phrase, start in found:
        if label == "EMERGENCY" and deny_emergency:
            capped.append("denied_emergency")
            label = "URGENT"      # code can only soften an EMERGENCY the text denies
        elif label == "EMERGENCY" and FOR_MEDICATION.search(
                answer[max(0, start - MEDICATION_WINDOW):start + MEDICATION_WINDOW]):
            capped.append("emergency_room_for_medication")
            label = "URGENT"
        kept.append((label, phrase))
    if not kept:
        # Rubric's last ROUTINE clause: self-care advice and no time frame at
        # all reads as "no professional visit needed yet", not as silence.
        care = SELF_CARE.search(answer)
        if care and not RECOMMENDS_VISIT.search(answer):
            return {"silver_label": "ROUTINE", "matched_phrase": care.group(0),
                    "conflicted": False, "capped": sorted(set(capped)),
                    "labels_found": ["ROUTINE"], "via": "self_care_no_window"}
        return {"silver_label": "UNSPECIFIED", "matched_phrase": None, "conflicted": False,
                "capped": sorted(set(capped)), "labels_found": []}
    best = min(kept, key=lambda lp: RANK[lp[0]])
    return {"silver_label": best[0], "matched_phrase": best[1],
            "conflicted": len({label for label, _ in kept}) > 1,
            "capped": sorted(set(capped)),
            "labels_found": sorted({label for label, _ in kept}, key=RANK.__getitem__)}


# --- Running over the corpus -------------------------------------------------

def label_rows(rows: list) -> list:
    out = []
    for r in rows:
        if r["id"] in SOURCE_FAULTS:
            out.append({**r, "silver_label": None, "source_fault": True})
            continue
        out.append({**r, **label_answer(r["answer"])})
    return out


def summarise(labelled: list) -> dict:
    scored = [r for r in labelled if not r.get("source_fault")]
    counts = Counter(r["silver_label"] for r in scored)
    covered = sum(counts[label] for label in LABELS[:-1])
    return {"rubric_version": RUBRIC_VERSION, "n": len(labelled),
            "source_faults": len(labelled) - len(scored),
            "label_counts": {label: counts[label] for label in LABELS},
            "coverage": covered / len(scored) if scored else 0.0,
            "conflicted": sum(r["conflicted"] for r in scored),
            "capped": dict(Counter(c for r in scored for c in r["capped"]))}


# --- Agreement with research-pm's blind hand labels ---------------------------

def read_hand_labels(path: Path) -> dict:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {row["id"]: row["hand_label"].strip().upper()
                for row in csv.DictReader(f) if row.get("id")}


def kappa_nominal(pairs: list) -> float:
    """Cohen's kappa over the five labels, unweighted (they are not one scale:
    UNSPECIFIED is 'no timing given', not a degree of urgency)."""
    from sklearn.metrics import cohen_kappa_score
    a, b = zip(*pairs)
    return float(cohen_kappa_score(a, b, labels=list(LABELS)))


def evaluate(labelled: list, hand: dict) -> dict:
    by_id = {r["id"]: r for r in labelled}
    pairs, missing, faults = [], [], []
    for row_id, want in hand.items():
        got = by_id.get(row_id)
        if got is None:
            missing.append(row_id)
        elif got.get("source_fault"):
            faults.append(row_id)
        else:
            pairs.append((want, got["silver_label"]))
    matrix = Counter(pairs)
    agree = sum(n for (a, b), n in matrix.items() if a == b)
    by_label = {}
    for label in LABELS:
        hand_n = sum(n for (a, _), n in matrix.items() if a == label)
        script_n = sum(n for (_, b), n in matrix.items() if b == label)
        right = matrix.get((label, label), 0)
        by_label[label] = {"hand": hand_n, "script": script_n, "both": right,
                           "recall": right / hand_n if hand_n else None,
                           "precision": right / script_n if script_n else None}
    under = sum(n for (a, b), n in matrix.items() if RANK[b] > RANK[a] and b != "UNSPECIFIED"
                and a != "UNSPECIFIED")
    return {"n": len(pairs), "not_in_corpus": missing, "source_faults": faults,
            "agreement": agree / len(pairs) if pairs else float("nan"),
            "kappa": kappa_nominal(pairs) if pairs else float("nan"),
            "confusion": {f"hand={a}|script={b}": n for (a, b), n in sorted(matrix.items())},
            "per_label": by_label,
            "script_less_urgent_than_hand": under}


def calibration_batch(labelled: list, n: int, seed: int = 20260923) -> list:
    """research-pm's batch 2: n rows the script calls EMERGENCY plus n from the
    other labels, shuffled, labels hidden, so EMERGENCY precision has a
    denominator (batch 1 had 2 EMERGENCY rows)."""
    rng = random.Random(seed)
    scored = [r for r in labelled if not r.get("source_fault")]
    emergency = [r for r in scored if r["silver_label"] == "EMERGENCY"]
    others = [r for r in scored if r["silver_label"] != "EMERGENCY"]
    picked = rng.sample(emergency, min(n, len(emergency))) + rng.sample(others, min(n, len(others)))
    rng.shuffle(picked)
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", default=str(DENTAL_TOPIC))
    ap.add_argument("--evaluate", help="CSV of blind hand labels (id, hand_label)")
    ap.add_argument("--calibration-batch", type=int, default=0,
                    help="write N EMERGENCY + N other rows for blind reading")
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.rows).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    labelled = label_rows(rows)
    summary = summarise(labelled)
    print(f"rubric {RUBRIC_VERSION} on {args.rows}")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    keep = ("id", "source", "silver_label", "matched_phrase", "conflicted", "capped",
            "labels_found", "source_fault")
    with open(OUT / "silver_labels.jsonl", "w", encoding="utf-8") as f:
        for r in labelled:
            f.write(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False) + "\n")
    print(f"wrote {OUT / 'silver_labels.jsonl'}")

    if args.evaluate:
        hand = read_hand_labels(Path(args.evaluate))
        result = evaluate(labelled, hand)
        print(f"\nagainst {args.evaluate}: n = {result['n']}"
              f"  agreement {result['agreement']:.1%}  kappa {result['kappa']:.3f}"
              f"  (bar: kappa >= 0.6)")
        for label, s in result["per_label"].items():
            recall = "n/a" if s["recall"] is None else f"{s['recall']:.0%}"
            precision = "n/a" if s["precision"] is None else f"{s['precision']:.0%}"
            print(f"  {label:12s} hand {s['hand']:3d}  script {s['script']:3d}  "
                  f"both {s['both']:3d}  recall {recall:>4}  precision {precision:>4}")
        print("  confusion (only the disagreements):")
        for key, n in result["confusion"].items():
            hand_label, script_label = key.split("|")
            if hand_label.split("=")[1] != script_label.split("=")[1]:
                print(f"    {key}: {n}")
        (OUT / "silver_vs_hand.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"  wrote {OUT / 'silver_vs_hand.json'}")

    if args.calibration_batch:
        batch = calibration_batch(labelled, args.calibration_batch)
        path = OUT / "silver_calibration_batch.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "patient_question", "doctor_answer", "hand_label", "note"])
            for r in batch:
                writer.writerow([r["id"], " ".join(r["question"].split()),
                                 " ".join(r["answer"].split()), "", ""])
        hidden = OUT / "silver_calibration_key.json"
        hidden.write_text(json.dumps({r["id"]: r["silver_label"] for r in batch}, indent=1),
                          encoding="utf-8")
        print(f"\ncalibration batch: {len(batch)} rows -> {path} (labels hidden); "
              f"key kept apart in {hidden}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
