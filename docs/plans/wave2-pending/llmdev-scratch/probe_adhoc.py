import sys

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import check_symptoms as cs  # noqa: E402
import interview  # noqa: E402
import protocol as P  # noqa: E402

proto = P.load(allow_unreviewed=True)
CASES = [
    {"id": "X1", "checklist": {"A": {"Q9": True}, "B": {}},
     "script": {"Q10": "No.", "Q11": "Moderate.", "Q12": "It comes out of the blue, mostly at night.",
                "Q17": "Downstairs, right side.", "Q18": "A week."},
     "expected": {"pain_relief_effect": "not_tried", "pain_severity": "moderate",
                  "pain_triggers": ["spontaneous"], "location": "lower_right", "duration_days": 7}},
    {"id": "X2", "checklist": {"A": {"Q9": True}, "B": {}},
     "script": {"Q10": ["Yes.", "It didn't help much."], "Q11": "Mild.",
                "Q12": "No idea what sets it off. I work nights so I notice it at night.",
                "Q17": "Front, up top.", "Q18": "Two days."},
     "expected": {"pain_relief_effect": "not_helped", "pain_severity": "mild",
                  "pain_triggers": ["unknown"], "location": "front", "duration_days": 2}},
]
for case in CASES:
    played = cs.run_case(case, interview.DEFAULT_MODEL, proto)
    got = played["symptoms"]
    print("==", case["id"], "asked:", [a["id"] for a in played["asked"]])
    for f, want in case["expected"].items():
        g = got.get(f)
        ok = (sorted(g or []) == sorted(want)) if isinstance(want, list) else g == want
        print(f"   {'ok ' if ok else 'BAD'} {f}: want {want!r} got {g!r}")
