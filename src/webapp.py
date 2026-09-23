"""Local demo server: photos in, screening result out.

    python src/webapp.py          # then open http://localhost:8000

Wires the existing pieces together and adds nothing clinical of its own:

    upload      -> pipeline.build_findings() + segmentation/caries overlays
    interview   -> interview.Interview (questions, then evidence-checked JSON)
    result      -> triage.assess() decides urgency (assessment 2.0),
                   explain.Explanation words it

Any EMERGENCY result is the one fixed emergency screen: no explanation call,
so a red-flag stop never waits on the language model.

Everything runs on this machine: Ollama for the language model, the local
weights for vision. Sessions are kept in memory, so restarting the server
drops them — it is a demo, not a deployment.
"""
import base64
import io
import json
import sys
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from caries_tool import CariesDetector, annotate, crop_tooth
from explain import Explanation, fdi_label
from interview import DEFAULT_MODEL, Interview
from pipeline import build_findings
from retrieval import Knowledge
from segment_tool import segment_teeth_mask
import triage

REPO_ROOT = Path(__file__).resolve().parent.parent
UPLOADS = REPO_ROOT / "runs" / "webapp_uploads"
INDEX_HTML = Path(__file__).resolve().parent / "webapp_index.html"

# Fixed patient-facing wording is triage.py's, never this file's or the page's.
DISCLAIMER = triage.DISCLAIMER
FINDING_PHRASE = triage.FINDING_PHRASE

app = FastAPI(title="Dental screening demo")
SESSIONS = {}
_knowledge = None


def knowledge() -> Knowledge:
    global _knowledge
    if _knowledge is None:
        _knowledge = Knowledge()
    return _knowledge


