"""Regenerate Form A (protocol review) from the protocol YAML, so the form
cannot drift from what the code runs.

    .venv/Scripts/python docs/dentist-review/make_form_a.py
    .venv/Scripts/python docs/dentist-review/make_form_a.py --protocol docs/plans/protocol-v0.2/triage_protocol.yaml
"""
import argparse
import datetime
import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LEVELS = ["EMERGENCY", "URGENT", "SOON", "ROUTINE"]
PENDING_WORDING = {"Q20", "Q21"}  # remove once the project owner approves the wording

SOURCE_NAMES = [
    (r"USER-2026-09-22-(\d+)", r"project owner, 22 Sep 2026 (decision \1)"),
    (r"USER-2026-09-22", "project owner, 22 Sep 2026"),
    (r"SDCEP-(\d{4})", r"SDCEP \1"),
    (r"NHSE-2025", "NHS England 2025"),
    (r"AAE-2009", "AAE 2009 terminology"),
    (r"dentist's call", "OUR CALL - no source sets this"),
]


def source(text, width=420):
    for pat, rep in SOURCE_NAMES:
        text = re.sub(pat, rep, text)
    return text if len(text) <= width else text[:width].rstrip() + "…"


def cell(text):
    return str(text).replace("|", "/").replace("\n", " ").strip()


def build(p, protocol_path):
    labels = p["fixed_text"]["option_labels"]
    out = [
        "# Form A — triage protocol review", "",
        f"Protocol: `{protocol_path}` v{p['protocol_version']}, review_status `{p['review_status']}`.",
        f"Generated from the file on {datetime.date.today():%Y-%m-%d} by `make_form_a.py` (research-pm). "
        "Do not edit the YAML;", "write in this form and we will apply the changes.", "",
        "For each row: **Agree / Change / Remove**, and if Change, what it should say.",
        "\"Source\" is what we read; \"our call\" means no guideline sets it and the",
        "project decided it. The wording in *Statement* is what the patient's result",
        "may be based on, not what they are shown.", "",
        "## 1. Levels and time frames", "",
        "| Level | Time frame we use | On-screen headline | Agree / Change |", "|---|---|---|---|",
    ]
    for lv in LEVELS:
        d = p["levels"][lv]
        out.append(f"| {lv} | {d['time_frame']} | \"{cell(d['headline'])}\" | |")
    out += ["", "Source for all four: SDCEP *Management of Acute Dental Problems* 2nd ed.",
            "(March 2026), \"Timescales for treatment\", and NHS England's 2025 unscheduled",
            "dental care guidance §3. EMERGENCY shows one screen with no phone number",
            "(user's decision); ROUTINE has no window in any source.", "",
            "## 2. Criteria", "",
            "Level = how soon. **floor** means code forces EMERGENCY on this alone, before",
            "the model sees anything. **checklist** means the criterion is decided by a",
            "Yes/No row the patient answers; **narrative** means the model must find it in",
            "the patient's own words.", ""]
    for lv in LEVELS:
        out += ["", f"### {lv}", "",
                "| id | Statement | Decided from | floor | how | Agree / Change / Remove |",
                "|---|---|---|---|---|---|"]
        for c in p["criteria"]:
            if c["level"] == lv:
                how = "narrative" if c["kind"] == "narrative" else "checklist / photo"
                out.append(f"| {c['id']} | {cell(c['statement'])} | {cell(source(c['source']))} | "
                           f"{'yes' if c.get('floor') else ''} | {how} | |")
    out += ["", "## 3. Questions the patient is asked", "",
            "Checklist rows are a Yes/No form, all rows at once. Chat rows are answered in",
            "their own words. Nothing here names a drug or a dose.", "",
            "| id | Input | Question as the patient sees it | Agree / Change |", "|---|---|---|---|"]
    for q in p["questions"]:
        kind = q["input"] + (f" {q['group']}" if q.get("group") else "")
        if q.get("options"):
            kind += " (options: " + " / ".join(labels[o] for o in q["options"]) + ")"
        text = cell(q["text"])
        if q["id"] in PENDING_WORDING:
            text += " *(new in v0.2; wording awaiting the project owner's approval)*"
        out.append(f"| {q['id']} | {kind} | {text} | |")
    ft = p["fixed_text"]
    out += ["", "## 4. Fixed text shown to every patient", "",
            "| Where | Text | Agree / Change |", "|---|---|---|"]
    for i, line in enumerate(p["limitations"], 1):
        out.append(f"| Limitations line {i}, shown with every result | {cell(line)} | |")
    out += [f"| Safety net, on every result | {cell(p['safety_net'])} | |",
            f"| disclaimer | {cell(ft['disclaimer'])} | |",
            f"| routine_advice | {cell(ft['routine_advice'])} | |",
            f"| photo_finding_phrase | {cell(ft['photo_finding_phrase'])} | |",
            f"| Shown above each Yes/No checklist | {cell(ft['checklist_intro'])} | |",
            f"| Answer buttons | {' / '.join(labels.values())} | |",
            f"| Re-ask, when a chat answer is unclear | {cell(p['reask_template'])} | |",
            "", "## 5. Sign-off", "",
            "Nothing in the product may be described as reviewed until this is signed.",
            "Only you may set `review_status`; research-pm will not.", "",
            "- [ ] I have reviewed the levels, criteria, questions and fixed text above.",
            "- [ ] Changes required are written in this form.",
            "- Name, registration number, date:", "",
            "_________________________________________________", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", default="llm/protocol/triage_protocol.yaml")
    ap.add_argument("--out", default=str(HERE / "form-a-protocol.md"))
    args = ap.parse_args()
    p = yaml.safe_load((ROOT / args.protocol).read_text(encoding="utf-8"))
    Path(args.out).write_text(build(p, args.protocol), encoding="utf-8")
    print(f"wrote {args.out} from {args.protocol} v{p['protocol_version']}")


if __name__ == "__main__":
    main()
