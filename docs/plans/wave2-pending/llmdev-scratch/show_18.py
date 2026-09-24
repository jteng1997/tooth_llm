# Task #18: print the retake_required + URGENT cases from the Test 2 triage-2.0 run.
import json
import sys

d = json.load(open(r"D:\jonathan\tooth-llm\runs\evals\test2v2_syn60_both.json", encoding="utf-8"))
t = d["triage"]
print({k: t[k] for k in t if k != "cases"})
ids = set(sys.argv[1:]) or set("S0004 S0017 S0023 S0030 S0034 S0054 S0005 S0012 S0049 S0052".split())
for c in t["cases"]:
    if c["id"] in ids:
        print("=====", c["id"], c["urgency"], "flagged", c["flagged"], "hall", c["hallucinated"],
              "om", c["omitted"], "contra", repr(c["contradiction"]), "mis", c["misstated"],
              "fb", c["fallback"])
        print(c["guardrail_log"])
        print(c["text"][:900])
