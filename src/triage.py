"""Triage step: symptoms + visual summary + protocol -> assessment 2.0.

The LLM proposes a level by citing protocol criteria with evidence; code
checks every citation and then decides what the patient is told
(llm/interface.md §3–4, docs/plans/llm-triage-design.md §1.4):

1. Red-flag floor (rules.red_flag_floor). If it fires, the model is not
   called at all: the result is the one fixed EMERGENCY screen.
2. Otherwise the model answers under a JSON schema whose criterion ids
   come from the protocol. A proposal is invalid if a cited criterion does
   not hold on the verified symptoms, a quote is not the patient's, or the
   level is not the most urgent level cited. Invalid -> one retry with the
   errors listed -> otherwise the rules.py result. One exception on the
   last attempt: if every citation checks out and only the level is below
   what those citations imply, the proposal is kept and code raises the
   level to them: `decided_by` "llm_raised", and
   `triage.level_raised_from` keeps the model's own level.
3. Protocol check (decision 2026-09-22 #10, option A): the structured
   criteria are evaluated in code too, and if they imply a more urgent
   level than the model chose, the level is raised. A model level below the
   protocol's is fed back once as an error first, so it gets a chance to
   cite what it missed.

Code only ever raises the model's level, never lowers it. rules.py always
runs alongside as the baseline the paper compares against.

    python src/triage.py --findings f.json --symptoms s.json [--allow-unreviewed]
"""
import argparse
import json
import sys
from pathlib import Path

import protocol as protocol_mod
from assess import rules
from interview import DEFAULT_MODEL, _is_bare, _normalize, chat

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT = (REPO_ROOT / "llm" / "prompts" / "system_triage.md").read_text(encoding="utf-8")
MAX_ATTEMPTS = 2


def _fixed_text() -> dict:
    """The user-approved wording in the protocol file (decision 2026-09-22,
    protocol v0.1 #4: the file is the single copy code reads). Read without
    validation so the web page can import this module whatever the state of
    the rest of the file; load_protocol() validates it before any triage."""
    try:
        return protocol_mod.yaml.safe_load(
            protocol_mod.PROTOCOL_PATH.read_text(encoding="utf-8")).get("fixed_text") or {}
    except (OSError, AttributeError, protocol_mod.yaml.YAMLError):
        return {}


# Wording the web page shows with every result (the brief's guardrails).
DISCLAIMER = _fixed_text().get("disclaimer", "").strip() or None
FINDING_PHRASE = _fixed_text().get("photo_finding_phrase", "").strip() or None

_protocols = {}


def load_protocol(allow_unreviewed: bool = False) -> protocol_mod.Protocol:
    """The protocol file, loaded once per process."""
    if allow_unreviewed not in _protocols:
        _protocols[allow_unreviewed] = protocol_mod.load(allow_unreviewed=allow_unreviewed)
    return _protocols[allow_unreviewed]


# --- Inputs ------------------------------------------------------------------

def visual_summary(findings: dict) -> dict:
    """What the model may know about the photos, computed rather than
    handed over: no raw confidences, only teeth rules.py would report.

    `findings` of None means there are no photos at all (complaint-only
    scoring, e.g. the ChatDoctor silver labels). That is not a retake:
    `images_usable` is null, which satisfies no criterion either way."""
    from explain import fdi_label  # late: explain imports this module
    if findings is None:
        return {"images_usable": None, "photos_taken": False, "retake_reasons": [],
                "flagged_teeth": [], "unexpected_missing_teeth": []}
    problems = rules.quality_problems(findings)
    return {
        "photos_taken": True,
        "images_usable": not problems,
        "retake_reasons": problems,
        "flagged_teeth": [{"fdi": t, "name": fdi_label(t)} for t in rules.caries_teeth(findings)],
        "unexpected_missing_teeth": [{"fdi": t, "name": fdi_label(t)}
                                     for t in rules.missing_teeth(findings)],
    }


def patient_words(messages: list) -> list:
    return [m["content"] for m in messages or [] if m.get("role") == "user"]


def output_schema(protocol: protocol_mod.Protocol, symptom_fields: list) -> dict:
    """The Ollama `format` schema; criteria come before the level, so the
    model commits to its evidence first."""
    fields = list(symptom_fields) + list(protocol_mod.VISUAL_FIELDS) + ["free_text"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["criteria_met", "level", "uncertain"],
        "properties": {
            "criteria_met": {
                "type": "array",
                "maxItems": len(protocol.criteria),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["criterion_id", "evidence"],
                    "properties": {
                        "criterion_id": {"enum": protocol.criterion_ids()},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["source", "field", "quote"],
                                "properties": {
                                    "source": {"enum": ["symptoms", "patient_words",
                                                        "visual_summary"]},
                                    "field": {"enum": fields},
                                    "quote": {"type": ["string", "null"]},
                                },
                            },
                        },
                    },
                },
            },
            "level": {"enum": list(protocol_mod.LEVELS)},
            "uncertain": {"type": "boolean"},
        },
    }


