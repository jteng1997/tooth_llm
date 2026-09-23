"""Offline end-to-end test of src/webapp.py: no GPU, no Ollama, no port.

Only the two model calls and the vision step are stubbed. The real
Interview (with the real protocol), the real triage.assess and the real
FastAPI app do the work, so the endpoints are tested against the objects
they actually receive (llm/interface.md 2.1 and 4).

    .venv/Scripts/python tests/test_webapp_offline.py

Exits 1 on the first failure.

Written by app-dev (T9), adopted into tests/ by qa-engineer 2026-09-23.
"""
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import interview as interview_mod  # noqa: E402
import protocol as protocol_mod  # noqa: E402
import triage  # noqa: E402
import webapp  # noqa: E402

PROTOCOL = protocol_mod.load(allow_unreviewed=True)
ROWS = {g: [q for q in PROTOCOL.questions if q.input == "yesno_checklist" and q.group == g]
        for g in ("A", "B")}
FIELD_OF = {q.id: q.fields[0] for q in PROTOCOL.questions}
PAIN_ROW = next(q.id for q in PROTOCOL.questions if q.fields == ["pain_present"])
SWELLING_ROW = next(q.id for q in PROTOCOL.questions if q.fields == ["swelling"])

FINDINGS = {
    "schema_version": "1.0",
    "image_quality": {"upper": {"usable": True, "reasons": []}},
    "arches": {"upper": {"present": True, "teeth_detected": 12}},
    "teeth": {**{str(f): {"present": True, "detections": []} for f in
                 (11, 12, 13, 14, 15, 17, 21, 22, 23, 24, 25)},
              "16": {"present": True, "detections": [{"type": "caries", "confidence": 0.8}]}},
    "unassigned_detections": [],
    "model_versions": {},
}

CALLS = {"extract": 0, "triage": 0, "explain": 0}


def stub_extractor(messages, schema):
    """Stands in for the extraction model: finds nothing, so every chat field
    stays null. The interview's own tests cover extraction itself."""
    CALLS["extract"] += 1
    return json.dumps({f: {"value": None, "quote": None} for f in schema["properties"]})


def stub_triage_llm(model):
    def call(messages, schema):
        CALLS["triage"] += 1
        return json.dumps({"criteria_met": [], "level": "ROUTINE", "uncertain": False})
    return call


class FakeExplanation:
    def __init__(self, findings, symptoms, model, allow_unreviewed=False, knowledge=None,
                 assessment=None):
        CALLS["explain"] += 1
        self.assessment = assessment

    def first_response(self):
        return "explanation text"

    def ask(self, question):
        return "answer to " + question


webapp.build_findings = lambda upper, lower: json.loads(json.dumps(FINDINGS))
webapp._overlay_png = lambda path, view: ("data:x", [])
webapp.Interview = lambda model, allow_unreviewed=False: interview_mod.Interview(
    protocol=PROTOCOL, llm=stub_extractor)
webapp.Explanation = FakeExplanation
webapp.knowledge = lambda: None
triage._default_llm = stub_triage_llm


