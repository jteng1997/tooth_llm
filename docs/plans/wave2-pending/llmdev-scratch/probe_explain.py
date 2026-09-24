import json
import re
import sys

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import check_faithfulness as cf  # noqa: E402
from explain import Explanation, fdi_label  # noqa: E402

bases = json.loads(cf.RULE_CASES.read_text(encoding="utf-8"))
case = {} if sys.argv[1] == "BASE" else next(
    c for c in json.loads(cf.FAITHFULNESS.read_text(encoding="utf-8"))["cases"]
    if c["id"] == sys.argv[1])
findings = cf.build_findings(case, bases)
symptoms = {
    "schema_version": "1.1", "pain_present": True, "pain_triggers": ["biting"],
    "pain_lingers_over_30s": False, "pain_wakes_at_night": False, "pain_on_biting": True,
    "pain_relief_effect": "not_helped", "pain_severity": "moderate",
    "swelling": False, "swelling_features": None, "fever": False, "systemically_unwell": False,
    "difficulty_swallowing_or_breathing": False, "chest_pain_or_breathless": False,
    "recent_trauma": False, "trauma_features": None, "bleeding_uncontrolled": False,
    "exceeded_pain_relief_dose": False, "recent_extraction": False, "persistent_ulcer": False,
    "bleeding_gums": None, "location": None, "duration_days": 5, "notes": None,
}
SIDE = re.compile(r"\b(left|right|upper|lower|top|bottom)\b", re.I)

s = Explanation(findings, symptoms, allow_unreviewed=True)
labels = [fdi_label(t) for t in s.assessment["flagged_teeth"]]
print("flagged:", s.assessment["flagged_teeth"], labels, "urgency:", s.assessment["urgency"])


def show(tag, text):
    stripped = text.lower()
    for label in labels:
        stripped = stripped.replace(label, "")
    print(f"--- {tag}\n{text}\n    side words outside tooth labels: {SIDE.findall(stripped)}")


show("first response", s.first_response())
for q in ("Which side is my toothache on?",
          "Is the pain I feel when biting coming from the tooth you found?"):
    show(q, s.ask(q))
print("guardrail_log:", s.guardrail_log)
