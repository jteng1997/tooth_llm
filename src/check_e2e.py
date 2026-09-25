"""Test 5, end-to-end set: checklist clicks + scripted chat -> real interview
and extraction -> triage, with the spec §3 error attribution.

    python src/check_e2e.py --mock --placeholder-text           # no model, no P7 text
    python src/check_e2e.py --model qwen3:14b --confirm-heldout # the real run (task #5)

Each key (labels/heldout/e2e_keys.json) gives the checklist clicks (its
`symptoms`) and, after P7, the patient's `opening` and `script` (one answer
per chat question). The production Interview runs the plan: checklist A,
checklist B, then the chat questions it decides to ask, each answered from
the script; a re-asked question gets the same scripted answer again, and a
question the script lacks gets "I'm not sure." (logged). Its symptoms, the
transcript and the photo summary go to triage.assess(), and every system is
scored against the key with check_triage's scoring.

The app has no free-text opening before checklist A. --opening drop (default)
matches production: the opening is not seen. --opening prepend puts it in as
a first patient message, which production never does.

Attribution (spec §3), proposed by code for every case that misses the key,
exactly one bucket, first failure in the chain wins; research-pm confirms it:
  1 interview   a question the key expects was never put, or the key needs a
                narrative fact that only the (dropped) opening carries
  2 extraction  a symptom field differs from the key
  3 triage      every field matches the key, the level does not
  4 protocol gap  never proposed by code; research-pm's call
Severity block (pre-declared 2026-09-26, reported after the above): false
severe / missed severe over the cases that reached the chat (as in
check_symptoms), and, where pain_severity differs from the key, how often the
level moved up or down from the level the key's own symptoms give.
--mock replaces both models: an oracle extractor that returns the key's value
for every answered chat question (quoting the patient's reply), and a triage
model that always proposes ROUTINE with no criteria, so the final level is
code's. A mock run is a harness check, not a scoring, and is never logged.
"""
import argparse
import copy
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_symptoms as cs  # noqa: E402
import check_triage as ct  # noqa: E402
import interview as interview_mod  # noqa: E402

E2E_KEYS = ct.REPO_ROOT / "labels" / "heldout" / "e2e_keys.json"
NOT_SURE = "I'm not sure."
MAX_STEPS = 60
BUCKETS = {1: "interview", 2: "extraction", 3: "triage", 4: "protocol gap"}
SKIP_FIELDS = ("schema_version", "notes")
MOCK_TRIAGE_REPLY = '{"criteria_met": [], "level": "ROUTINE", "uncertain": false}'


# --- Mocks and placeholder text (harness checks only) -------------------------------

def oracle_extractor(key: dict, protocol):
    """An extractor that is right whenever the patient has answered: for each
    chat field, the key's value, quoting the patient's reply to the question
    that asks for it; null before that reply exists."""
    asks = {f: q for q in protocol.questions if q.input == "chat" for f in q.fields}

    def llm(messages, schema):
        out = {"notes": {"value": None, "quote": None}}
        for field in schema["required"]:
            if field == "notes":
                continue
            q = asks.get(field)
            reply = None
            for prev, msg in zip(messages, messages[1:]):
                if (q is not None and prev["role"] == "assistant" and q.text in prev["content"]
                        and msg["role"] == "user"):
                    reply = msg["content"]
            value = key["symptoms"].get(field)
            out[field] = ({"value": value, "quote": reply} if reply and value is not None
                          else {"value": None, "quote": None})
        return json.dumps(out)
    return llm


def mock_triage(messages, schema):
    return MOCK_TRIAGE_REPLY


PLACEHOLDER = {
    "Q10": lambda s: {"helped": "I took painkillers and they helped.",
                      "not_helped": "I took painkillers but they did not help.",
                      "not_tried": "I have not taken anything for it."}.get(s.get("pain_relief_effect")),
    "Q11": lambda s: {"mild": "It is mild.", "moderate": "It is fairly bad.",
                      "severe": "It is so bad I cannot sleep or eat."}.get(s.get("pain_severity")),
    "Q12": lambda s: _triggers(s.get("pain_triggers")),
    "Q17": lambda s: ({"front": "At the front."}.get(s.get("location"))
                      or (f"In the {s['location'].replace('_', ' ')}." if s.get("location") else None)),
    "Q18": lambda s: (None if s.get("duration_days") is None else "Since yesterday."
                      if s["duration_days"] == 1 else f"For {s['duration_days']} days."),
}


