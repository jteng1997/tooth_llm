"""Stage 2 of the dental topic filter: a local model reads the patient's
message and says whether the question is about teeth, gums, jaw or mouth.

    python src/topic_classify_llm.py --trial 20        # measure against P9 labels
    python src/topic_classify_llm.py --rows dataset/dental_qa/dental_topic.jsonl

The plan (§3, stage 2) calls for this when keyword precision is below 90%;
research-pm measured 76.5% (153/200, 95% CI 70-82%) on 2026-09-23, and the
oral soft-tissue terms added the same day loosened it further.

Heavy job: one Ollama call per row, scheduled by the lead (one GPU).
`--trial` runs only against rows research-pm has already labelled by hand
(labels/dental_filter_audit.csv, audit A1), so the stage is measured before
it is trusted, and prints the projected runtime for a full pass.

The model sees the patient's message only, fenced as data, and answers under
a schema. It never sees the doctor's answer, and it cannot change any label
on its own: its verdict is recorded next to the keyword verdict.
"""
import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_triage import clopper_pearson  # noqa: E402
from interview import DEFAULT_MODEL, chat  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DENTAL_TOPIC = REPO_ROOT / "dataset" / "dental_qa" / "dental_topic.jsonl"
AUDIT = REPO_ROOT / "labels" / "dental_filter_audit.csv"
OUT = REPO_ROOT / "dataset" / "dental_qa"

