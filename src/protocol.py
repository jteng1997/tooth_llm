"""Triage protocol: load llm/protocol/triage_protocol.yaml and evaluate it.

The protocol content (criteria, questions, headlines) belongs to research-pm
and the reviewing dentist; this module only reads and checks it. Format:
docs/plans/llm-triage-design.md §3.1.

    python src/protocol.py            # load, validate, print a summary

Structured criteria carry a predicate over symptom and visual_summary fields
in a small fixed grammar, evaluated here rather than with eval():

    expr   := term ("OR" term)*
    term   := factor ("AND" factor)*
    factor := "(" expr ")" | field "==" lit | field "!=" lit
            | field "contains" lit | field "non-empty" | field "is" "null" | field
    lit    := true | false | a bare word | "a quoted string" | a number

A bare `field` means `field == true`. An unanswered field (null) satisfies
no comparison at all, `!=` included: an unanswered question is never
evidence for a criterion. The one exception is `field is null`, which holds
exactly when the field is unanswered (null or absent), so a criterion can
name a blank as a reason on its own (user, 2026-09-26: pain with the relief
question unanswered is URGENT). A floor criterion may not use it: the floor
fires on a reported red flag, never on a missing answer.
"""
import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = REPO_ROOT / "llm" / "protocol" / "triage_protocol.yaml"
SYMPTOM_SCHEMA_PATH = REPO_ROOT / "llm" / "prompts" / "symptoms_schema.json"
UNREVIEWED = "DRAFT-UNREVIEWED"

LEVELS = ("EMERGENCY", "URGENT", "SOON", "ROUTINE")
LEVEL_RANK = {"EMERGENCY": 1, "URGENT": 2, "SOON": 3, "ROUTINE": 4}
ROUTES = ("medical", "dental", "either")
KINDS = ("structured", "narrative")
INPUTS = ("yesno_checklist", "chat")
OPTIONS = ("yes", "no", "not_sure")  # checklist answers; not_sure records null
# What the page shows for each option, and the value it submits. "Not sure"
# submits null, which records the field as unanswered.
# The value each option submits. "Not sure" submits null, which records the
# field as unanswered. The patient-facing labels come from the protocol's
# fixed_text.option_labels, so every word a patient reads lives in the file a
# dentist signs off; these are only the fallback when the file omits them.
OPTION_VALUES = {"yes": True, "no": False, "not_sure": None}
DEFAULT_OPTION_LABELS = {"yes": "Yes", "no": "No", "not_sure": "Not sure"}
FIXED_TEXT = ("disclaimer", "photo_finding_phrase")  # required keys of fixed_text

# What code computes from findings for the triage step (interface.md §3.1).
VISUAL_FIELDS = {"flagged_teeth": {"type": "array"},
                 "unexpected_missing_teeth": {"type": "array"},
                 "images_usable": {"type": "boolean"}}


class ProtocolError(ValueError):
    pass


class UnreviewedProtocol(RuntimeError):
    pass


def most_urgent(levels) -> str | None:
    """The most urgent of the given levels (None-safe); None if there are none."""
    present = [lv for lv in levels if lv]
    return min(present, key=LEVEL_RANK.__getitem__) if present else None


# --- Predicate grammar ------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:(\()|(\))|(==|!=)|("(?:[^"\\]|\\.)*")|([A-Za-z_][\w.\-]*)|(-?\d+))')
_KEYWORDS = {"AND", "OR", "contains", "non-empty", "is"}
_OP_WORDS = ("contains", "non-empty", "is")


def _tokenize(text: str) -> list:
    tokens, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ProtocolError(f"cannot parse predicate at {text[pos:]!r}: {text!r}")
        lparen, rparen, op, string, word, number = m.groups()
        if lparen or rparen:
            tokens.append(("punct", lparen or rparen))
        elif op:
            tokens.append(("op", op))
        elif string:
            tokens.append(("lit", json.loads(string)))
        elif number:
            tokens.append(("lit", int(number)))
        elif word in _KEYWORDS:
            tokens.append(("op" if word in _OP_WORDS else "bool", word))
        else:
            tokens.append(("word", word))
        pos = m.end()
    return tokens


def _literal(token) -> object:
    kind, value = token
    if kind == "lit":
        return value
    if kind == "word":
        return {"true": True, "false": False, "null": None}.get(value, value)
    raise ProtocolError(f"expected a value, got {value!r}")