def _fence(words: list) -> str:
    # The patient cannot close the fence early by typing the tag themselves.
    clean = [w.replace("<patient_words>", "").replace("</patient_words>", "") for w in words]
    return "<patient_words>\n" + "\n---\n".join(clean) + "\n</patient_words>"


def build_messages(protocol, symptoms: dict, visual: dict, words: list) -> list:
    # A structured criterion's condition is shown with it: from the statement
    # alone the model cited "A possible cavity seen in the photo" on a
    # patient's own guess, with flagged_teeth empty (dev Test 5, 2026-09-26).
    criteria = [{"id": c.id, "level": c.level, "kind": c.kind, "statement": c.statement,
                 **({"holds_when": c.predicate} if c.kind == "structured" else {})}
                for c in protocol.criteria]
    # Answered and unanswered are shown apart, because a null buried in a JSON
    # dump is easy to read past: in a live run the model cited a criterion about
    # lingering pain on a question the patient had answered "Not sure".
    answered = {k: v for k, v in symptoms.items() if v is not None and k != "schema_version"}
    unanswered = sorted(k for k, v in symptoms.items() if v is None)
    content = "\n\n".join([
        "protocol_criteria:\n" + json.dumps(criteria, indent=1),
        "symptoms_answered:\n" + json.dumps(answered, indent=1, ensure_ascii=False),
        "symptoms_not_answered (the patient gave no answer for these; a criterion that "
        "needs one of them is NOT met and must not be cited):\n" + json.dumps(unanswered, indent=1),
        "visual_summary:\n" + json.dumps(visual, indent=1),
        "patient_words:\n" + _fence(words),
        "Apply the protocol now and output the JSON.",
    ])
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]


# --- Checking a proposal -----------------------------------------------------

def check_proposal(proposal: dict, protocol, symptoms: dict, visual: dict,
                   words: list) -> tuple:
    """(errors, reasons, implied). errors is empty when the proposal may be
    used; reasons are the cited criteria with their checked evidence;
    implied is the level those criteria imply, or None if a citation or the
    level itself failed a check."""
    errors, reasons, levels = [], [], []
    said = _normalize(" ".join(words))
    if proposal.get("level") not in protocol_mod.LEVELS:
        return [f"level {proposal.get('level')!r} is not a triage level"], [], None

    seen = set()
    for cited in proposal.get("criteria_met") or []:
        cid = cited.get("criterion_id")
        if cid in seen:
            continue
        seen.add(cid)
        try:
            criterion = protocol.criterion(cid)
        except KeyError:
            errors.append(f"{cid}: not a protocol criterion")
            continue
        evidence, ok = [], True
        for item in cited.get("evidence") or []:
            source, name, quote = item.get("source"), item.get("field"), item.get("quote")
            if quote and not (_normalize(quote) and _normalize(quote) in said):
                if source == "patient_words":
                    errors.append(f"{cid}: quote {quote!r} is not in the patient's words")
                    ok = False
                    continue
                # A symptom or photo citation rests on its checked value, not
                # the quote; an unverifiable quote is dropped, never kept.
                quote = None
            entry = {"source": source, "field": name}
            if source == "symptoms":
                if (symptoms or {}).get(name) is None:
                    errors.append(f"{cid}: symptom {name!r} is unanswered, so it is not evidence")
                    ok = False
                    continue
                entry["value"] = symptoms[name]
            elif source == "visual_summary":
                entry["value"] = (visual or {}).get(name)
            if quote:
                entry["quote"] = quote
            evidence.append(entry)

        if criterion.kind == "structured":
            if not criterion.holds(symptoms, visual):
                errors.append(f"{cid}: its condition does not hold on the verified "
                              f"symptoms and photo summary ({criterion.statement})")
                ok = False
        else:
            quotes = [e.get("quote") for e in evidence if e["source"] == "patient_words"]
            if not any(q and not _is_bare(q) for q in quotes):
                errors.append(f"{cid}: a narrative criterion needs the patient's own "
                              "words as a quote")
                ok = False
        if ok:
            levels.append(criterion.level)
            reasons.append({"criterion_id": cid, "statement": criterion.statement,
                            "evidence": evidence})

    if errors:
        return errors, reasons, None
    implied = protocol_mod.most_urgent(levels) or "ROUTINE"
    if proposal["level"] != implied:
        errors.append(f"level {proposal['level']} does not match the criteria cited, "
                      f"which imply {implied}")
    return errors, reasons, implied