def run_checks() -> list:
    """Run every check; returns the list of failures (empty when all pass)."""
    global FAILED
    FAILED = []
    client = TestClient(webapp.app)
    _, jpg = cv2.imencode(".jpg", np.zeros((20, 20, 3), np.uint8))
    FILES = {"upper": ("u.jpg", jpg.tobytes(), "image/jpeg")}
    FAILED = []


    def check(cond, msg):
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            FAILED.append(msg)


    def analyse():
        data = client.post("/api/analyse", files=FILES).json()
        return data["session"], data


    def answers(group, **yes):
        out = {q.id: False for q in ROWS[group]}
        out.update(yes)
        return out


    def submit(session, group, values):
        return client.post("/api/checklist", data={"session": session, "group": group,
                                                   "answers": json.dumps(values)})


    r = client.get("/")
    check(r.status_code == 200 and "emergency-card" in r.text, "GET / serves the page")

    # --- first step is checklist A, with the protocol's rows ---------------------
    session, data = analyse()
    step = data["step"]
    check(step["type"] == "checklist" and step["group"] == "A", f"first step is checklist A ({step['type']})")
    check([i["id"] for i in step["items"]] == [q.id for q in ROWS["A"]], "A carries the protocol's rows")
    check(all(i["options"] == [{"label": "Yes", "value": True}, {"label": "No", "value": False}]
              for i in step["items"]), "A rows offer Yes/No only")
    check(data["disclaimer"] == triage.DISCLAIMER, "analyse returns the disclaimer")

    # --- the server refuses everything that would skip checklist A --------------
    check(client.post("/api/result", data={"session": session}).status_code == 409,
          "no result before checklist A (409)")
    check(client.post("/api/answer", data={"session": session, "message": "hi"}).status_code == 409,
          "no chat answer while a checklist is open (409)")
    check(submit(session, "B", answers("B")).status_code == 409, "wrong group refused (409)")
    partial = answers("A")
    del partial[ROWS["A"][0].id]
    check(submit(session, "A", partial).status_code == 400, "missing row refused (400)")
    check(submit(session, "A", {**answers("A"), ROWS["A"][1].id: None}).status_code == 400,
          "null on a Yes/No row refused (400)")
    check(client.post("/api/checklist", data={"session": session, "group": "A",
                                              "answers": "not json"}).status_code == 400,
          "answers that aren't JSON refused (400)")
    check(client.post("/api/checklist", data={"session": session, "group": "A",
                                              "answers": "[1, 2]"}).status_code == 400,
          "answers that aren't an object refused (400)")

    # --- red flag on checklist A: done at once, emergency, no model calls -------
    before = dict(CALLS)
    step = submit(session, "A", answers("A", **{SWELLING_ROW: True})).json()["step"]
    check(step["type"] == "done" and step["red_flag"] is True, f"red flag ends the interview ({step['type']})")
    check(submit(session, "A", answers("A")).status_code == 409, "double submit refused (409)")
    res = client.post("/api/result", data={"session": session}).json()
    a = res["assessment"]
    check(a["urgency"] == "EMERGENCY" and a["headline"] == PROTOCOL.headlines["EMERGENCY"],
          "EMERGENCY with the protocol's fixed headline")
    check(a["decided_by"] == "red_flag_floor", f"decided_by red_flag_floor ({a['decided_by']})")
    check(res["explanation"] is None and CALLS == before, "no extraction, triage or explanation call")
    check(client.post("/api/ask", data={"session": session, "message": "?"}).status_code == 404,
          "no follow-up questions on the emergency screen")

    # --- no pain: straight to done, then a normal result ------------------------
    session, _ = analyse()
    step = submit(session, "A", answers("A")).json()["step"]
    check(step["type"] == "done" and step["red_flag"] is False, "no pain ends the interview")
    check(step["symptoms"]["pain_present"] is False, "the checklist answer is recorded")
    res = client.post("/api/result", data={"session": session}).json()
    a = res["assessment"]
    print("  result:", json.dumps({k: a[k] for k in ("urgency", "headline", "decided_by")}))
    check(a["schema_version"] == "2.0" and a["urgency"] in ("SOON", "ROUTINE", "URGENT"), "assessment 2.0")
    check(a["headline"] == PROTOCOL.headlines[a["urgency"]], "headline is the protocol's, unchanged")
    check(res["explanation"] == "explanation text", "explanation present when not an emergency")
    check(res["flagged_names"] == ["upper right first molar (16)"], f"tooth names {res['flagged_names']}")
    check(res["finding_phrase"] == triage.FINDING_PHRASE, "finding phrase comes from triage.py")
    check(a["safety_net"] == PROTOCOL.safety_net and res["disclaimer"] == triage.DISCLAIMER,
          "safety net and disclaimer on the result")
    check("rule_id" not in a and "rule_id" in a["rules_baseline"], "rule_id only under rules_baseline")
    q = client.post("/api/ask", data={"session": session, "message": "what now?"}).json()
    check(q == {"answer": "answer to what now?"}, f"follow-up question answered {q}")

    # --- pain: checklist B, then the chat questions -----------------------------
    session, _ = analyse()
    step = submit(session, "A", answers("A", **{PAIN_ROW: True})).json()["step"]
    check(step["type"] == "checklist" and step["group"] == "B", "pain leads to checklist B")
    unsure = [i for i in step["items"] if {"label": "Not sure", "value": None} in i["options"]]
    check(bool(unsure), "a B row offers Not sure")
    step = submit(session, "B", {**answers("B"), unsure[0]["id"]: None}).json()["step"]
    check(step["type"] == "question" and step["text"], f"B leads to a chat question ({step['type']})")

    turns = 0
    while step["type"] == "question" and turns < 30:
        step = client.post("/api/answer", data={"session": session, "message": "not sure really"}).json()["step"]
        turns += 1
    check(step["type"] == "done", f"the chat questions end by themselves after {turns} turns")
    check(CALLS["extract"] > 0, "the chat turns used the extractor")
    res = client.post("/api/result", data={"session": session}).json()
    check(res["assessment"]["schema_version"] == "2.0", "result after the chat path")
    check(res["symptoms"][FIELD_OF[unsure[0]["id"]]] is None, "'Not sure' recorded as null")

    # --- reset ------------------------------------------------------------------
    check(client.post("/api/reset", data={"session": session}).json() == {"ok": True}, "reset")
    for endpoint, payload in (("/api/answer", {"session": session, "message": "x"}),
                              ("/api/result", {"session": session}),
                              ("/api/ask", {"session": session, "message": "x"}),
                              ("/api/checklist", {"session": session, "group": "A", "answers": "{}"})):
        check(client.post(endpoint, data=payload).status_code == 404, f"{endpoint} 404 after reset")
    return FAILED


class WebappOffline(unittest.TestCase):
    """One test, so `python -m unittest discover -s tests` counts this file
    once and still reports the rest of the suite (it used to sys.exit() at
    import time, which ended discovery on the spot)."""

    def test_offline_flow(self):
        self.assertEqual(run_checks(), [])


if __name__ == "__main__":
    unittest.main()
