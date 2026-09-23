"""Test 3 from llm/eval: does the model understand what the patient said?

    python src/check_symptoms.py [--model qwen3:4b] [--json out.json]

Drives the real interview: start() -> submit_checklist("A") ->
submit_checklist("B") -> reply() per chat question, with the case's scripted
answers. That is the shipped flow (decisions.md 2026-09-22, protocol v0.1
item 5), so only the five chat questions are extracted; the checklist rows
are clicks. Rebuilt 2026-09-23: the old dialogues replayed a chat-only
interview and scored fields (pain_present, the red flags) that extraction
never touches now, which flattered and punished the model for a path that no
longer exists.

Reports per-field accuracy plus the failure the eval spec calls out as the
one that matters most:

  guessed   the key says null (the patient never settled it) but the model
            filled something in — a guessed field goes straight into triage
  missed    the key has a value but the model returned null

Two extra lines:
  clicks    a checklist answer that prose overwrote (must never happen)
  robustness  cases marked "scope": "robustness" (D05, non-English answers,
            out of scope since the English-only decision) — scored apart and
            never in the headline numbers.
"""
import argparse
import io
import json
from collections import defaultdict
from pathlib import Path

import protocol as protocol_mod
from interview import DEFAULT_MODEL, Interview, _not_latin

REPO_ROOT = Path(__file__).resolve().parent.parent
DIALOGUES = REPO_ROOT / "llm" / "eval" / "symptom_dialogues.json"


def _checklist_answers(protocol, group: str, given: dict) -> dict:
    """Every row of the group, defaulting to No, with the case's clicks on top."""
    rows = [q for q in protocol.questions
            if getattr(q, "input", "") == "yesno_checklist" and getattr(q, "group", None) == group]
    answers = {q.id: False for q in rows}
    answers.update({k: v for k, v in (given or {}).items() if k in answers})
    return answers


def run_case(case: dict, model: str, protocol, llm=None) -> dict:
    """Play one dialogue through the real interview. Returns the symptoms and
    a log of what was asked, so a miss can be traced to the question."""
    session = Interview(model, protocol=protocol, **({"llm": llm} if llm else {}))
    step = session.start()
    asked, unscripted = [], []
    pending = {qid: (list(a) if isinstance(a, list) else [a])
               for qid, a in case["script"].items()}

    while step["type"] != "done":
        if step["type"] == "checklist":
            step = session.submit_checklist(
                step["group"], _checklist_answers(protocol, step["group"], case["checklist"].get(step["group"])))
            continue
        qid = step["id"]
        answers = pending.get(qid)
        if not answers:
            unscripted.append(qid)
            answer = "I'm not sure."
        else:
            answer = answers.pop(0)
        asked.append({"id": qid, "answer": answer})
        step = session.reply(answer)

    return {"symptoms": session.symptoms, "asked": asked, "unscripted": unscripted,
            "unused": {qid: rest for qid, rest in pending.items() if rest}}


