# tree24 checks: app-dev's live texts, then all stored Test 2 texts.
import json
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parents[1] / "tree24"
sys.path.insert(0, str(TREE / "src"))
import explain  # noqa: E402
from eval_data import generate_v2  # noqa: E402

bad_upper = {"image_quality": {"upper": {"usable": False, "reasons": ["no_teeth_detected"]},
                               "lower": {"usable": True, "reasons": []}}, "arches": {}, "teeth": {}}
tmp = Path(r"C:\Users\user\.claude\jobs\480511cf\tmp")
for name in ("res.json", "res2.json"):
    text = json.loads((tmp / name).read_text(encoding="utf-8"))["explanation"]
    print(name, "denies:", explain.denies_tooth_finding(text),
          "unscoped absence:", explain.unscoped_absence(text, bad_upper))
print("follow-up (res2):", explain.unscoped_absence(
    "Nothing was visible on the biting surfaces in these photos.", bad_upper))

total = hits = 0
for path in sorted(Path(r"D:\jonathan\tooth-llm\runs\evals").glob("*.json")):
    d = json.loads(path.read_text(encoding="utf-8"))
    for key in ("triage", "legacy"):
        sec = d.get(key) if isinstance(d, dict) else None
        for c in (sec or {}).get("cases", []) + (d.get("cases", []) if key == "triage" else []):
            for t in c.get("replies") or [c.get("text")]:
                if not isinstance(t, str):
                    continue
                total += 1
                if explain.denies_tooth_finding(t):
                    hits += 1
                    print("  DENIES", path.name, c.get("id"), "|", t[:160].replace("\n", " "))
print(f"denies_tooth_finding over stored texts: {hits}/{total}")

gen = {c["id"]: c for c in generate_v2(60, 0)}
d = json.load(open(r"D:\jonathan\tooth-llm\runs\evals\test2v3_syn60_both.json", encoding="utf-8"))
n = h = 0
for c in d["triage"]["cases"]:
    if not c["retake_required"]:
        continue
    for t in c["replies"]:
        n += 1
        if explain.unscoped_absence(t, gen[c["id"]]["findings"]):
            h += 1
            print("  ABSENCE", c["id"], c["urgency"], "|", t[:200].replace("\n", " "))
print(f"unscoped_absence over v3 retake texts: {h}/{n}")
