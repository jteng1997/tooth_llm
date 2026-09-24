import json
import sys
from pathlib import Path

import yaml

ROOT = Path(r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2")
sys.path.insert(0, str(ROOT / "src"))
schema = json.loads((ROOT / "llm/prompts/symptoms_schema.json").read_text(encoding="utf-8"))
schema["properties"]["schema_version"]["const"] = "1.2"
props = {}
for k, v in schema["properties"].items():
    props[k] = v
    if k == "persistent_ulcer":
        props["broken_filling_or_tooth"] = {"type": ["boolean", "null"]}
        props["pus_or_discharge"] = {"type": ["boolean", "null"]}
schema["properties"] = props
out = Path(r"C:\Users\user\.claude\jobs\480511cf\tmp\llmdev\symptoms_schema_1.2.json")
out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

import interview  # noqa: E402
import protocol as P  # noqa: E402

raw = yaml.safe_load((ROOT / "docs/plans/protocol-v0.2/triage_protocol.yaml").read_text(encoding="utf-8"))
p = P.build(raw, symptom_schema=schema)
print("v", p.version, len(p.criteria), "criteria", len(p.questions), "questions")
A = [q.id for q in p.questions if q.input == "yesno_checklist" and q.group == "A"]
print("A rows", A)
for row, field in (("Q21", "pus"), ("Q20", "broken")):
    iv = interview.Interview(protocol=p, llm=lambda m, s: "{}")
    iv.start()
    ans = {q: False for q in A}
    ans[row] = True
    step = iv.submit_checklist("A", ans)
    vis = {"images_usable": True, "flagged_teeth": [], "unexpected_missing_teeth": []}
    print(f"{field} yes, no pain:", step["type"], "red_flag", step.get("red_flag"),
          "level", p.protocol_level(step["symptoms"], vis))
