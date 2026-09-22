"""Explanation step: findings + symptoms + assessment + knowledge -> text.

Step 5 of llm/README.md. The model only verbalises what the other stages
decided — it never sees a photo, never picks the urgency, and answers
questions only from the retrieved passages.

    python src/explain.py --findings findings.json \
                          [--symptoms s.json] [--ask "is it definitely a cavity?"]

The assessment is computed here from findings + symptoms rather than
passed in, so the text can never describe an urgency that rules.py did
not produce.

Knowledge passages carry their file's review_status. llm/README.md says
not to ship anything still marked DRAFT-UNREVIEWED, so unreviewed
passages are refused unless --allow-unreviewed is passed, which is for
development only.
"""
import argparse
import json
import sys
from pathlib import Path

from assess import assess
from interview import chat, DEFAULT_MODEL
from retrieval import Knowledge

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT = (REPO_ROOT / "llm" / "prompts" / "system_explain.md").read_text(encoding="utf-8")
UNREVIEWED = "DRAFT-UNREVIEWED"


class UnreviewedKnowledge(RuntimeError):
    pass


# The prompt asks for a plain-word location beside every FDI number, and the
# model gets it wrong (it called 36 "upper right"). The mapping is fixed, so
# it is computed here and handed over rather than left to the model.
_QUADRANTS = {"1": "upper right", "2": "upper left", "3": "lower left", "4": "lower right",
              "5": "upper right baby", "6": "upper left baby",
              "7": "lower left baby", "8": "lower right baby"}
_POSITIONS = {"1": "central incisor", "2": "lateral incisor", "3": "canine",
              "4": "first premolar", "5": "second premolar", "6": "first molar",
              "7": "second molar", "8": "third molar (wisdom tooth)"}


def fdi_label(fdi: str) -> str:
    """'36' -> 'lower left first molar'."""
    quadrant, position = str(fdi)[0], str(fdi)[1]
    if quadrant not in _QUADRANTS or position not in _POSITIONS:
        return "tooth " + str(fdi)
    return f"{_QUADRANTS[quadrant]} {_POSITIONS[position]}"


def tooth_names(findings: dict) -> dict:
    return {fdi: fdi_label(fdi) for fdi in findings.get("teeth", {})}


def _passages_block(passages: list) -> str:
    if not passages:
        return "knowledge_passages: []"
    parts = [f"### {p['heading']} ({p['file']})\n{p['text']}" for p in passages]
    return "knowledge_passages:\n" + "\n\n".join(parts)


def _first_query(findings: dict, assessment: dict) -> str:
    """What to retrieve for the opening message, before the user has asked
    anything: the urgency being explained plus the kinds of finding."""
    types = sorted({d["type"] for t in findings.get("teeth", {}).values()
                    for d in t.get("detections", [])})
    return " ".join([assessment["urgency"], assessment["rule_reason"].replace("_", " "),
                     *types, "what this means and what to do"]).strip()


class Explanation:
    def __init__(self, findings: dict, symptoms: dict = None, model: str = DEFAULT_MODEL,
                 allow_unreviewed: bool = False, knowledge: Knowledge = None):
        self.findings = findings
        self.symptoms = symptoms
        self.assessment = assess(findings, symptoms)
        self.model = model
        self.allow_unreviewed = allow_unreviewed
        self.knowledge = knowledge or Knowledge()
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _retrieve(self, query: str) -> list:
        passages = self.knowledge.search(query)
        unreviewed = [p["file"] for p in passages if p["review_status"] == UNREVIEWED]
        if unreviewed and not self.allow_unreviewed:
            raise UnreviewedKnowledge(
                f"{UNREVIEWED} knowledge retrieved ({', '.join(sorted(set(unreviewed)))}). "
                "A dentist must sign these off; pass --allow-unreviewed for development."
            )
        return passages

    def first_response(self) -> str:
        passages = self._retrieve(_first_query(self.findings, self.assessment))
        content = "\n\n".join([
            "findings:\n" + json.dumps(self.findings, indent=2),
            "symptoms:\n" + json.dumps(self.symptoms, indent=2) if self.symptoms
            else "symptoms: null (the user did not do the interview)",
            "assessment:\n" + json.dumps(self.assessment, indent=2),
            "tooth_names (plain-word location for each number; write a tooth as "
            "\"tooth 36 (lower left first molar)\", always giving both):\n"
            + json.dumps(tooth_names(self.findings), indent=2),
            _passages_block(passages),
            self._scope_instruction(),
        ])
        return self._turn(content)

    def _scope_instruction(self) -> str:
        """What may be reported at all.

        findings.teeth carries every detection the model made, including
        ones below the reporting threshold in rules.py. Only the teeth
        rules.py flagged may be described as possible cavities — otherwise
        a 0.22-confidence blip gets told to the user as a finding.
        """
        if self.assessment["retake_required"]:
            return ("Write the first response now. The photos could not be used: ask for "
                    "a retake and explain how. Do not mention any tooth, number or "
                    "finding — not even in plain words.")
        flagged = self.assessment["flagged_teeth"]
        if flagged:
            scope = ("Only these teeth may be described as having a possible finding: "
                     + ", ".join(flagged) + ". ")
        else:
            scope = ("No tooth may be described as having a finding: nothing reached the "
                     "reporting threshold. Say nothing was found, and that this does not "
                     "rule anything out. ")
        return (scope + "Any other detection in findings was below the reporting threshold "
                "and must not be mentioned at all. Write the first response now.")

    def ask(self, question: str) -> str:
        passages = self._retrieve(question)
        return self._turn(_passages_block(passages) + f"\n\nUser asks: {question}")

    def _turn(self, content: str) -> str:
        self.messages.append({"role": "user", "content": content})
        reply = chat(self.messages, self.model)
        self.messages.append({"role": "assistant", "content": reply})
        return reply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--symptoms")
    ap.add_argument("--ask", action="append", default=[], help="Follow-up question; repeatable")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--allow-unreviewed", action="store_true")
    args = ap.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    symptoms = json.loads(Path(args.symptoms).read_text(encoding="utf-8")) if args.symptoms else None

    try:
        session = Explanation(findings, symptoms, args.model, args.allow_unreviewed)
        print(f"[assessment] {session.assessment['urgency']} / {session.assessment['rule_id']}\n")
        print(session.first_response())
        for question in args.ask:
            print(f"\n--- user: {question}\n")
            print(session.ask(question))
    except UnreviewedKnowledge as exc:
        print(f"refused: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
