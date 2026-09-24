# Task #22: run the tree21 checks over every stored Test 2 v3 text (triage mode):
# final first responses, first-response drafts, and follow-up answers.
import json
import re
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parents[1] / "tree21"
sys.path.insert(0, str(TREE / "src"))
import explain  # noqa: E402
from eval_data import generate_v2  # noqa: E402

d = json.load(open(r"D:\jonathan\tooth-llm\runs\evals\test2v3_syn60_both.json", encoding="utf-8"))
gen = {c["id"]: c for c in generate_v2(60, 0)}
hits = {"first": [], "follow": []}
denials = []
n_first = n_follow = 0
for c in d["triage"]["cases"]:
    f = gen[c["id"]]["findings"]
    a = {"flagged_teeth": c["flagged"], "retake_required": c["retake_required"],
         "urgency": c["urgency"], "reasons": [{"statement": "missing"}]
         if any(v.get("present") is False for v in f.get("teeth", {}).values()) else []}
    allowed = {t for g in explain.split_flagged(a, f) for t in g}
    firsts = 2 if c["guardrail_log"] else 1
    for i, text in enumerate(c["replies"]):
        kind = "first" if i < firsts else "follow"
        if kind == "first":
            n_first += 1
        else:
            n_follow += 1
        bad = explain.reports_unreported(text, allowed)
        if bad:
            hits[kind].append((c["id"], i, bad))
        if explain.discourages_care(text):
            print("   DISCOURAGES", c["id"], i, text[:200].replace("\n", " "))
        if explain.denies_tooth_finding(text):
            denials.append((c["id"], i, [s for s in re.split(r"(?<=[.!?])\s+", text)
                                         if explain.denies_tooth_finding(s)]))
print(f"first-response texts {n_first}, flagged by reports_unreported: {len(hits['first'])}")
for h in hits["first"]:
    print("   ", h)
print(f"follow-up texts {n_follow}, flagged: {len(hits['follow'])}")
for h in hits["follow"]:
    print("   ", h)
print(f"denies_tooth_finding hits: {len(denials)}")
for h in denials:
    print("   ", h)
