import json
import sys

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import check_faithfulness as cf  # noqa: E402
from explain import places_pain  # noqa: E402

cases = {c["id"]: c for c in json.loads(cf.FAITHFULNESS.read_text(encoding="utf-8"))["cases"]}
rules = {c["id"]: c for c in json.loads(cf.RULE_CASES.read_text(encoding="utf-8"))["cases"]}
for name in ("faithfulness_qwen3_14b.json", "faithfulness_qwen3_4b.json"):
    data = json.loads(open(rf"D:\jonathan\tooth-llm\runs\evals\{name}", encoding="utf-8").read())
    hits = 0
    for c in data["cases"]:
        src = cases.get(c["id"]) or rules.get(c["id"]) or {}
        loc = (src.get("symptoms") or {}).get("location")
        if places_pain(c["text"], loc):
            hits += 1
            print(f"HIT {name} {c['id']} loc={loc}\n    {c['text'][:700]}\n")
    print(name, f"{hits}/{len(data['cases'])}")