def _overlay_png(image_path: Path, view: str) -> tuple:
    """Segmentation overlay + one annotated crop per flagged tooth."""
    image = cv2.imread(str(image_path))
    mask = segment_teeth_mask(str(image_path), view=view)
    detector = CariesDetector()

    rng = np.random.default_rng(3)
    colour = np.zeros_like(image)
    for fdi in np.unique(mask):
        if fdi:
            colour[mask == fdi] = rng.integers(70, 255, 3)
    overlay = cv2.addWeighted(image, 0.55, colour, 0.45, 0)

    crops = []
    for fdi in sorted(int(v) for v in np.unique(mask) if v):
        ys, xs = np.where(mask == fdi)
        cv2.putText(overlay, str(fdi), (int(xs.mean()) - 14, int(ys.mean()) + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        crop, _, _ = crop_tooth(image, mask, fdi)
        findings = detector.findings(crop)
        if findings:
            crops.append({
                "fdi": str(fdi),
                "name": fdi_label(str(fdi)),
                "confidence": findings[0]["confidence"],
                "image": _to_data_uri(annotate(crop, findings)),
            })
    return _to_data_uri(overlay), crops


def _to_data_uri(image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("could not encode image")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


@app.get("/")
def index():
    return FileResponse(INDEX_HTML)


@app.post("/api/analyse")
async def analyse(upper: UploadFile = None, lower: UploadFile = None):
    if not upper and not lower:
        raise HTTPException(400, "upload an upper photo, a lower photo, or both")

    session_id = uuid.uuid4().hex[:12]
    folder = UPLOADS / session_id
    folder.mkdir(parents=True, exist_ok=True)

    paths = {}
    for view, upload in (("upper", upper), ("lower", lower)):
        if upload is None:
            continue
        data = await upload.read()
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(400, f"could not read the {view} image")
        path = folder / f"{view}.jpg"
        cv2.imwrite(str(path), image)
        paths[view] = path

    findings = build_findings(str(paths.get("upper", "")) or None,
                              str(paths.get("lower", "")) or None)
    views = {}
    for view, path in paths.items():
        overlay, crops = _overlay_png(path, view)
        views[view] = {
            "overlay": overlay,
            "crops": crops,
            "teeth_detected": findings["arches"][view]["teeth_detected"],
            "quality": findings["image_quality"][view],
        }

    # allow_unreviewed: the triage protocol is DRAFT-UNREVIEWED (development only).
    session = Interview(DEFAULT_MODEL, allow_unreviewed=True)
    step = session.start()
    SESSIONS[session_id] = {"findings": findings, "interview": session}

    return JSONResponse({"session": session_id, "findings": findings,
                         "views": views, "step": step,
                         "disclaimer": DISCLAIMER})


@app.post("/api/answer")
def answer(session: str = Form(...), message: str = Form(...)):
    """The answer to the open chat question. Returns the next step
    (interface.md 2.1); on "done" the page asks for the result itself."""
    interview = _interview(session)
    if not _pending(interview, "chat"):
        raise HTTPException(409, "no chat question is open")
    return JSONResponse({"step": interview.reply(message)})


@app.post("/api/checklist")
def checklist(session: str = Form(...), group: str = Form(...), answers: str = Form(...)):
    """One whole checklist. `answers` is JSON, {question_id: true|false|null}
    for every row, where null is "not sure" on a row that offers it. The page
    enforces this too, but the server never trusts it: an unanswered row must
    not reach the interview as a "no" (hard rule 7)."""
    interview = _interview(session)
    pending = _pending(interview, "checklist")
    if not pending or pending[1] != group:
        raise HTTPException(409, f"checklist {group} is not the open step")
    try:
        parsed = json.loads(answers)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"answers is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "answers must be an object of question id -> answer")
    try:
        step = interview.submit_checklist(group, parsed)
    except ValueError as exc:  # missing row, null, or a value that isn't allowed
        raise HTTPException(400, str(exc))
    return JSONResponse({"step": step})


def _interview(session: str) -> Interview:
    state = SESSIONS.get(session)
    if state is None:
        raise HTTPException(404, "unknown session — reload and analyse again")
    return state["interview"]


def _pending(interview: Interview, kind: str):
    pending = interview.pending
    return pending if pending and pending[0] == kind else None


@app.post("/api/reset")
def reset(session: str = Form(...)):
    """Forget a session when the page starts over with new photos."""
    SESSIONS.pop(session, None)
    return JSONResponse({"ok": True})


@app.post("/api/result")
def result(session: str = Form(...)):
    state = SESSIONS.get(session)
    if state is None:
        raise HTTPException(404, "unknown session — reload and analyse again")

    interview = state["interview"]
    if _pending(interview, "checklist"):
        # No result, and no "skip to result", before a checklist is answered:
        # skipping checklist A would skip every red-flag question.
        raise HTTPException(409, "answer the open checklist first")
    # A finished interview already extracted on its last turn; only an early
    # "skip to result" still needs one. extract() refuses before checklist A,
    # which the 409 above already covers — this keeps any other refusal a 400
    # rather than a 500.
    try:
        symptoms = interview.symptoms if interview.done else interview.extract()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # allow_unreviewed: the triage protocol is DRAFT-UNREVIEWED (development only).
    assessment = triage.assess(state["findings"], symptoms, interview.messages,
                               DEFAULT_MODEL, allow_unreviewed=True)
    state["assessment"] = assessment
    state.pop("explanation", None)
    reply = {"symptoms": symptoms, "assessment": assessment, "explanation": None,
             "flagged_names": [f"{fdi_label(t)} ({t})" for t in assessment["flagged_teeth"]],
             "finding_phrase": FINDING_PHRASE, "disclaimer": DISCLAIMER}
    if assessment["urgency"] == "EMERGENCY":
        return JSONResponse(reply)  # the fixed emergency screen: no prose, no follow-ups

    # allow_unreviewed: the knowledge files are still DRAFT-UNREVIEWED, and
    # this is a development demo. A real deployment must not pass this.
    explanation = Explanation(state["findings"], symptoms, DEFAULT_MODEL,
                              allow_unreviewed=True, knowledge=knowledge(),
                              assessment=assessment)
    reply["explanation"] = explanation.first_response()
    state["explanation"] = explanation
    return JSONResponse(reply)


@app.post("/api/ask")
def ask(session: str = Form(...), message: str = Form(...)):
    state = SESSIONS.get(session)
    if state is None or "explanation" not in state:
        raise HTTPException(404, "get the result first")
    explanation = state["explanation"]
    answer = explanation.ask(message)
    # A red flag raised during follow-up questions recomputes the assessment
    # (triage design section 1.6); hand the new one back so the page switches.
    latest = explanation.assessment
    if (latest.get("schema_version") == "2.0"
            and latest["urgency"] != state["assessment"]["urgency"]):
        state["assessment"] = latest
        return JSONResponse({"answer": answer, "assessment": latest})
    return JSONResponse({"answer": answer})


if __name__ == "__main__":
    import uvicorn

    UPLOADS.mkdir(parents=True, exist_ok=True)
    print("open http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