class _Parser:
    """Recursive descent over the token list; returns a nested tuple AST."""

    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokenize(text)
        self.i = 0

    def parse(self):
        node = self._expr()
        if self.i != len(self.tokens):
            raise ProtocolError(f"unexpected {self.tokens[self.i][1]!r} in {self.text!r}")
        return node

    def _peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def _take(self):
        token = self._peek()
        if token[0] is None:
            raise ProtocolError(f"predicate ends too early: {self.text!r}")
        self.i += 1
        return token

    def _expr(self):
        node = self._term()
        while self._peek() == ("bool", "OR"):
            self._take()
            node = ("or", node, self._term())
        return node

    def _term(self):
        node = self._factor()
        while self._peek() == ("bool", "AND"):
            self._take()
            node = ("and", node, self._factor())
        return node

    def _factor(self):
        kind, value = self._take()
        if (kind, value) == ("punct", "("):
            node = self._expr()
            if self._take() != ("punct", ")"):
                raise ProtocolError(f"missing ')' in {self.text!r}")
            return node
        if kind != "word":
            raise ProtocolError(f"expected a field name, got {value!r} in {self.text!r}")
        name = value
        op = self._peek()
        if op in (("op", "=="), ("op", "!="), ("op", "contains")):
            self._take()
            token = self._take()
            if token == ("word", "null"):
                # `== null` could never hold (null satisfies no comparison)
                raise ProtocolError(f"compare with null using '{name} is null' in {self.text!r}")
            return (op[1], name, _literal(token))
        if op == ("op", "non-empty"):
            self._take()
            return ("non-empty", name, None)
        if op == ("op", "is"):
            self._take()
            if self._take() != ("word", "null"):
                raise ProtocolError(f"'is' takes only 'null' in {self.text!r}")
            return ("is null", name, None)
        return ("==", name, True)


def parse_predicate(text: str):
    return _Parser(text).parse()


def _fields_in(node) -> set:
    if node[0] in ("and", "or"):
        return _fields_in(node[1]) | _fields_in(node[2])
    return {node[1]}


def _null_tested(node) -> set:
    """Field names the predicate tests with `is null`."""
    if node[0] in ("and", "or"):
        return _null_tested(node[1]) | _null_tested(node[2])
    return {node[1]} if node[0] == "is null" else set()


_IS_NULL = re.compile(r"\b([A-Za-z_][\w.\-]*)\s+is\s+null\b")


def render_predicate(text: str) -> str:
    """A predicate as the triage model reads it (`holds_when`): unchanged,
    except `x is null` reads "x not answered", which the model can match to
    its symptoms_not_answered list; the bare word null would read as a value."""
    return _IS_NULL.sub(r"\1 not answered", text)


def _lookup(context: dict, name: str):
    """`visual_summary.flagged_teeth` or a bare field name (symptoms first)."""
    if "." in name:
        head, tail = name.split(".", 1)
        return (context.get(head) or {}).get(tail)
    if name in context.get("symptoms", {}):
        return context["symptoms"][name]
    return (context.get("visual_summary") or {}).get(name)


def evaluate(node, context: dict) -> bool:
    op = node[0]
    if op == "and":
        return evaluate(node[1], context) and evaluate(node[2], context)
    if op == "or":
        return evaluate(node[1], context) or evaluate(node[2], context)
    value = _lookup(context, node[1])
    if op == "is null":
        return value is None
    if value is None:
        return False  # unanswered is never evidence
    if op == "==":
        return value == node[2]
    if op == "!=":
        return value != node[2]
    if op == "contains":
        return isinstance(value, list) and node[2] in value
    if op == "non-empty":
        return bool(value)
    raise ProtocolError(f"unknown operator {op!r}")


def _bare(name: str) -> str:
    return name.split(".", 1)[1] if name.startswith("visual_summary.") else name


# --- Protocol ----------------------------------------------------------------

@dataclass
class Criterion:
    id: str
    level: str
    kind: str
    statement: str
    source: str
    predicate: str | None = None
    floor: bool = False
    route: str | None = None
    ast: tuple | None = field(default=None, repr=False)

    def fields(self) -> list:
        """Field names the predicate reads, visual_summary prefix removed."""
        return sorted({_bare(n) for n in _fields_in(self.ast)}) if self.ast else []

    def null_fields(self) -> list:
        """Fields the predicate tests with `is null`: for these, being
        unanswered is the evidence."""
        return sorted({_bare(n) for n in _null_tested(self.ast)}) if self.ast else []

    def holds_when(self) -> str | None:
        """The condition as shown to the triage model."""
        return render_predicate(self.predicate) if self.predicate else None

    def holds(self, symptoms: dict, visual_summary: dict) -> bool:
        """Structured criteria only; narrative ones need a quote and the LLM."""
        if self.ast is None:
            return False
        return evaluate(self.ast, {"symptoms": symptoms or {},
                                   "visual_summary": visual_summary or {}})


