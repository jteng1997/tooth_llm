# Task #21 offline simulation on Test 2 v3 (triage mode), using the stored model drafts:
#  A) "unreported tooth" guardrail: a tooth outside decay+missing named in the first response.
#  B) retake last resort: when the only failure left after the rewrite is the missing retake
#     request, append the fixed retake sentence instead of replacing everything with the fallback.
import json
import sys

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import check_faithfulness as cf  # noqa: E402
import explain  # noqa: E402
from eval_data import generate_v2  # noqa: E402

d = json.load(open(r"D:\jonathan\tooth-llm\runs\evals\test2v3_syn60_both.json", encoding="utf-8"))
gen = {c["id"]: c for c in generate_v2(60, 0)}


def reportable(case_id, flagged):
    f = gen[case_id]["findings"]
    missing = [t for t, v in f.get("teeth", {}).items() if v.get("present") is False]
    return set(flagged) | set(missing)


a_final = a_draft = 0
b_saved, b_still = [], []
for c in d["triage"]["cases"]:
    n = 2 if c["guardrail_log"] else 1
    ok = reportable(c["id"], c["flagged"])
    for i, text in enumerate(c["replies"][:n]):
        if cf.mentioned_teeth(text) - ok:
            a_draft += 1
            if i == n - 1 and not c["fallback"]:
                a_final += 1
    log = c["guardrail_log"]
    if c["fallback"] and log and all("retake" in p for p in log[0]["after_retry"]):
        draft = c["replies"][1]
        f = gen[c["id"]]["findings"]
        appended = draft.rstrip() + " " + explain._retake_sentence(f)
        other = explain.guardrail_violations(appended, [t for t in c["flagged"]])
        unreported = cf.mentioned_teeth(appended) - ok
        if other or unreported or not cf.retake_requested(appended):
            b_still.append((c["id"], other, sorted(unreported)))
        else:
            b_saved.append(c["id"])
print(f"A: drafts naming an unreported tooth {a_draft}; of them shown to the patient {a_final}/60")
print(f"B: fallbacks that the appended retake sentence would replace {len(b_saved)}: {b_saved}")
print(f"B: would still fall back {len(b_still)}: {b_still}")