def _baseline_reason(baseline: dict) -> dict:
    """A last-resort reason, when the level came from rules.py and no protocol
    criterion sits at it. The patient is never shown an urgency with no why."""
    return {"criterion_id": f"rules:{baseline['rule_id']}",
            "statement": baseline["rule_reason"].replace("_", " ").replace(":", ": "),
            "evidence": []}


def _code_reasons(criteria: list, symptoms: dict, visual: dict) -> list:
    """Reasons written by code, when the floor, the protocol check or the
    fallback decides: each criterion with the answered fields it reads."""
    reasons = []
    for c in criteria:
        evidence = []
        for name in c.fields():
            if name in protocol_mod.VISUAL_FIELDS:
                if visual.get(name):
                    evidence.append({"source": "visual_summary", "field": name,
                                     "value": visual[name]})
            elif symptoms.get(name) is not None:
                evidence.append({"source": "symptoms", "field": name, "value": symptoms[name]})
        reasons.append({"criterion_id": c.id, "statement": c.statement, "evidence": evidence})
    return reasons


# --- The step ------------------------------------------------------------------

def _ask_model(llm, protocol, symptoms, visual, words, schema, log: dict):
    """Up to MAX_ATTEMPTS proposals. Returns (proposal, reasons, implied) for
    the first usable one, or (None, [], None) if none was usable. implied is
    the level the proposal's valid citations imply; it is below the model's
    own level only when the last attempt was kept for code to raise."""
    messages = build_messages(protocol, symptoms, visual, words)
    protocol_level = protocol.protocol_level(symptoms, visual)
    last_valid = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log["attempts"] = attempt
        raw = llm(messages, schema)
        try:
            proposal = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            errors, reasons, implied = [f"output is not JSON: {str(raw)[:80]!r}"], [], None
        else:
            errors, reasons, implied = check_proposal(proposal, protocol, symptoms, visual, words)
        log["validation_errors"] += [f"attempt {attempt}: {e}" for e in errors]
        # Every citation checked out and only the level is below them: fed
        # back like any error first; on the last attempt the proposal is kept
        # and code raises the level. A level above them is never kept, since
        # code may not lower. (Dev Test 5, 2026-09-26: 15/15 fallbacks were
        # this case on the retry.)
        if (errors and implied and attempt == MAX_ATTEMPTS
                and protocol_mod.LEVEL_RANK[proposal["level"]] > protocol_mod.LEVEL_RANK[implied]):
            log["validation_errors"].append(f"attempt {attempt}: kept, level raised in code "
                                            f"from {proposal['level']} to {implied}")
            errors = []
        if not errors:
            last_valid = (proposal, reasons, implied)
            missed = protocol_mod.LEVEL_RANK[implied] > protocol_mod.LEVEL_RANK[protocol_level]
            if not missed:
                return last_valid
            # Option A: say which criteria were missed, once; raise in code after.
            # Only criteria that could raise the level are worth naming: a
            # missed ROUTINE criterion cannot change the outcome, and listing
            # it sent the model back for nothing (measured 2026-09-23).
            cited_ids = {r["criterion_id"] for r in reasons}
            unmet = [c.id for c in protocol.met(symptoms, visual)
                     if c.id not in cited_ids
                     and protocol_mod.LEVEL_RANK[c.level]
                     <= protocol_mod.LEVEL_RANK[protocol_level]]
            errors = [f"these criteria hold on the given facts but were not cited: "
                      f"{', '.join(unmet)}"]
            log["validation_errors"] += [f"attempt {attempt}: {errors[0]}"]
        messages = messages + [
            {"role": "assistant", "content": str(raw)},
            {"role": "user", "content": "Your answer was rejected:\n- " + "\n- ".join(errors)
                                        + "\nCorrect it and output the JSON again. Leave out "
                                        "any criterion rejected above, and set `level` again "
                                        "to the most urgent level among the criteria you "
                                        "still list."},
        ]
    return last_valid or (None, [], None)


def _default_llm(model: str):
    return lambda messages, schema: chat(messages, model, schema=schema)