@dataclass
class Question:
    id: str
    fields: list
    text: str
    red_flag: bool = False
    asked_if: str | None = None
    input: str = "chat"
    group: str | None = None
    options: tuple = ("yes", "no")
    option_labels: dict = field(default_factory=lambda: dict(DEFAULT_OPTION_LABELS))
    ast: tuple | None = field(default=None, repr=False)

    def option_items(self) -> list:
        """The answer buttons for a checklist row, as the page renders them."""
        return [{"label": self.option_labels.get(name, DEFAULT_OPTION_LABELS[name]),
                 "value": OPTION_VALUES[name]} for name in self.options]

    def allows(self, value) -> bool:
        """Whether `value` is an answer this row accepts. None ("not sure")
        only where the row offers it; never a string, number or missing."""
        return any(value is item["value"] for item in self.option_items())

    def applies(self, symptoms: dict) -> bool:
        """Whether asked_if holds (always, if there is none)."""
        return self.ast is None or evaluate(self.ast, {"symptoms": symptoms or {}})


@dataclass
class Protocol:
    version: str
    review_status: str
    headlines: dict
    safety_net: str
    criteria: list
    questions: list
    fixed_text: dict = field(default_factory=dict)
    limitations: list = field(default_factory=list)
    reask_template: str = "{question}"
    symptom_fields: list = field(default_factory=list)

    @property
    def reviewed(self) -> bool:
        return self.review_status != UNREVIEWED

    def criterion(self, criterion_id: str) -> Criterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)

    def criterion_ids(self) -> list:
        return [c.id for c in self.criteria]

    def met(self, symptoms: dict, visual_summary: dict) -> list:
        """Structured criteria that hold on these (already verified) facts."""
        return [c for c in self.criteria if c.kind == "structured"
                and c.holds(symptoms, visual_summary)]

    def protocol_level(self, symptoms: dict, visual_summary: dict) -> str:
        """The level the protocol's structured criteria imply by themselves:
        the most urgent that holds, ROUTINE when none does."""
        return most_urgent(c.level for c in self.met(symptoms, visual_summary)) or "ROUTINE"

    def route(self, criteria: list) -> str | None:
        """Emergency route for research logging: medical wins over dental."""
        routes = {c.route for c in criteria if c.level == "EMERGENCY"}
        for route in ("medical", "dental", "either"):
            if route in routes:
                return route
        return None


def _symptom_fields(schema: dict) -> dict:
    return {k: v for k, v in schema["properties"].items()
            if k not in ("schema_version", "notes")}


def _allowed_values(spec: dict):
    """Enum values a literal may take for this field, or None if any value goes."""
    if "enum" in spec:
        return set(spec["enum"])
    items = spec.get("items") or {}
    if "enum" in items:
        return set(items["enum"])
    types = spec.get("type")
    types = types if isinstance(types, list) else [types]
    if "boolean" in types:
        return {True, False}
    return None


def _check_literals(node, fields: dict, where: str, errors: list) -> None:
    if node[0] in ("and", "or"):
        _check_literals(node[1], fields, where, errors)
        _check_literals(node[2], fields, where, errors)
        return
    op, name, literal = node
    spec = fields.get(_bare(name))
    if spec is None:
        errors.append(f"{where}: unknown field {name!r}")
        return
    allowed = _allowed_values(spec)
    if op in ("==", "!=", "contains") and allowed is not None and literal not in allowed:
        errors.append(f"{where}: {literal!r} is not a value of {name}")


def _options(q: dict) -> tuple:
    """A checklist row's answer options. YAML 1.1 reads a bare yes/no as a
    boolean, so those are mapped back to their names."""
    names = {True: "yes", False: "no"}
    return tuple(names.get(o, o) if isinstance(o, bool) else o
                 for o in q.get("options") or ("yes", "no"))


