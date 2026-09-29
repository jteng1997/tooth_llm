"""Phrase sets through the real interview extraction (qwen3:14b by default).

    python src/check_phrases.py                                   # both sets
    python src/check_phrases.py --sets llm/eval/relief_phrases.json --json out.json

Each phrase is the patient's reply to the chat question that asks for its
field (Q11 pain_severity for severity_phrases*.json, Q10 pain_relief_effect
for relief_phrases.json). Production has no free-text opening, so an
"opening" phrase is delivered the same way. Checklist A is No except Q9
(pain), checklist B is all No; every other chat question, and a re-ask of the
target question, gets "I'm not sure." so only the phrase can settle the field.
The value scored is the field once the target question is finished (asked,
and re-asked once if unsettled); the interview stops there, since a later
"I'm not sure." never replaces a verified value.

Severity sets: `severe` true/false; the result is severe / not severe (a
null counts as not severe, the direction that lowers urgency). Relief set:
`expected` is the exact value (helped, not_helped, not_tried or null). Cases
marked `"tuned": true` (wording quoted in the extraction instruction) are
reported apart from the independent ones.
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import protocol as protocol_mod  # noqa: E402
from interview import DEFAULT_MODEL, EXTRACTION_INSTRUCTION, SYSTEM_PROMPT, Interview  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL = REPO_ROOT / "llm" / "eval"
DEFAULT_SETS = [EVAL / "severity_phrases.json", EVAL / "severity_phrases_b.json",
                EVAL / "relief_phrases.json"]
NOT_SURE = "I'm not sure."


def target(case: dict) -> tuple:
    """(question id, field) the phrase answers."""
    return ("Q10", "pain_relief_effect") if "expected" in case else ("Q11", "pain_severity")


def run_phrase(case: dict, model: str, protocol, llm=None) -> dict:
    qid, field = target(case)
    session = Interview(model, protocol=protocol, **({"llm": llm} if llm else {}))
    step = session.start()
    replies = []
    while step["type"] != "done":
        if step["type"] == "checklist":
            rows = [item["id"] for item in step["items"]]
            step = session.submit_checklist(step["group"], {r: r == "Q9" for r in rows})
            continue
        if qid in [r[0] for r in replies] and step["id"] != qid:
            break       # the target question is finished; a later "not sure" cannot change it
        answer = case["text"] if step["id"] == qid and qid not in [r[0] for r in replies] else NOT_SURE
        replies.append((step["id"], answer))
        step = session.reply(answer)
    return {"got": session.symptoms.get(field), "asked": [r[0] for r in replies],
            "reasked": replies.count((qid, NOT_SURE)) > 0}


def score(case: dict, got) -> bool:
    if "expected" in case:
        return got == case["expected"]
    return (got == "severe") == case["severe"]


def summarise(rows: list) -> dict:
    out = {}
    for label, part in (("independent", [r for r in rows if not r["tuned"]]),
                        ("tuned", [r for r in rows if r["tuned"]])):
        if part:
            out[label] = {"n": len(part), "correct": sum(r["ok"] for r in part),
                          "wrong_ids": [r["id"] for r in part if not r["ok"]]}
    sev = [r for r in rows if "severe" in r]
    if sev:
        key_sev = [r for r in sev if r["severe"]]
        key_not = [r for r in sev if not r["severe"]]
        out["false_drops"] = {"n": len(key_sev), "k": sum(not r["ok"] for r in key_sev)}
        out["false_keeps"] = {"n": len(key_not), "k": sum(not r["ok"] for r in key_not)}
    return out


def configuration(model: str) -> dict:
    return {"model": model,
            "interview_py_sha256": hashlib.sha256((REPO_ROOT / "src" / "interview.py").read_bytes()).hexdigest(),
            "extraction_prompt_sha256": hashlib.sha256(
                (SYSTEM_PROMPT + "\n" + EXTRACTION_INSTRUCTION).encode()).hexdigest(),
            "protocol_sha256": hashlib.sha256(protocol_mod.PROTOCOL_PATH.read_bytes()).hexdigest()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sets", nargs="+", default=[str(p) for p in DEFAULT_SETS])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--json", default=str(REPO_ROOT / "runs" / "evals" / "phrases_v03.json"))
    args = ap.parse_args()
    protocol = protocol_mod.load(allow_unreviewed=True)
    result = {"date": datetime.datetime.now().isoformat(timespec="seconds"),
              "configuration": configuration(args.model), "sets": {}}
    print(json.dumps(result["configuration"]))
    for path in map(Path, args.sets):
        cases = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for case in cases:
            r = run_phrase(case, args.model, protocol)
            row = {"id": case["id"], "text": case["text"], "tuned": bool(case.get("tuned")),
                   "got": r["got"], "reasked": r["reasked"], "ok": score(case, r["got"])}
            row.update({k: case[k] for k in ("severe", "expected") if k in case})
            rows.append(row)
            want = case.get("expected", "severe" if case.get("severe") else "not severe")
            print(f"{'ok ' if row['ok'] else 'BAD'} {path.name} {case['id']} want {want!r} "
                  f"got {r['got']!r}{' (re-asked)' if r['reasked'] else ''}", flush=True)
        result["sets"][path.name] = {"summary": summarise(rows), "cases": rows}
        print(path.name, json.dumps(result["sets"][path.name]["summary"]), flush=True)
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
