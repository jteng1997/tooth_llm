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


def evaluate(model: str = DEFAULT_MODEL, verbose: bool = True, protocol=None, llm=None,
             dialogues: Path = DIALOGUES) -> dict:
    spec = json.loads(io.open(dialogues, encoding="utf-8").read())
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
        invented = invented_items(case["expected"], got)
        clicks_changed = {f: {"clicked": v, "got": got.get(f)}
                          for f, v in (case.get("expected_clicks_unchanged") or {}).items()
                          if got.get(f) != v}

        scope = case.get("scope", "headline")
        record = {"id": case["id"], "style": case["style"], "scope": scope,
                  "ambiguous": bool(case.get("ambiguous")), "wrong": wrong, "invented": invented,
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

    headline = [c for c in results["cases"] if c["scope"] == "headline"]
    results.update(_aggregate(headline))
    # ambiguous cases stay in the headline; this line reports them on their own too
    results["ambiguous"] = _aggregate([c for c in headline if c["ambiguous"]])
    focus = [ok for c in headline for f, ok in c["scored_fields"].items()
             if f in ("location", "pain_triggers")]
    results["location_and_triggers"] = {"right": sum(focus), "total": len(focus)}
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
        print(f"  dialogues with an invented list item (key not null)  {results['invented']}/{results['n']}"
              f"  ({results['invented_items']} items)")
        print(f"  checklist answers overwritten by prose          "
              f"{results['clicks_overwritten']}  (must be 0)")
        print("  per field: " + ", ".join(f"{f} {a:.0%}"
                                         for f, a in results["per_field_accuracy"].items()))
        lo, hi = clopper_pearson(results["fields_right"], results["fields_scored"])
        print(f"  field accuracy 95% CI (exact)  [{lo:.1%}, {hi:.1%}]")
        lt = results["location_and_triggers"]
        lo, hi = clopper_pearson(lt["right"], lt["total"])
        print(f"  location + triggers {lt['right']}/{lt['total']}  95% CI (exact) [{lo:.1%}, {hi:.1%}]")
        a = results["ambiguous"]
        if a["n"]:
            print(f"  ambiguous dialogues (included above, also shown alone): exact {a['exact']}/{a['n']}, "
                  f"fields {a['fields_right']}/{a['fields_scored']}")
        r = results["robustness"]
        if r["n"]:
            print(f"  out-of-scope robustness, separate from the above: exact {r['exact']}/{r['n']}, "
                  f"fields {r['fields_right']}/{r['fields_scored']}, guessed {r['guessed']}, "
                  f"missed {r['missed']}, English-only notice would show {r['english_notice']}/{r['n']}")
    return results


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple:
    from scipy.stats import beta
    if n == 0:
        return (float("nan"), float("nan"))
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


def configuration(model: str, dialogues: Path) -> dict:
    """What this score was measured on, so a one-shot blind run is logged."""
    import datetime
    import hashlib
    import subprocess

    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    try:
        commit = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {"date": datetime.datetime.now().isoformat(timespec="seconds"), "model": model,
            "dialogues": str(dialogues), "dialogues_sha256": sha(dialogues),
            "interview_py_sha256": sha(REPO_ROOT / "src" / "interview.py"),
            "system_symptoms_sha256": sha(REPO_ROOT / "llm" / "prompts" / "system_symptoms.md"),
            "protocol_sha256": sha(REPO_ROOT / "llm" / "protocol" / "triage_protocol.yaml"),
            "git_commit": commit}


def invented_items(expected: dict, got: dict) -> dict:
    """List items the patient never gave, in a field whose key is not null
    (the 'guessed' count only covers null keys): {field: [items]}."""
    out = {}
    for field, want in expected.items():
        actual = got.get(field)
        if isinstance(want, list) and isinstance(actual, list):
            extra = sorted(set(actual) - set(want))
            if extra:
                out[field] = extra
    return out


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
            "invented": sum(bool(c.get("invented")) for c in cases),
            "invented_items": sum(len(v) for c in cases for v in (c.get("invented") or {}).values()),
            "fields_scored": scored, "fields_right": correct,
            "field_accuracy": round(correct / scored, 4) if scored else float("nan"),
            "per_field_accuracy": {f: round(v["right"] / v["total"], 3)
                                   for f, v in sorted(per_field.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--json")
    ap.add_argument("--dialogues", default=str(DIALOGUES),
                    help="dialogue file (held-out: labels/heldout/symptom_dialogues_heldout.json; "
                         "never show its per-case output to llm-dev)")
    args = ap.parse_args()
    results = evaluate(args.model, dialogues=Path(args.dialogues))
    results["configuration"] = configuration(args.model, Path(args.dialogues))
    print(f"  configuration: {json.dumps(results['configuration'])}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