def validate(raw: dict, symptom_schema: dict, red_flag_fields) -> list:
    """Every problem in the raw protocol, as readable strings (empty = valid)."""
    errors = []
    fields = {**_symptom_fields(symptom_schema), **VISUAL_FIELDS}
    red_flag_fields = set(red_flag_fields)

    for key in ("protocol_version", "review_status", "levels", "safety_net",
                "limitations", "fixed_text", "reask_template", "criteria", "questions"):
        if key not in raw:
            errors.append(f"missing top-level key {key!r}")
    if errors:
        return errors

    for level in LEVELS:
        if not ((raw["levels"] or {}).get(level) or {}).get("headline"):
            errors.append(f"levels.{level}.headline is missing")
    for key in FIXED_TEXT:
        if not (raw["fixed_text"] or {}).get(key):
            errors.append(f"fixed_text.{key} is missing")
    labels = (raw["fixed_text"] or {}).get("option_labels") or {}
    for name in labels:
        if name not in OPTIONS:
            errors.append(f"fixed_text.option_labels: {name!r} is not an option "
                          f"(expected {OPTIONS}); bare yes/no keys parse as booleans in YAML")
    if not (isinstance(raw["limitations"], list) and raw["limitations"]
            and all(isinstance(x, str) and x.strip() for x in raw["limitations"])):
        errors.append("limitations must be a non-empty list of strings")
    if "{question}" not in str(raw["reask_template"]):
        errors.append("reask_template must contain {question}")

    seen = set()
    for c in raw["criteria"]:
        where = f"criterion {c.get('id')!r}"
        if c.get("id") in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(c.get("id"))
        for key in ("id", "level", "kind", "statement", "source"):
            if not c.get(key):
                errors.append(f"{where}: missing {key!r}")
        if c.get("level") not in LEVELS:
            errors.append(f"{where}: level {c.get('level')!r} is not one of {LEVELS}")
        if c.get("kind") not in KINDS:
            errors.append(f"{where}: kind {c.get('kind')!r} is not one of {KINDS}")
        if c.get("kind") == "structured":
            if not c.get("predicate"):
                errors.append(f"{where}: structured criterion without a predicate")
            else:
                try:
                    ast = parse_predicate(c["predicate"])
                    _check_literals(ast, fields, where, errors)
                    if c.get("floor") and _null_tested(ast):
                        errors.append(f"{where}: a floor criterion may not use 'is null'; "
                                      "the floor fires on a reported red flag, never on "
                                      "a missing answer")
                except ProtocolError as exc:
                    errors.append(f"{where}: {exc}")
        if c.get("kind") == "narrative" and c.get("predicate"):
            errors.append(f"{where}: narrative criteria take no predicate "
                          "(split it into a structured and a narrative criterion)")
        if c.get("level") == "EMERGENCY" and c.get("route") not in ROUTES:
            errors.append(f"{where}: EMERGENCY criterion needs route in {ROUTES}")
        if c.get("floor") and c.get("level") != "EMERGENCY":
            errors.append(f"{where}: a floor criterion must be EMERGENCY")

    asked, seen, non_red_seen = set(), set(), False
    for q in raw["questions"]:
        where = f"question {q.get('id')!r}"
        if q.get("id") in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(q.get("id"))
        if not q.get("text"):
            errors.append(f"{where}: missing the fixed question text")
        qfields = q.get("fields") or []
        if not qfields:
            errors.append(f"{where}: no fields")
        for name in qfields:
            if name not in fields or name in VISUAL_FIELDS:
                errors.append(f"{where}: unknown symptom field {name!r}")
        if q.get("input") not in INPUTS:
            errors.append(f"{where}: input must be one of {INPUTS}")
        if q.get("input") == "yesno_checklist":
            if not q.get("group"):
                errors.append(f"{where}: a checklist row needs a group")
            if len(qfields) != 1 or _allowed_values(fields.get(qfields[0], {})) != {True, False}:
                errors.append(f"{where}: a checklist row must fill exactly one yes/no field")
            options = _options(q)
            if not set(options) <= set(OPTIONS) or not {"yes", "no"} <= set(options):
                errors.append(f"{where}: options must include yes and no, from {OPTIONS}")
            if "not_sure" in options and q.get("red_flag"):
                errors.append(f"{where}: a red-flag row may not offer not_sure; it would "
                              "record null and the floor could never fire")
        elif q.get("options"):
            errors.append(f"{where}: options are for checklist rows only")
        asked |= set(qfields)
        in_floor = {name in red_flag_fields for name in qfields}
        if len(in_floor) > 1:
            errors.append(f"{where}: mixes red-flag and other fields; a bare yes "
                          "could not say which it answers")
        if bool(q.get("red_flag")) != (in_floor == {True}):
            errors.append(f"{where}: red_flag must be true exactly when its fields "
                          "are red-flag fields")
        if q.get("asked_if"):
            try:
                _check_literals(parse_predicate(q["asked_if"]), fields, where, errors)
            except ProtocolError as exc:
                errors.append(f"{where}: {exc}")
        if not q.get("red_flag"):
            non_red_seen = True
        elif non_red_seen and not q.get("asked_if"):
            errors.append(f"{where}: an unconditional red-flag question must come "
                          "before every other question")

    by_input = {}
    for q in raw["questions"]:
        for name in q.get("fields") or []:
            by_input.setdefault(name, set()).add(q.get("input"))
    for name, inputs in sorted(by_input.items()):
        if len(inputs) > 1:
            errors.append(f"field {name!r} is filled both on a checklist and in the chat; "
                          "the checklist answer would silently win")

    for name in sorted(red_flag_fields - asked):
        errors.append(f"red-flag field {name!r} is not asked by any question")

    # Every red flag needs a floor criterion of its own: the floor forces
    # EMERGENCY either way, and without one the result would carry no reason.
    floored = set()
    for c in raw["criteria"]:
        if c.get("floor") and c.get("predicate"):
            try:
                floored |= {_bare(n) for n in _fields_in(parse_predicate(c["predicate"]))}
            except ProtocolError:
                continue
    for name in sorted(red_flag_fields - floored):
        errors.append(f"red-flag field {name!r} has no floor criterion, so an EMERGENCY "
                      "from it would have no reason to show")
    for c in raw["criteria"]:
        if c.get("kind") == "structured" and c.get("predicate"):
            try:
                used = {_bare(n) for n in _fields_in(parse_predicate(c["predicate"]))}
            except ProtocolError:
                continue
            for name in sorted(used - asked - set(VISUAL_FIELDS)):
                errors.append(f"criterion {c['id']!r}: field {name!r} is not asked "
                              "by any question")
    return errors


