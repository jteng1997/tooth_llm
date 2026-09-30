"""Build the dev end-to-end keys for src/check_e2e.py (research-pm, 2026-09-30).

    .venv/Scripts/python labels/dev/build_e2e_dev_keys.py

Writes e2e_dev_keys.json next to this file. DEV: anyone may read it and tune
on it. Built only from dev material: the keys in triage_dev_keys.json
(protocol v0.3) and their P7 patient_words. No held-out content is read.

Only the cases that reach the chat are kept (no red flag, pain present): the
others end on checklist A, so the chat extraction this set measures never
runs. Dev P7 wrote one message per case (the triage template), not one answer
per question, so every chat question the interview may put (Q10, Q11, Q12,
Q17, Q18) is answered with that whole message, and a re-ask gets it again.
A field the key leaves null is absent from the text by P7's own checks, so
its question stays unsettled, as for a patient who cannot say. This differs
from the held-out e2e set, whose P7 script answers each question on its own;
say so wherever the two are compared.

Deterministic: re-running gives byte-identical output. The build stops if a
key's level disagrees with the live protocol, if a checklist value is one its
row does not offer, or if runs/p7/generated_dev.json (when present) holds a
different accepted text for a case.
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import protocol as protocol_mod  # noqa: E402

SOURCE = HERE / "triage_dev_keys.json"
OUT = HERE / "e2e_dev_keys.json"
# runs/ is local only; from a worktree it sits in the main checkout.
P7_GENERATED = next((p for p in (ROOT / "runs/p7/generated_dev.json",
                                 ROOT.parents[2] / "runs/p7/generated_dev.json") if p.exists()), None)
CHAT = ["Q10", "Q11", "Q12", "Q17", "Q18"]
KEEP = ["archetype", "key_level", "emergency_route", "criteria_met", "boundary", "style",
        "facts", "symptoms", "visual_summary", "id"]


def expected_questions(proto, symptoms):
    """Checklist A, then (with pain) checklist B and the chat questions, in the
    order check_e2e reports them. Only called for chat-reaching keys."""
    a = [q.id for q in proto.questions if q.input == "yesno_checklist" and q.group == "A"]
    b = [q.id for q in proto.questions if q.input == "yesno_checklist" and q.group == "B"
         and q.applies(symptoms)]
    chat = [q for q in CHAT if next(x for x in proto.questions if x.id == q).applies(symptoms)]
    return a + b + chat


def main():
    proto = protocol_mod.load(allow_unreviewed=True)   # dev keys are built on the live draft
    src_bytes = SOURCE.read_bytes()
    src = json.loads(src_bytes)
    if src["_meta"].get("split") != "dev" or src["_meta"]["protocol_version"] != proto.version:
        raise SystemExit(f"{SOURCE.name} is not a dev key file on protocol v{proto.version}")
    rows = {q.id: q for q in proto.questions}
    generated = None
    if P7_GENERATED:
        generated = json.loads(P7_GENERATED.read_text(encoding="utf-8"))["cases"]

    keys, skipped = [], []
    red_flags = [q.fields[0] for q in proto.questions if q.red_flag]
    for k in sorted(src["keys"], key=lambda x: x["id"]):
        s = k["symptoms"]
        if any(s.get(f) is True for f in red_flags) or s.get("pain_present") is not True:
            continue
        words = k.get("patient_words")
        if not words:
            skipped.append((k["id"], "no P7 text"))
            continue
        if generated is not None:
            g = generated.get(k["id"], {})
            if g.get("status") != "accepted" or g.get("text") != words:
                raise SystemExit(f"{k['id']}: P7 text in the key file differs from the "
                                 "accepted text in runs/p7/generated_dev.json")
        visual = {"images_usable": k["visual_summary"]["images_usable"],
                  "flagged_teeth": [t["fdi"] for t in k["visual_summary"]["flagged_teeth"]],
                  "unexpected_missing_teeth": [t["fdi"] for t in
                                               k["visual_summary"]["unexpected_missing_teeth"]]}
        level = proto.protocol_level(s, visual)
        if level != k["key_level"]:
            raise SystemExit(f"{k['id']}: key {k['key_level']}, protocol v{proto.version} gives {level}")
        expected = expected_questions(proto, s)
        for qid in expected:
            q = rows[qid]
            if q.input == "yesno_checklist" and not q.allows(s.get(q.fields[0])):
                raise SystemExit(f"{k['id']}: {s.get(q.fields[0])!r} is not an answer row {qid} offers")
        key = {f: k[f] for f in KEEP}
        key.update(expected_questions=expected, expected_stop_question=None, opening=words,
                   script={q: words for q in expected if q in CHAT},
                   p7={"source": "triage_dev_keys.json patient_words (dev P7, triage template)",
                       **k.get("p7", {})})
        keys.append(key)

    meta = {"author": "research-pm", "date": "2026-09-30", "split": "dev",
            "status": "DEV: anyone may read and tune on it; never mixed with held-out",
            "protocol_version": proto.version,
            "key_basis": f"labels/dev/triage_dev_keys.json (protocol v{proto.version}, "
                         "DRAFT-UNREVIEWED): the keys that reach the chat",
            "source_sha256": hashlib.sha256(src_bytes.replace(b"\r\n", b"\n")).hexdigest(),
            "script_design": "every chat question is answered with the case's whole dev P7 "
                             "message (one message per case, not one answer per question); "
                             "opening = the same message"}
    OUT.write_bytes(json.dumps({"_meta": meta, "keys": keys}, indent=1,
                               ensure_ascii=False).encode("utf-8"))
    from collections import Counter
    print(f"{len(keys)} chat-reaching dev keys -> {OUT.name}:",
          dict(Counter(k["key_level"] for k in keys)), "boundary", sum(k["boundary"] for k in keys))
    for cid, why in skipped:
        print(f"  skipped {cid}: {why}")


if __name__ == "__main__":
    main()
