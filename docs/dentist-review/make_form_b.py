"""Render blind labelling sheets for Form B (research-pm).

    .venv/Scripts/python docs/dentist-review/make_form_b.py --n 60

Reads the held-out keys, writes sheets to runs/dentist/ (gitignored) and a
matching answer file that stays in labels/heldout/. The sheet never contains
the key, the criteria, the archetype or the level, and cases come out in a
shuffled order with fresh sheet numbers, so nothing about the ordering leaks.

Vignette text (`patient_words`) is written by P7; until then the keys carry
only `facts`, and this script refuses to run rather than hand a dentist a
sheet made of our own shorthand.
"""
import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KEYS = ROOT / "labels" / "heldout" / "triage_heldout_keys.json"
OUT = ROOT / "runs" / "dentist"

BOXES = ("Level:  [ ] EMERGENCY   [ ] URGENT   [ ] SOON   [ ] ROUTINE   "
         "[ ] Not enough information\n"
         "If EMERGENCY, route: [ ] hospital  [ ] dentist\n"
         "What drove your decision: ______________________________________")


def photo_line(visual: dict) -> str:
    if not visual["images_usable"]:
        return "The photos were too blurry or cropped to read."
    flagged = [t["name"] for t in visual["flagged_teeth"]]
    missing = [t["name"] for t in visual["unexpected_missing_teeth"]]
    parts = []
    if flagged:
        parts.append("the photo flagged possible decay on the " + ", ".join(flagged))
    if missing:
        parts.append("the " + ", ".join(missing) + " appears to be missing")
    return ("The photos showed nothing of note." if not parts
            else (" and ".join(parts)).capitalize() + ".")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="how many cases on the sheet")
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--name", default="sheet1")
    args = ap.parse_args()

    keys = json.loads(KEYS.read_text(encoding="utf-8"))["keys"]
    missing_text = [k["id"] for k in keys if not k.get("patient_words")]
    if missing_text:
        raise SystemExit(f"{len(missing_text)} keys have no patient_words yet (P7); "
                         "not writing a sheet from internal shorthand.")

    rng = random.Random(args.seed)
    chosen = rng.sample(keys, min(args.n, len(keys)))
    rng.shuffle(chosen)

    OUT.mkdir(parents=True, exist_ok=True)
    lines, answers = [f"# Blind labelling sheet: {args.name}", ""], []
    for i, k in enumerate(chosen, 1):
        case = f"{args.name.upper()}-{i:03d}"
        lines += [f"## Case {case}", "",
                  f'Patient: "{k["patient_words"]}"', "",
                  f"Photo: {photo_line(k['visual_summary'])}", "",
                  BOXES, "", "---", ""]
        answers.append({"case": case, "id": k["id"]})
    (OUT / f"{args.name}.md").write_text("\n".join(lines), encoding="utf-8")
    (KEYS.parent / f"{args.name}_caseids.json").write_text(
        json.dumps(answers, indent=1), encoding="utf-8")
    print(f"{len(chosen)} cases -> {OUT / (args.name + '.md')}")
    print(f"case-id map (keep out of the dentist's hands) -> "
          f"{KEYS.parent / (args.name + '_caseids.json')}")


if __name__ == "__main__":
    main()