def evaluate(model: str = DEFAULT_MODEL, verbose: bool = True, protocol=None, llm=None) -> dict:
    spec = json.loads(io.open(DIALOGUES, encoding="utf-8").read())
    protocol = protocol or protocol_mod.load(allow_unreviewed=True)
    results = {"model": model, "cases": []}

    for case in spec["cases"]:
        played = run_case(case, model, protocol, llm)
        got = played["symptoms"]

        wrong, guessed, missed = {}, [], []
        for field, want in case["expected"].items():
            actual = got.get(field)
            if isinstance(want, list) and isinstance(actual, list):
                same = sorted(want) == sorted(actual)
            else:
                same = actual == want
            if not same:
                wrong[field] = {"expected": want, "got": actual}
                if want is None:
                    guessed.append(field)
                elif actual is None:
                    missed.append(field)
        clicks_changed = {f: {"clicked": v, "got": got.get(f)}
                          for f, v in (case.get("expected_clicks_unchanged") or {}).items()
                          if got.get(f) != v}

        scope = case.get("scope", "headline")
        record = {"id": case["id"], "style": case["style"], "scope": scope, "wrong": wrong,
                  "guessed": guessed, "missed": missed, "clicks_changed": clicks_changed,
                  "asked": played["asked"], "unscripted": played["unscripted"],
                  "unused": played["unused"], "got": got,
                  "scored_fields": {f: (got.get(f) == want if not isinstance(want, list)
                                        else sorted(got.get(f) or []) == sorted(want))
                                    for f, want in case["expected"].items()}}
        if scope == "robustness":
            record["english_notice_would_show"] = any(
                _not_latin(a["answer"]) for a in played["asked"])
        results["cases"].append(record)
        if verbose:
            tag = "" if scope == "headline" else f" [{scope}, not in the headline numbers]"
            print(f"{'ok  ' if not wrong and not clicks_changed else 'FAIL'} {case['id']} "
                  f"({case['style']}){tag}")
            for field, diff in wrong.items():
                kind = "GUESSED" if diff["expected"] is None else (
                    "missed" if diff["got"] is None else "wrong")
                print(f"       {kind} {field}: expected {diff['expected']!r}, got {diff['got']!r}")
            for field, diff in clicks_changed.items():
                print(f"       CLICK OVERWRITTEN {field}: clicked {diff['clicked']!r}, "
                      f"got {diff['got']!r}")
            if played["unscripted"]:
                print(f"       (no scripted answer for {played['unscripted']})")

    results.update(_aggregate([c for c in results["cases"] if c["scope"] == "headline"]))
    robust = [c for c in results["cases"] if c["scope"] == "robustness"]
    results["robustness"] = {**_aggregate(robust),
                             "english_notice": sum(c["english_notice_would_show"] for c in robust)}
    results["clicks_overwritten"] = sum(bool(c["clicks_changed"]) for c in results["cases"])

    if verbose:
        print(f"\nmodel: {model}   chat fields only: {spec['chat_fields']}")
        print(f"  exact dialogues   {results['exact']}/{results['n']}")
        print(f"  field accuracy    {results['fields_right']}/{results['fields_scored']} "
              f"({results['field_accuracy']:.1%})")
        print(f"  dialogues with a guessed field (key says null)  {results['guessed']}/{results['n']}")
        print(f"  dialogues with a missed field (returned null)   {results['missed']}/{results['n']}")
        print(f"  checklist answers overwritten by prose          "
              f"{results['clicks_overwritten']}  (must be 0)")
        print("  per field: " + ", ".join(f"{f} {a:.0%}"
                                         for f, a in results["per_field_accuracy"].items()))
        r = results["robustness"]
        if r["n"]:
            print(f"  out-of-scope robustness, separate from the above: exact {r['exact']}/{r['n']}, "
                  f"fields {r['fields_right']}/{r['fields_scored']}, guessed {r['guessed']}, "
                  f"missed {r['missed']}, English-only notice would show {r['english_notice']}/{r['n']}")
    return results


def _aggregate(cases: list) -> dict:
    per_field = defaultdict(lambda: {"right": 0, "total": 0})
    for c in cases:
        for field, ok in c["scored_fields"].items():
            per_field[field]["total"] += 1
            per_field[field]["right"] += ok
    scored = sum(v["total"] for v in per_field.values())
    correct = sum(v["right"] for v in per_field.values())
    return {"n": len(cases), "exact": sum(not c["wrong"] for c in cases),
            "guessed": sum(bool(c["guessed"]) for c in cases),
            "missed": sum(bool(c["missed"]) for c in cases),
            "fields_scored": scored, "fields_right": correct,
            "field_accuracy": round(correct / scored, 4) if scored else float("nan"),
            "per_field_accuracy": {f: round(v["right"] / v["total"], 3)
                                   for f, v in sorted(per_field.items())}}


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