def _triggers(items):
    if not items:
        return None
    words = {"cold": "cold things", "hot": "hot things", "sweet": "sweet things",
             "biting": "when I bite", "spontaneous": "it comes on by itself",
             "unknown": "I can't tell what sets it off"}
    return "It hurts with " + " and ".join(words[i] for i in items) + "."


def placeholder_text(key: dict) -> dict:
    """Stand-in `opening` and `script` built from the key, so the harness can
    run before P7. Never scored."""
    s = key["symptoms"]
    script = {q: (PLACEHOLDER[q](s) or NOT_SURE)
              for q in key.get("expected_questions", []) if q in PLACEHOLDER}
    return {"opening": " ".join(key["facts"]), "script": script}


# --- One case ----------------------------------------------------------------------------

def checklist_answers(step: dict, symptoms: dict, protocol) -> dict:
    """The key's clicks for an open checklist. A row the key leaves null where
    the row offers no 'Not sure' is a key/interview mismatch, not a default."""
    rows = {q.id: q for q in protocol.questions}
    answers = {}
    for item in step["items"]:
        value = symptoms.get(item["field"])
        if not rows[item["id"]].allows(value):
            raise ValueError(f"key has {value!r} for checklist row {item['id']} "
                             f"({item['field']}), which the row does not offer")
        answers[item["id"]] = value
    return answers


def run_case(key: dict, text: dict, protocol, extract_llm, triage_llm, model: str,
             opening: str = "drop") -> dict:
    import triage
    iv = interview_mod.Interview(model, allow_unreviewed=True, protocol=protocol, llm=extract_llm)
    if opening == "prepend" and text.get("opening"):
        iv.messages.append({"role": "user", "content": text["opening"]})
        iv.reply_to.append(None)
    step = iv.start()
    shown, asked, reasked, unscripted = [], [], [], []
    for _ in range(MAX_STEPS):
        if step["type"] == "done":
            break
        if step["type"] == "checklist":
            shown += [item["id"] for item in step["items"]]
            step = iv.submit_checklist(step["group"], checklist_answers(step, key["symptoms"], protocol))
            continue
        qid = step["id"]
        if qid in asked:
            reasked.append(qid)
        else:
            asked.append(qid)
        answer = text.get("script", {}).get(qid)
        if answer is None:
            unscripted.append(qid)
            answer = NOT_SURE
        step = iv.reply(answer)
    else:
        raise RuntimeError(f"{key['id']}: interview did not finish in {MAX_STEPS} steps")
    symptoms = step["symptoms"]
    vs = key["visual_summary"]
    visual = {"images_usable": vs["images_usable"], "flagged_teeth": ct._fdi_list(vs["flagged_teeth"]),
              "unexpected_missing_teeth": ct._fdi_list(vs["unexpected_missing_teeth"])}
    a = triage.assess(ct.findings_from_visual(visual), copy.deepcopy(symptoms), iv.messages,
                      model=model, allow_unreviewed=True, protocol=protocol, llm=triage_llm)
    t = a["triage"]
    return {
        "id": key["id"], "key_level": key["key_level"], "boundary": key["boundary"],
        "images_usable": vs["images_usable"],
        "questions_shown": shown + asked, "chat_asked": asked, "reasked": reasked,
        "unscripted": unscripted, "red_flag_stop": step.get("red_flag"),
        "symptoms": symptoms, "transcript": [m for m in iv.messages if m["role"] != "system"],
        "final": a["urgency"], "llm_proposed": t["llm_proposed"],
        "protocol_check": t["protocol_level"], "rules": a["rules_baseline"]["urgency"],
        "decided_by": a["decided_by"], "llm_valid": t["llm_valid"], "attempts": t["attempts"],
        "level_raised_from": t.get("level_raised_from"),
        "rejections": len(ct.rejection_lines(t["validation_errors"])),
        "model_called": t["model"] is not None,
        "protocol_on_key_symptoms": protocol.protocol_level(key["symptoms"], visual),
    }


