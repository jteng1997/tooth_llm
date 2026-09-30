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
reported apart from the independent ones. Cases marked `"unclear": true`
(the rulings do not settle them; `severe` is null) are never scored: their
raw readings are listed apart, for the user. --breakout NAME=ID,... reports
a named subset (e.g. the HEDGE probes) as its own block as well.

    python src/check_phrases.py --sets llm/eval/heldback/severity_phrases_c.json \
        --breakout HEDGE=HS19,HS20,HS22,HS23,HS35
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import interview as live_interview  # noqa: E402
import protocol as protocol_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = live_interview.DEFAULT_MODEL
IV = live_interview                     # the extraction module in use (--interview swaps it)
IV_FILE = REPO_ROOT / "src" / "interview.py"


def load_interview(path) -> tuple:
    """(module, sha256) of an interview.py kept elsewhere, e.g. an earlier
    configuration, without touching src/interview.py. Its __file__ is set to
    src/interview.py so its repo-relative paths (prompts, protocol) resolve
    as they did when it was live."""
    import types
    source = Path(path).read_bytes()
    module = types.ModuleType("interview_under_test")
    module.__file__ = str(IV_FILE)
    exec(compile(source.decode("utf-8"), str(path), "exec"), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()
EVAL = REPO_ROOT / "llm" / "eval"
DEFAULT_SETS = [EVAL / "severity_phrases.json", EVAL / "severity_phrases_b.json",
                EVAL / "relief_phrases.json"]
NOT_SURE = "I'm not sure."


def target(case: dict) -> tuple:
    """(question id, field) the phrase answers."""
    return ("Q10", "pain_relief_effect") if "expected" in case else ("Q11", "pain_severity")


def run_phrase(case: dict, model: str, protocol, llm=None) -> dict:
    qid, field = target(case)
    session = IV.Interview(model, protocol=protocol, **({"llm": llm} if llm else {}))
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


def score(case: dict, got):
    """True/False; None for an `unclear` case (the rulings do not settle it),
    which is never scored."""
    if case.get("unclear"):
        return None
    if "expected" in case:
        return got == case["expected"]
    return (got == "severe") == case["severe"]


def _block(part: list) -> dict:
    out = {"n": len(part), "correct": sum(r["ok"] for r in part),
           "wrong_ids": [r["id"] for r in part if not r["ok"]]}
    if part and "severe" in part[0]:
        key_sev = [r for r in part if r["severe"]]
        key_not = [r for r in part if not r["severe"]]
        out["false_drops"] = {"n": len(key_sev), "k": sum(not r["ok"] for r in key_sev),
                              "ids": [r["id"] for r in key_sev if not r["ok"]]}
        out["false_keeps"] = {"n": len(key_not), "k": sum(not r["ok"] for r in key_not),
                              "ids": [r["id"] for r in key_not if not r["ok"]]}
    return out


def summarise(rows: list, breakout: dict = None) -> dict:
    """Independent and tuned apart, with severity directions in each;
    `unclear` cases only as raw readings; each named breakout (e.g. the HEDGE
    probes) as its own block, which is also inside the numbers above."""
    scored = [r for r in rows if r["ok"] is not None]
    post = [r for r in scored if r.get("post_hoc")]
    scored_ex = [r for r in scored if not r.get("post_hoc")]
    out = {}
    # post_hoc: keyed by a ruling made after its reading was seen (set c
    # HU01-HU08, 2026-09-30) -- never independent evidence, reported apart
    for label, part in (("independent", [r for r in scored_ex if not r["tuned"]]),
                        ("tuned", [r for r in scored_ex if r["tuned"]]),
                        ("post_hoc", post)):
        if part:
            out[label] = _block(part)
    unclear = [r for r in rows if r["ok"] is None]
    if unclear:
        out["unclear_not_scored"] = {r["id"]: r["got"] for r in unclear}
    for name, ids in (breakout or {}).items():
        part = [r for r in scored if r["id"] in ids]
        out[f"breakout_{name}"] = {**_block(part), "unclear": {r["id"]: r["got"] for r in unclear
                                                               if r["id"] in ids}}
    return out


def configuration(model: str, interview_file: Path = IV_FILE, interview_sha: str = None) -> dict:
    """What was actually loaded: the interview file and its hash, and the
    prompts of that module (not of src/interview.py, when --interview)."""
    return {"model": model, "interview_file": str(interview_file),
            "interview_py_sha256": interview_sha or hashlib.sha256(IV_FILE.read_bytes()).hexdigest(),
            "extraction_prompt_sha256": hashlib.sha256(
                (IV.SYSTEM_PROMPT + "\n" + IV.EXTRACTION_INSTRUCTION).encode()).hexdigest(),
            "extraction_instruction_sha256": hashlib.sha256(
                IV.EXTRACTION_INSTRUCTION.encode()).hexdigest(),
            "protocol_sha256": hashlib.sha256(protocol_mod.PROTOCOL_PATH.read_bytes()).hexdigest()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sets", nargs="+", default=[str(p) for p in DEFAULT_SETS])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--json", default=str(REPO_ROOT / "runs" / "evals" / "phrases_v03.json"))
    ap.add_argument("--breakout", action="append", default=[], metavar="NAME=ID,ID,...",
                    help="report these case ids as their own block too, e.g. "
                         "HEDGE=HS19,HS20,HS22,HS23,HS35")
    ap.add_argument("--interview", metavar="PATH",
                    help="run the extraction from this interview.py instead of src/interview.py "
                         "(e.g. an earlier configuration); its sha256 is recorded")
    args = ap.parse_args()
    global IV
    interview_file, interview_sha = IV_FILE, None
    if args.interview:
        IV, interview_sha = load_interview(args.interview)
        interview_file = Path(args.interview)
    breakout = {}
    for item in args.breakout:
        name, _, ids = item.partition("=")
        breakout[name] = set(filter(None, ids.split(",")))
    protocol = protocol_mod.load(allow_unreviewed=True)
    result = {"date": datetime.datetime.now().isoformat(timespec="seconds"),
              "configuration": configuration(args.model, interview_file, interview_sha), "sets": {}}
    print(json.dumps(result["configuration"]))
    for path in map(Path, args.sets):
        cases = json.loads(path.read_text(encoding="utf-8"))
        unknown = set().union(*breakout.values()) - {c["id"] for c in cases} if breakout else set()
        if unknown and len(args.sets) == 1:
            print(f"ERROR: breakout ids not in {path.name}: {sorted(unknown)}")
            return 1
        rows = []
        for case in cases:
            r = run_phrase(case, args.model, protocol)
            row = {"id": case["id"], "text": case["text"], "tuned": bool(case.get("tuned")),
                   "post_hoc": bool(case.get("post_hoc_ruling")),
                   "got": r["got"], "reasked": r["reasked"], "ok": score(case, r["got"])}
            row.update({k: case[k] for k in ("severe", "expected") if k in case})
            rows.append(row)
            want = ("unclear" if case.get("unclear") else
                    case.get("expected", "severe" if case.get("severe") else "not severe"))
            mark = "-- " if row["ok"] is None else "ok " if row["ok"] else "BAD"
            print(f"{mark} {path.name} {case['id']} want {want!r} "
                  f"got {r['got']!r}{' (re-asked)' if r['reasked'] else ''}", flush=True)
        result["sets"][path.name] = {"summary": summarise(rows, breakout), "cases": rows}
        print(path.name, json.dumps(result["sets"][path.name]["summary"]), flush=True)
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
