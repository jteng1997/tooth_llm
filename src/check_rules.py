"""Test 1 from llm/eval: does rules.py produce the intended urgency?

    python src/check_rules.py

Deterministic — any failure is a bug, target is 100%. Each case names a
findings template in rule_cases.json ("_good_findings", "_bad_image",
"_few_teeth"), then overrides `teeth` and any other findings key on top.
"""
import copy
import json
import sys
from pathlib import Path

from assess import assess

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES = REPO_ROOT / "llm" / "eval" / "rule_cases.json"
CASE_ONLY_KEYS = {"id", "note", "findings_base", "symptoms",
                  "expected_urgency", "expected_rule", "dentist_label"}


def build_findings(spec: dict, case: dict) -> dict:
    findings = copy.deepcopy(spec[case["findings_base"]])
    for key, value in case.items():
        if key not in CASE_ONLY_KEYS:
            findings[key] = value
    return findings


def main() -> int:
    spec = json.loads(CASES.read_text())
    failures = []
    for case in spec["cases"]:
        result = assess(build_findings(spec, case), case.get("symptoms"))
        ok_urgency = result["urgency"] == case["expected_urgency"]
        ok_rule = result["rule_id"] == case["expected_rule"]
        status = "ok  " if (ok_urgency and ok_rule) else "FAIL"
        if not (ok_urgency and ok_rule):
            failures.append((case, result))
        print(f"{status} {case['id']}  expected {case['expected_urgency']}/{case['expected_rule']}"
              f"  got {result['urgency']}/{result['rule_id']}  — {case['note']}")

    total = len(spec["cases"])
    print(f"\n{total - len(failures)}/{total} cases pass")
    for case, result in failures:
        print(f"  {case['id']}: expected {case['expected_urgency']}/{case['expected_rule']}, "
              f"got {result['urgency']}/{result['rule_id']} ({result['rule_reason']})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
