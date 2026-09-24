# Task #21: in first-response drafts (before guardrails), how often does the model
# (a) omit the retake request on a partial retake, (b) name a tooth outside flagged_teeth?
import json
import sys

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import check_faithfulness as cf  # noqa: E402

d = json.load(open(r"D:\jonathan\tooth-llm\runs\evals\test2v3_syn60_both.json", encoding="utf-8"))
drafts = extra_cases = 0
extra = []
no_retake = []
for c in d["triage"]["cases"]:
    n = 2 if c["guardrail_log"] else 1   # first response + its one rewrite, if any
    firsts = c["replies"][:n]
    allowed = set(c["flagged"])
    for i, text in enumerate(firsts):
        drafts += 1
        named = cf.mentioned_teeth(text) - allowed
        if named:
            extra.append((c["id"], i, sorted(named), c["urgency"], c["retake_required"]))
        if c["retake_required"] and c["urgency"] != "RETAKE" and not cf.retake_requested(text):
            no_retake.append((c["id"], i))
print("first-response drafts:", drafts)
print("drafts naming a tooth outside flagged_teeth:", len(extra))
for e in extra:
    print("  ", e)
print("partial-retake drafts without a retake request:", len(no_retake), no_retake)