# --- Attribution -------------------------------------------------------------------------

def field_diffs(key_symptoms: dict, got: dict) -> list:
    fields = sorted((set(key_symptoms) | set(got)) - set(SKIP_FIELDS))
    return [{"field": f, "key": key_symptoms.get(f), "got": got.get(f)} for f in fields
            if not _same(f, key_symptoms.get(f), got.get(f))]


def _same(field, a, b) -> bool:
    if field in ("pain_triggers", "swelling_features", "trauma_features") and a and b:
        return set(a) == set(b)
    return a == b


def attribute(key: dict, result: dict, protocol, opening: str) -> dict:
    """The proposed §3 bucket for a case whose final level misses the key,
    with the evidence for each bucket that applies."""
    missing = [q for q in key.get("expected_questions", []) if q not in result["questions_shown"]]
    extra = [q for q in result["questions_shown"] if q not in key.get("expected_questions", [])]
    # P7 puts the facts in the opening, and each chat answer answers only its
    # own question, so with the opening dropped a narrative fact has no turn.
    narrative = [c for c in key["criteria_met"] if protocol.criterion(c).kind == "narrative"]
    no_turn = bool(narrative) and opening == "drop"
    diffs = field_diffs(key["symptoms"], result["symptoms"])
    evidence = {"missing_questions": missing, "extra_questions": extra,
                "narrative_without_a_turn": narrative if no_turn else [],
                "field_diffs": diffs}
    if missing or no_turn:
        bucket = 1
    elif diffs:
        bucket = 2
    else:
        bucket = 3
    return {"proposed_bucket": bucket, "proposed": BUCKETS[bucket], "research_pm_bucket": None,
            "evidence": evidence}


# --- Whole run ---------------------------------------------------------------------------

def evaluate(keys: list, texts: dict, protocol, model: str, extract_llm_for, triage_llm,
             opening: str = "drop") -> dict:
    """extract_llm_for(key) -> the extraction callable for that case (None = Ollama)."""
    results, attributions = [], {}
    for key in keys:
        r = run_case(key, texts[key["id"]], protocol, extract_llm_for(key), triage_llm, model, opening)
        results.append(r)
        if r["final"] != key["key_level"]:
            attributions[key["id"]] = attribute(key, r, protocol, opening)
    systems = {}
    for s in ct.SYSTEMS:
        rows = [{"id": r["id"], "ref": r["key_level"], "ref_expected": r["key_level"],
                 "boundary": r["boundary"], "ambiguous": False, "images_usable": r["images_usable"],
                 "got": r[s]} for r in results]
        systems[s] = ct.summarise(rows, s)
    by_id = {k["id"]: k for k in keys}
    reached = [r for r in results if r["chat_asked"]]
    chat_fields = [f for q in protocol.questions if q.input == "chat" for f in q.fields]
    wrong = Counter(d["field"] for r in reached for d in field_diffs(by_id[r["id"]]["symptoms"], r["symptoms"])
                    if d["field"] in chat_fields)
    summary = {
        "n_cases": len(results), "opening": opening, "model": model,
        "protocol_version": getattr(protocol, "version", None), "systems": systems,
        "comparisons": {f"{a}_vs_{b}": ct.paired(systems[a], systems[b]) for a, b in ct.COMPARISONS},
        "code_ceiling": ct.code_ceiling(systems),
        "attribution": {"proposed": dict(Counter(a["proposed"] for a in attributions.values())),
                        "n_misses": len(attributions), "cases": attributions},
        "extraction": {"cases_reaching_chat": len(reached), "fields": chat_fields,
                       "cells": len(reached) * len(chat_fields),
                       "wrong_cells": sum(wrong.values()), "wrong_by_field": dict(wrong)},
        "interview": {"cases_with_missing_questions": sum(
                          any(q not in r["questions_shown"] for q in by_id[r["id"]].get("expected_questions", []))
                          for r in results),
                      "cases_with_extra_questions": sum(
                          any(q not in by_id[r["id"]].get("expected_questions", []) for q in r["questions_shown"])
                          for r in results),
                      "reasked": sum(len(r["reasked"]) for r in results),
                      "unscripted": sum(len(r["unscripted"]) for r in results)},
        "severity": severity_block(results, by_id),
        "triage_calls": triage_calls(results),
        "cases": results,
    }
    return summary


