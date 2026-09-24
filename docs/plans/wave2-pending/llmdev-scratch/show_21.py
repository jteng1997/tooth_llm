# Task #21: why partial-retake explanations end in the fallback (Test 2 v3, triage mode).
import json
import sys

d = json.load(open(r"D:\jonathan\tooth-llm\runs\evals\test2v3_syn60_both.json", encoding="utf-8"))
print("top keys:", list(d))
t = d["triage"]
print({k: t[k] for k in t if k not in ("cases", "follow_up")})
c0 = t["cases"][0]
print("case keys:", list(c0))
full = "--full" in sys.argv
for c in t["cases"]:
    if not c.get("retake_required"):
        continue
    print("=====", c["id"], c["urgency"], "flagged", c["flagged"], "fallback", c["fallback"])
    for g in c.get("guardrail_log") or []:
        print("   log:", g)
    for k in ("drafts", "raw_replies", "attempts", "chat_log"):
        if k in c:
            print("   ", k, ":", json.dumps(c[k])[:3000 if full else 600])
