import sys

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import check_faithfulness as cf  # noqa: E402

ids = sys.argv[1:]
cases = [c for c in cf.generate(60, 0) if c["id"] in ids]
res = cf.evaluate(cases, model="qwen3:14b", verbose=False)
for c in res["cases"]:
    print(c["id"], "misstated:", c.get("misstated"), "| retry/fallback log:", c.get("guardrail_log"))
    print("   ", c.get("text", "")[:600].replace("\n", " "))
print({k: res[k] for k in ("n", "hallucination", "omission", "contradiction", "misstated")})