def triage_calls(results: list) -> dict:
    """Report-only: over the cases whose triage called the model, how often
    its own level decided (decided_by 'llm' only) and how often code kept it
    with the level raised to its own citations."""
    called = [r for r in results if r["model_called"]]
    n = len(called)
    decided = sum(r["decided_by"] == "llm" for r in called)
    raised = [r["id"] for r in called if r.get("level_raised_from") is not None]
    fallback = sum(not r["llm_valid"] for r in called)
    llm_raised = sum(r["decided_by"] == "llm_raised" for r in called)
    old_rule = fallback + len(raised)       # spec 9.9: the rule as first registered
    return {"n": n, "llm_decided": decided, "llm_decided_ci95": ct.clopper_pearson(decided, n),
            "level_raised": len(raised), "level_raised_ids": raised,
            "level_raised_ci95": ct.clopper_pearson(len(raised), n),
            "llm_raised": llm_raised, "llm_raised_ci95": ct.clopper_pearson(llm_raised, n),
            "fallback_rules": fallback, "fallback_rules_ci95": ct.clopper_pearson(fallback, n),
            "fallback_as_first_registered": old_rule,
            "fallback_as_first_registered_ci95": ct.clopper_pearson(old_rule, n),
            "valid": n - fallback,
            "rejections": sum(r.get("rejections", 0) for r in called)}


def severity_block(results: list, by_id: dict) -> dict:
    """Pre-declared 2026-09-26, before held-out Test 5; an addition, no
    pre-registered metric depends on it. pain_severity errors by direction
    over the cases that reached the chat, and the cases whose level differs
    from the level the key's own symptoms give (protocol_on_key_symptoms)
    while pain_severity differs from the key, split up/down."""
    reached = [r for r in results if r["chat_asked"]]
    errors = cs.severity_errors(
        [(r["id"], by_id[r["id"]]["symptoms"].get("pain_severity"), r["symptoms"].get("pain_severity"))
         for r in reached], ct.clopper_pearson)
    differs = [r for r in results
               if by_id[r["id"]]["symptoms"].get("pain_severity") != r["symptoms"].get("pain_severity")]
    shift = {"n_severity_differs": len(differs)}
    for system in ("final", "protocol_check"):
        up, down, other = [], [], []
        for r in differs:
            ref, got = r["protocol_on_key_symptoms"], r[system]
            if got not in ct.ORDER:          # RETAKE or no answer: not on the scale
                other.append(r["id"])
            elif ct.ORDER[got] < ct.ORDER[ref]:
                up.append(r["id"])
            elif ct.ORDER[got] > ct.ORDER[ref]:
                down.append(r["id"])
        shift[system] = {"up": len(up), "up_ids": up, "down": len(down), "down_ids": down,
                         "not_a_level": len(other), "not_a_level_ids": other}
    return {"errors": errors, "level_shift": shift}