SYSTEM = """You sort patient messages by topic for a dental research dataset.

Decide whether the message is asking about a problem with the teeth, gums,
jaw joint, or the inside of the mouth (tongue, palate, lips, mouth ulcers).

Count as dental:
- pain, decay, fillings, crowns, extractions, wisdom teeth, braces, dentures
- gum problems, mouth ulcers, tongue or palate problems, jaw joint problems
- questions about dental treatment the patient has had or is considering

Do NOT count as dental:
- a dental word used in passing about another problem ("toothache in my leg",
  "my blood pressure was taken at the dentist", "I am a dental hygienist")
- teething blamed for a general illness such as fever or diarrhoea
- general medical questions that merely mention the mouth or face

Answer with JSON only. `dental` is your verdict; `quote` is the few words from
the message that decided it, copied exactly, or null if nothing did."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["dental", "quote"],
    "properties": {"dental": {"type": "boolean"}, "quote": {"type": ["string", "null"]}},
}


def _fence(message: str) -> str:
    clean = message.replace("<patient_message>", "").replace("</patient_message>", "")
    return f"<patient_message>\n{clean}\n</patient_message>\n\nAnswer with the JSON."


def classify(message: str, model: str = DEFAULT_MODEL, llm=None) -> dict:
    llm = llm or (lambda messages, schema: chat(messages, model, schema=schema))
    raw = llm([{"role": "system", "content": SYSTEM},
               {"role": "user", "content": _fence(message)}], SCHEMA)
    try:
        out = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"dental": None, "quote": None, "invalid": str(raw)[:120]}
    quote = out.get("quote")
    # The quote is checked like every other quote in this project: it must be
    # the patient's words, not the model's. A bad quote does not flip the
    # verdict, it is only recorded.
    supported = bool(quote) and _normalise(quote) in _normalise(message)
    return {"dental": bool(out.get("dental")), "quote": quote, "quote_supported": supported}


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def read_audit(path: Path, audit: str) -> dict:
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r["label"] for r in csv.DictReader(f) if r["audit"] == audit}


def run(rows: list, model: str, llm=None, verbose: bool = True) -> list:
    out = []
    for r in rows:
        start = time.perf_counter()
        verdict = classify(r["question"], model, llm)
        verdict["seconds"] = time.perf_counter() - start
        out.append({**r, **verdict})
        if verbose:
            print(f"  {r['id']}  llm_dental={verdict['dental']}  "
                  f"{verdict['seconds']:.1f}s  quote={str(verdict.get('quote'))[:60]!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", default=str(DENTAL_TOPIC))
    ap.add_argument("--trial", type=int, default=0,
                    help="N hand-labelled rows (balanced) instead of the corpus")
    ap.add_argument("--oral", type=int, default=0,
                    help="also run N rows tagged oral_soft_tissue (no hand labels exist "
                         "for these yet: the model's verdict is an estimate, not a measurement)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--json", help="write results here")
    args = ap.parse_args()

    corpus = {json.loads(line)["id"]: json.loads(line)
              for line in Path(args.rows).read_text(encoding="utf-8").splitlines() if line.strip()}

    if args.trial:
        hand = read_audit(AUDIT, "A1_topic_precision")
        rng = random.Random(args.seed)
        per_label = max(1, args.trial // 2)
        picked = []
        for label in ("dental", "not_dental"):
            pool = [i for i, lab in hand.items() if lab == label and i in corpus]
            picked += rng.sample(pool, min(per_label, len(pool)))
        rng.shuffle(picked)
        rows = [corpus[i] for i in picked]
        print(f"trial: {len(rows)} rows from A1 ({sum(hand[i] == 'dental' for i in picked)} dental, "
              f"{sum(hand[i] == 'not_dental' for i in picked)} not dental), model {args.model}")
        results = run(rows, args.model, verbose=True)
        right = sum((r["dental"] is True) == (hand[r["id"]] == "dental") for r in results)
        kept_wrongly = [r["id"] for r in results
                        if r["dental"] is True and hand[r["id"]] == "not_dental"]
        dropped_wrongly = [r["id"] for r in results
                           if r["dental"] is False and hand[r["id"]] == "dental"]
        seconds = [r["seconds"] for r in results]
        lo, hi = clopper_pearson(right, len(results))
        print(f"\nagreement with the hand labels: {right}/{len(results)} "
              f"({right / len(results):.0%}, 95% CI [{lo:.0%}, {hi:.0%}])")
        print(f"  kept a non-dental row: {kept_wrongly}")
        print(f"  dropped a dental row:  {dropped_wrongly}   <- the costly direction")
        print(f"  quote supported by the message: "
              f"{sum(r.get('quote_supported') for r in results)}/{len(results)}")
        print(f"  invalid outputs: {sum(r['dental'] is None for r in results)}")
        mean = sum(seconds) / len(seconds)
        print(f"  {mean:.1f}s per row (min {min(seconds):.1f}, max {max(seconds):.1f})")
        for n, what in ((len(corpus), "the kept dental rows"),
                        (102190, "every row the keyword filter rejected")):
            print(f"  projected: {n} rows x {mean:.1f}s = {n * mean / 3600:.1f} h for {what}")

        if args.oral:
            oral = [r for r in corpus.values() if "oral_soft_tissue" in r.get("topic_tags", [])]
            rng2 = random.Random(args.seed)
            sample = rng2.sample(oral, min(args.oral, len(oral)))
            print(f"\noral_soft_tissue rows ({len(oral)} in the corpus), {len(sample)} sampled:")
            oral_results = run(sample, args.model, verbose=True)
            kept = sum(r["dental"] is True for r in oral_results)
            lo2, hi2 = clopper_pearson(kept, len(oral_results))
            print(f"  the model calls {kept}/{len(oral_results)} of them dental "
                  f"({kept / len(oral_results):.0%}, 95% CI [{lo2:.0%}, {hi2:.0%}])")
            print("  NOT a precision measurement: no human has labelled these rows. "
                  "research-pm needs to read a sample before this number is used.")
            results = results + oral_results
    else:
        rows = list(corpus.values())
        print(f"full pass: {len(rows)} rows, model {args.model}")
        results = run(rows, args.model, verbose=False)
        counts = Counter(r["dental"] for r in results)
        print(f"  llm says dental: {counts[True]}, not dental: {counts[False]}, "
              f"invalid: {counts[None]}")

    path = Path(args.json) if args.json else OUT / "topic_llm_trial.json"
    path.write_text(json.dumps([{k: v for k, v in r.items() if k != "answer"} for r in results],
                               indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
