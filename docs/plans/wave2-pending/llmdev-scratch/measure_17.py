import json
import re

ns = {"re": re}
exec(open(r"C:\Users\user\.claude\jobs\480511cf\tmp\llmdev\pending_17_explain.py", encoding="utf-8").read(), ns)
for name in ("faithfulness_qwen3_14b.json", "faithfulness_qwen3_4b.json"):
    data = json.loads(open(rf"D:\jonathan\tooth-llm\runs\evals\{name}", encoding="utf-8").read())
    hits = [c["id"] for c in data["cases"] if ns["denies_tooth_cause"](c["text"])]
    print(name, f"{len(hits)}/{len(data['cases'])}", hits)