def print_report(summary: dict, mock: bool) -> None:
    if mock:
        print("MOCK RUN: harness check only, not a scoring; not logged")
    print(f"\nend-to-end: {summary['n_cases']} cases, opening {summary['opening']}")
    print(f"{'system':<15}{'n':>4}{'under':>7}{'severe':>8}{'missed EM':>11}{'over':>6}"
          f"{'exact':>8}{'kappa':>8}  kappa 95% CI")
    for name, s in summary["systems"].items():
        lo, hi = s["kappa_ci95"]
        print(f"{name:<15}{s['n_scored']:>4}{s['under']:>7}{s['severe_under']:>8}"
              f"{s['missed_emergency']:>7}/{s['n_key_emergency']:<3}{s['over']:>6}"
              f"{s['agree']:>4}/{s['n_scored']:<3}{s['kappa_linear']:>8.3f}  [{lo:.3f}, {hi:.3f}]")
    iv, ex = summary["interview"], summary["extraction"]
    print(f"interview: cases with a missing question {iv['cases_with_missing_questions']}/"
          f"{summary['n_cases']}, with an extra question {iv['cases_with_extra_questions']}, "
          f"re-asks {iv['reasked']}, unscripted questions {iv['unscripted']}")
    print(f"extraction: {ex['wrong_cells']}/{ex['cells']} chat-field cells differ from the key "
          f"over {ex['cases_reaching_chat']} cases that reached the chat {ex['wrong_by_field']}")
    att = summary["attribution"]
    print(f"attribution of {att['n_misses']} misses (proposed by code, research-pm confirms): "
          f"{att['proposed']}")
    for cid, a in att["cases"].items():
        ev = a["evidence"]
        why = "; ".join(x for x in (
            f"missing {ev['missing_questions']}" if ev["missing_questions"] else "",
            f"narrative {ev['narrative_without_a_turn']} with no turn to type it"
            if ev["narrative_without_a_turn"] else "",
            "fields " + ", ".join(f"{d['field']} key {d['key']!r} got {d['got']!r}" for d in ev["field_diffs"])
            if ev["field_diffs"] else "") if x)
        print(f"  {cid}: {a['proposed']}" + (f" ({why})" if why else ""))
    for name, c in summary["comparisons"].items():
        if name == "final_vs_rules":
            print(f"final vs rules (n = {c['n_common']}): b {c['only_first_under']}, c {c['only_second_under']}"
                  + ("; underpowered: fewer than 10 discordant pairs, so no test of a difference is reported"
                     if c["underpowered"] else f"; exact McNemar p = {c['p_exact']:.3g}"))
    tc = summary.get("triage_calls")
    if tc:
        print(f"triage calls {tc['n']}: the model's own level decided {tc['llm_decided']}/{tc['n']} "
              f"{ct._ci(tc['llm_decided_ci95'])}; level raised in code to its own citations "
              f"{tc['level_raised']}/{tc['n']} {ct._ci(tc['level_raised_ci95'])}; "
              f"rejected attempts {tc['rejections']}")
        if "fallback_rules" in tc:
            n = tc["n"]
            print(f"  valid output {tc['valid']}/{n}, of which {tc['level_raised']} kept with the level "
                  f"raised in code; fallback_rules (the bar, <= 1%) {tc['fallback_rules']}/{n} "
                  f"{ct._ci(tc['fallback_rules_ci95'])}; llm_raised {tc['llm_raised']}/{n} "
                  f"{ct._ci(tc['llm_raised_ci95'])}; sum, the rule as first registered "
                  f"{tc['fallback_as_first_registered']}/{n} {ct._ci(tc['fallback_as_first_registered_ci95'])}")
            print(f"  {ct.FALLBACK_RULE_NOTE}")
    sev = summary["severity"]
    cs.print_severity_errors(sev["errors"], "cases that reached the chat")
    sh = sev["level_shift"]
    print(f"  level vs the key's own symptoms (protocol on the key), in the "
          f"{sh['n_severity_differs']} cases whose pain_severity differs from the key:")
    for system in ("final", "protocol_check"):
        x = sh[system]
        print(f"    {system:<15} up {x['up']}/{sh['n_severity_differs']} {x['up_ids'] or ''}  "
              f"down {x['down']}/{sh['n_severity_differs']} {x['down_ids'] or ''}"
              + (f"  not a level {x['not_a_level']} {x['not_a_level_ids']}" if x["not_a_level"] else ""))
    print("\nThese numbers must be reported with:")
    for i, text in enumerate(ct.caveats(summary.get("protocol_version"))[:2], 1):
        print(f"  {i}. {text}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--keys", default=str(E2E_KEYS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--opening", choices=["drop", "prepend"], default="drop")
    ap.add_argument("--mock", action="store_true", help="oracle extractor + ROUTINE triage stub")
    ap.add_argument("--placeholder-text", action="store_true",
                    help="build opening/script from the key (only with --mock)")
    ap.add_argument("--confirm-heldout", action="store_true")
    ap.add_argument("--rerun-reason")
    ap.add_argument("--ran-by", default="qa-engineer")
    ap.add_argument("--json")
    args = ap.parse_args()
    if args.placeholder_text and not args.mock:
        print("REFUSED: placeholder text is for harness checks with --mock only")
        return 1

    path = Path(args.keys)
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = data["keys"]
    protocol, perr = ct.load_protocol()
    if perr:
        print(f"ERROR: protocol not loaded ({perr})")
        return 1
    texts = {}
    for k in keys:
        if args.placeholder_text:
            texts[k["id"]] = placeholder_text(k)
        else:
            texts[k["id"]] = {"opening": k.get("opening"), "script": k.get("script") or {}}
    if not args.placeholder_text:
        chat_ids = {key for kind, key in interview_mod.QUESTION_PLAN if kind == "chat"}
        needs = [k["id"] for k in keys
                 if any(q in chat_ids for q in k.get("expected_questions", [])) and not k.get("script")]
        if needs:
            print(f"ERROR: {len(needs)} keys expect chat questions but have no P7 script")
            return 1

    if args.mock:
        model = "mock"
        extract_for, triage_llm = (lambda k: oracle_extractor(k, protocol)), mock_triage
    else:
        from interview import DEFAULT_MODEL
        model = args.model or DEFAULT_MODEL
        extract_for, triage_llm = (lambda k: None), None
    try:
        split = ct.key_file_split(data.get("_meta", {}), path)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    cfg = ct.configuration("llm", model, protocol) if not args.mock else None
    prior = []
    if split == "heldout" and not args.mock:
        cfg = e2e_configuration(cfg, args.opening)
        prior = ct.prior_runs(cfg["fingerprint"], ct._sha256(path))
        refusal = ct.heldout_refusal("llm", args.confirm_heldout, prior, args.rerun_reason)
        if refusal:
            print(f"REFUSED: {refusal}")
            return 2

    summary = evaluate(keys, texts, protocol, model, extract_for, triage_llm, args.opening)
    summary.update(mock=args.mock, placeholder_text=args.placeholder_text, keys_file=str(path),
                   configuration=cfg)
    print_report(summary, args.mock)
    out = Path(args.json) if args.json else ct.OUT_DIR / (
        f"e2e_{path.stem}_{model.replace(':', '_')}_{args.opening}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {out}")
    if split == "heldout" and not args.mock:
        ct.append_runlog({"date": datetime.datetime.now().isoformat(timespec="seconds"),
                          "ran_by": args.ran_by, "cases_file": str(path),
                          "cases_sha256": ct._sha256(path), "n_cases": len(keys),
                          "reference": "key", "configuration": cfg, "git": ct._git_state(),
                          "rerun": bool(prior), "rerun_of": [e["date"] for e in prior],
                          "rerun_reason": args.rerun_reason, "stability_ids": [],
                          "output": str(out), "headline": ct.headline(summary)})
    return 0


def e2e_configuration(cfg: dict, opening: str) -> dict:
    """The triage configuration plus what the end-to-end run adds: the
    extraction prompt and the opening mode, all inside the fingerprint."""
    import hashlib
    blob = interview_mod.SYSTEM_PROMPT + "\n" + interview_mod.EXTRACTION_INSTRUCTION
    cfg = {k: v for k, v in cfg.items() if k != "fingerprint"}
    cfg.update(system="e2e", opening=opening,
               extraction_prompt_sha256=hashlib.sha256(blob.encode()).hexdigest())
    cfg["fingerprint"] = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    return cfg


if __name__ == "__main__":
    sys.exit(main())
