# Sweep the live explain.discourages_care() over every stored Test 2 text.
import json
import sys
from pathlib import Path

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import explain  # noqa: E402

runs = sorted(Path(r"D:\jonathan\tooth-llm\runs\evals").glob("*.json"))
total = 0
for path in runs:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        continue
    sections = [d[k] for k in ("triage", "legacy") if isinstance(d, dict) and isinstance(d.get(k), dict)]
    if isinstance(d, dict) and "cases" in d:
        sections.append(d)
    texts = []
    for s in sections:
        for c in s.get("cases", []):
            texts += [(c.get("id"), t) for t in (c.get("replies") or [c.get("text")]) if isinstance(t, str)]
    if not texts:
        continue
    hits = [(i, t) for i, t in texts
            if explain.discourages_care(t) or explain.denies_tooth_finding(t)
            or explain.denies_tooth_cause(t)]
    total += len(texts)
    print(f"{path.name}: {len(hits)}/{len(texts)}")
    for i, t in hits:
        print("    ", i, "|", t[:180].replace("\n", " "))
print("texts swept:", total)