def assess(findings: dict, symptoms: dict = None, messages: list = None,
           model: str = DEFAULT_MODEL, allow_unreviewed: bool = False,
           protocol=None, llm=None) -> dict:
    """The assessment 2.0 object for one screening (llm/interface.md §4).

    messages: the interview transcript (only user turns are used).
    llm: a callable (messages, schema) -> str, for tests; defaults to Ollama.
    """
    symptoms = dict(symptoms or {})
    findings = findings if findings is None else (findings or {})
    protocol = protocol or load_protocol(allow_unreviewed)
    llm = llm or _default_llm(model)
    visual = visual_summary(findings)
    words = patient_words(messages)
    baseline = rules.assess(findings or {}, symptoms)
    floor = rules.red_flag_floor(symptoms)
    met = protocol.met(symptoms, visual)
    protocol_level = protocol.protocol_level(symptoms, visual)
    log = {"protocol_version": protocol.version,
           "protocol_review_status": protocol.review_status,
           "model": None, "llm_proposed": None, "level_raised_from": None,
           "llm_valid": False, "attempts": 0,
           "validation_errors": [], "protocol_level": protocol_level,
           "floor": floor, "overridden_by": None}

    if floor["level"]:
        # A red flag: the fixed emergency screen, without waiting on a model.
        level, decided_by = "EMERGENCY", "red_flag_floor"
        reasons = _code_reasons([c for c in met if c.level == "EMERGENCY"], symptoms, visual)
        cited = [c for c in met if c.level == "EMERGENCY"]
        if not reasons:   # a protocol without a criterion for this flag
            reasons = [{"criterion_id": "red_flag_floor",
                        "statement": "A red flag was reported: "
                                     + ", ".join(f.replace("_", " ") for f in floor["red_flags"]),
                        "evidence": [{"source": "symptoms", "field": f, "value": True}
                                     for f in floor["red_flags"]]}]
    else:
        log["model"] = model
        schema = output_schema(protocol, protocol.symptom_fields)
        proposal, reasons, implied = _ask_model(llm, protocol, symptoms, visual, words,
                                                schema, log)
        if proposal is not None:
            log["llm_valid"] = True
            log["llm_proposed"] = proposal["level"]   # the model's own level, even if raised
            level = protocol_mod.most_urgent([proposal["level"], implied, protocol_level])
            decided_by = "llm"
            if implied != proposal["level"]:
                # Raised to the model's own valid citations. Not decided_by
                # "llm": Test 5 reads that as the model's own level deciding.
                # overridden_by stays for a source that raised past the citations.
                log["level_raised_from"] = proposal["level"]
                decided_by = "llm_raised"
            if level != implied:
                decided_by = log["overridden_by"] = "protocol_check"
                cited_ids = {r["criterion_id"] for r in reasons}
                reasons = reasons + _code_reasons([c for c in met if c.id not in cited_ids],
                                                 symptoms, visual)
            cited = [protocol.criterion(r["criterion_id"]) for r in reasons]
        else:
            fallback = None if baseline["urgency"] == "RETAKE" else baseline["urgency"]
            level = protocol_mod.most_urgent([fallback, protocol_level])
            decided_by = "fallback_rules" if level == fallback else "protocol_check"
            reasons = _code_reasons([c for c in met if c.level == level], symptoms, visual)
            cited = met
            if not reasons:
                reasons = [_baseline_reason(baseline)]

    retake_required = visual["photos_taken"] and not visual["images_usable"]
    log["level"] = level   # the composed level, before the photo-quality step
    urgency = level
    if retake_required and level in ("SOON", "ROUTINE"):
        urgency = "RETAKE"  # symptoms that need care are never hidden behind a bad photo
    return {
        "schema_version": "2.0",
        "urgency": urgency,
        "urgency_rank": rules.URGENCY_RANK[urgency],
        "headline": rules.HEADLINES["RETAKE"] if urgency == "RETAKE"
                    else protocol.headlines[urgency],
        "flagged_teeth": [] if urgency == "RETAKE" or findings is None
                         else rules.caries_teeth(findings),
        "retake_required": retake_required,
        "limitations": protocol.limitations,
        "safety_net": protocol.safety_net,
        "emergency_route": (protocol.route(cited) or "either") if urgency == "EMERGENCY" else None,
        "decided_by": decided_by,
        "reasons": reasons,
        "triage": log,
        "rules_baseline": {"urgency": baseline["urgency"], "rule_id": baseline["rule_id"],
                           "rule_reason": baseline["rule_reason"]},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--symptoms")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--allow-unreviewed", action="store_true")
    args = ap.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    symptoms = json.loads(Path(args.symptoms).read_text(encoding="utf-8")) if args.symptoms else {}
    try:
        result = assess(findings, symptoms, model=args.model,
                        allow_unreviewed=args.allow_unreviewed)
    except protocol_mod.UnreviewedProtocol as exc:
        print(f"refused: {exc}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
