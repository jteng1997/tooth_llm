# Task #20: the dev dialogues' own Q12 answers must still evidence their keyed triggers.
import json
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parents[1] / (sys.argv[1] if len(sys.argv) > 1 else "tree20")
sys.path.insert(0, str(TREE / "src"))
import interview  # noqa: E402

cases = json.loads((TREE / "llm/eval/symptom_dialogues.json").read_text(encoding="utf-8"))["cases"]
bad = 0
for c in cases:
    want = c["expected"].get("pain_triggers")
    answers = c["script"].get("Q12")
    if not want or answers is None or c.get("scope") == "robustness":
        continue
    answer = answers[-1] if isinstance(answers, list) else answers
    got = interview.verify("pain_triggers", want, answer, [("Q12", answer)], "Q12")
    ok = sorted(got or []) == sorted(want)
    bad += not ok
    print("ok " if ok else "BAD", c["id"], want, got, repr(answer))
print("dev trigger answers dropped:", bad)