def build(raw: dict, symptom_schema: dict = None, red_flag_fields=None) -> Protocol:
    """Validate a raw protocol dict and return a Protocol. Raises ProtocolError."""
    if symptom_schema is None:
        symptom_schema = json.loads(SYMPTOM_SCHEMA_PATH.read_text(encoding="utf-8"))
    if red_flag_fields is None:
        import assess  # noqa: F401  (puts llm/ on sys.path)
        import rules
        red_flag_fields = rules.RED_FLAG_FIELDS
    errors = validate(raw, symptom_schema, red_flag_fields)
    if errors:
        raise ProtocolError("invalid triage protocol:\n  " + "\n  ".join(errors))
    labels = {**DEFAULT_OPTION_LABELS,
              **{str(k): str(v) for k, v in
                 ((raw["fixed_text"] or {}).get("option_labels") or {}).items()}}
    criteria = [Criterion(id=c["id"], level=c["level"], kind=c["kind"],
                          statement=c["statement"], source=c["source"],
                          predicate=c.get("predicate"), floor=bool(c.get("floor")),
                          route=c.get("route"),
                          ast=parse_predicate(c["predicate"]) if c.get("predicate") else None)
                for c in raw["criteria"]]
    questions = [Question(id=q["id"], fields=list(q["fields"]), text=q["text"].strip(),
                          red_flag=bool(q.get("red_flag")), asked_if=q.get("asked_if"),
                          input=q["input"], group=q.get("group"),
                          options=_options(q), option_labels=labels,
                          ast=parse_predicate(q["asked_if"]) if q.get("asked_if") else None)
                 for q in raw["questions"]]
    return Protocol(version=str(raw["protocol_version"]),
                    review_status=raw["review_status"],
                    headlines={lv: raw["levels"][lv]["headline"].strip() for lv in LEVELS},
                    safety_net=raw["safety_net"].strip(),
                    limitations=[x.strip() for x in raw["limitations"]],
                    fixed_text={k: str(v).strip() for k, v in raw["fixed_text"].items()},
                    reask_template=raw["reask_template"].strip(),
                    criteria=criteria, questions=questions,
                    symptom_fields=list(_symptom_fields(symptom_schema)))


def load(path: Path = PROTOCOL_PATH, allow_unreviewed: bool = False, **kwargs) -> Protocol:
    """Load and validate the protocol file. An unreviewed protocol is refused
    unless allow_unreviewed=True, which is for development only."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    protocol = build(raw, **kwargs)
    if not protocol.reviewed and not allow_unreviewed:
        raise UnreviewedProtocol(
            f"{path} is {UNREVIEWED}. A dentist must sign it off; "
            "pass allow_unreviewed=True for development only.")
    return protocol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(PROTOCOL_PATH))
    args = ap.parse_args()
    protocol = load(Path(args.path), allow_unreviewed=True)
    print(f"protocol {protocol.version} ({protocol.review_status}): "
          f"{len(protocol.criteria)} criteria, {len(protocol.questions)} questions")
    for c in protocol.criteria:
        print(f"  {c.id:5} {c.level:9} {c.kind:10} {c.predicate or '(narrative)'}")


if __name__ == "__main__":
    main()
