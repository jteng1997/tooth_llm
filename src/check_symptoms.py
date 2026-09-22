"""Test 3 from llm/eval: does the model understand what the patient said?

    python src/check_symptoms.py [--model qwen3:4b] [--json out.json]

Replays each scripted dialogue and compares the extracted object with its
answer key, field by field. Reports per-field accuracy plus the failure
the eval spec calls out as the one that matters most:

  guessed   the key says null (the patient never answered) but the model
            filled something in — a guessed red flag propagates straight
            into the urgency decision
  missed    the key has a value but the model returned null

Only fields named in a case's answer key are scored; the key is partial
by design.
"""
import argparse
import io
import json
from collections import defaultdict
from pathlib import Path

from interview import DEFAULT_MODEL, Interview

REPO_ROOT = Path(__file__).resolve().parent.parent
DIALOGUES = REPO_ROOT / "llm" / "eval" / "symptom_dialogues.json"


def evaluate(model: str = DEFAULT_MODEL, verbose: bool = True) -> dict:
    cases = json.loads(io.open(DIALOGUES, encoding="utf-8").read())["cases"]
    per_field = defaultdict(lambda: {"right": 0, "total": 0})
    results = {"model": model, "n": len(cases), "exact": 0, "guessed": 0, "missed": 0, "cases": []}

    for case in cases:
        session = Interview(model)
        for turn in case["turns"]:
            session.record(turn["assistant"], turn["user"])
        got = session.extract()

        wrong, guessed, missed = {}, [], []
        for field, want in case["expected"].items():
            actual = got.get(field)
            per_field[field]["total"] += 1
            if actual == want:
                per_field[field]["right"] += 1
            else:
                wrong[field] = {"expected": want, "got": actual}
                if want is None:
                    guessed.append(field)
                elif actual is None:
                    missed.append(field)

        results["exact"] += not wrong
        results["guessed"] += bool(guessed)
        results["missed"] += bool(missed)
        results["cases"].append({"id": case["id"], "style": case["style"], "wrong": wrong,
                                 "guessed": guessed, "missed": missed, "got": got})
        if verbose:
            print(f"{'ok  ' if not wrong else 'FAIL'} {case['id']} ({case['style']})")
            for field, diff in wrong.items():
                kind = "GUESSED" if diff["expected"] is None else (
                    "missed" if diff["got"] is None else "wrong")
                print(f"       {kind} {field}: expected {diff['expected']!r}, got {diff['got']!r}")

    fields = {f: round(v["right"] / v["total"], 3) for f, v in sorted(per_field.items())}
    results["per_field_accuracy"] = fields
    scored = sum(v["total"] for v in per_field.values())
    correct = sum(v["right"] for v in per_field.values())
    results["field_accuracy"] = round(correct / scored, 4)

    if verbose:
        print(f"\nmodel: {model}")
        print(f"  exact dialogues   {results['exact']}/{results['n']}")
        print(f"  field accuracy    {correct}/{scored} ({results['field_accuracy']:.1%})")
        print(f"  dialogues with a guessed field (key says null)  {results['guessed']}/{results['n']}")
        print(f"  dialogues with a missed field (returned null)   {results['missed']}/{results['n']}")
        print("  per field: " + ", ".join(f"{f} {a:.0%}" for f, a in fields.items()))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--json")
    args = ap.parse_args()
    results = evaluate(args.model)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
