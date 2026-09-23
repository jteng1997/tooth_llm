"""Checklist UI test for src/webapp_index.html in headless Microsoft Edge.

No server, GPU, Ollama or port: the page is copied to a temp folder, a test
script is appended, and Edge runs it from a file:// URL. Checks the checklist
state handling, then that the page has no horizontal overflow at phone widths
(360 and 320 px, via iframes: headless Edge won't size a window below ~477 px).

    .venv/Scripts/python tests/test_page_checklist_edge.py [--screenshots DIR]

Exits 1 on any FAIL, on an uncaught page error, or if Edge is missing.

Written by app-dev (T9), adopted into tests/ by qa-engineer 2026-09-23 with
app-dev's post-T9 edits: showChecklist takes (rows, intro, group), and rows
carry the server's option objects.
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "src" / "webapp_index.html"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PHONE_WIDTHS = (360, 320)

# Fixture rows, not the protocol: this tests the page, not the wording.
YES_NO = [{"label": "Yes", "value": True}, {"label": "No", "value": False}]
A = [{"id": f"A{i}", "field": f"f{i}", "options": YES_NO,
      "text": f"Fixture checklist question number {i}, long enough to wrap on a phone?"}
     for i in range(1, 11)]
B = [{"id": f"B{i}", "field": f"b{i}", "options": YES_NO,
      "text": f"Fixture follow-up question {i}?"} for i in range(1, 4)]
B.append({"id": "B_opt", "field": "b_opt", "text": "Fixture question with three options?",
          "options": YES_NO + [{"label": "Not sure", "value": None}]})

STATE_TESTS = r"""
const log = [];
const t = (name, ok) => log.push((ok ? "PASS " : "FAIL ") + name);
const pick = (i, k) => { const el = document.querySelector(`input[name="cl-${i}"][value="${k}"]`); el.checked = true; el.dispatchEvent(new Event("change")); };
try{
  $("interview-card").hidden = false;
  showChecklist(A, null, "A");
  t("A renders " + A.length + " rows", $("checklist-rows").querySelectorAll("fieldset").length === A.length);
  t("rows without options get Yes/No", [...$("checklist-rows").querySelectorAll("fieldset")].every(f => f.querySelectorAll("input").length === 2));
  t("intro fallback shown when the step has none", $("checklist-intro").textContent !== "");
  t("nothing pre-selected", !document.querySelector("#checklist input:checked"));
  t("submit disabled at start", $("checklist-submit").disabled);
  t("chat input (with Skip) hidden during a checklist", $("chat-input").hidden);
  for(let i = 0; i < A.length - 1; i++) pick(i, 1);
  t("submit disabled with one row left", $("checklist-submit").disabled && $("checklist-status").textContent.startsWith("1 "));
  pick(A.length - 1, 0);
  const a = checklistAnswers();
  t("submit enabled when all answered", !$("checklist-submit").disabled);
  t("answers are booleans keyed by row id", Object.keys(a).length === A.length && a.A1 === false && a.A10 === true);
  t("checklist group is remembered for the submit", checklistGroup === "A");
  pick(0, 0);
  t("changing an answer keeps one value per row", document.querySelectorAll('input[name="cl-0"]:checked').length === 1 && checklistAnswers().A1 === true);
  hideChecklist();
  showChecklist(B, "Intro from server.", "B");
  t("server intro shown", $("checklist-intro").textContent === "Intro from server.");
  t("second checklist replaces the first", $("checklist-rows").querySelectorAll("fieldset").length === B.length);
  t("row options rendered (3)", $("checklist-rows").querySelectorAll("fieldset")[3].querySelectorAll("input").length === 3);
  pick(0, 0); pick(1, 1); pick(2, 1);
  t("submit disabled until the options row is answered", $("checklist-submit").disabled);
  pick(3, 2);
  const b = checklistAnswers();
  t("'Not sure' is a present null", "B_opt" in b && b.B_opt === null && !$("checklist-submit").disabled);
  setChecklistEnabled(false);
  t("disable locks inputs and submit", $("checklist-submit").disabled && document.querySelector("#checklist input").disabled);
  setChecklistEnabled(true);
  t("re-enable restores submit", !$("checklist-submit").disabled);
  resetPage();
  t("reset hides the checklist and clears it", $("checklist").hidden && !$("checklist-rows").children.length && !$("checklist-intro").textContent && !$("chat-input").hidden);
  $("interview-card").hidden = false;
  showChecklist(B, null, "B"); pick(0, 0); pick(3, 2);  // leave B on screen for the layout check
}catch(e){ log.push("FAIL exception: " + e); }
const vw = document.documentElement.clientWidth, sw = document.documentElement.scrollWidth;
log.push((sw <= vw ? "PASS " : "FAIL ") + `no horizontal overflow at ${vw}px (content ${sw}px)`);
if(window.parent !== window) window.parent.postMessage(log.join("\n"), "*");
const out = document.createElement("pre"); out.id = "test-log"; out.textContent = log.join("\n");
document.body.prepend(out);
"""

FRAME = """<!doctype html><html><body style="margin:0;display:flex;gap:10px">
%s
<pre id="test-log"></pre>
<script>
const got = [];
window.addEventListener("message", e => {
  got.push(e.data.split("\\n").filter(l => l.includes("overflow")).join("\\n"));
  document.getElementById("test-log").textContent = got.join("\\n");
});
</script></body></html>"""


def run_edge(url: str, profile: Path, *extra) -> tuple:
    proc = subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run",
                           f"--user-data-dir={profile}", "--enable-logging=stderr", "--v=0",
                           "--virtual-time-budget=3000", *extra, url],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120)
    return proc.stdout, proc.stderr


def test_log(dom: str) -> list:
    m = re.search(r'<pre id="test-log">(.*?)</pre>', dom, re.S)
    return html.unescape(m.group(1)).splitlines() if m else ["FAIL no test log (page script did not run)"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screenshots", help="folder for phone/desktop screenshots")
    args = ap.parse_args()
    if not EDGE.exists():
        print(f"FAIL Edge not found at {EDGE}")
        sys.exit(1)

    tmp = Path(tempfile.mkdtemp(prefix="page_edge_"))
    try:
        page = PAGE.read_text(encoding="utf-8")
        page = re.sub(r'<link rel="stylesheet" href="https://fonts[^>]*>', "", page)  # offline
        script = f"<script>const A = {json.dumps(A)}, B = {json.dumps(B)};{STATE_TESTS}</script>"
        (tmp / "harness.html").write_text(page.replace("</body>", script + "</body>"), encoding="utf-8")
        frames = "\n".join(f'<iframe src="harness.html" style="width:{w}px;height:1600px;border:0"></iframe>'
                           for w in PHONE_WIDTHS)
        (tmp / "frame.html").write_text(FRAME % frames, encoding="utf-8")
        profile = tmp / "profile"

        lines, errors = [], []
        dom, err = run_edge((tmp / "harness.html").as_uri(), profile, "--dump-dom")
        lines += [l for l in test_log(dom) if "overflow" not in l]  # desktop-width overflow isn't the point
        errors += [l for l in err.splitlines() if "Uncaught" in l]
        dom, err = run_edge((tmp / "frame.html").as_uri(), profile, "--window-size=800,1600", "--dump-dom")
        phone = [l for l in test_log(dom) if l]
        lines += phone if len(phone) == len(PHONE_WIDTHS) else ["FAIL phone-width frames did not report"]
        errors += [l for l in err.splitlines() if "Uncaught" in l]
        lines += [f"FAIL page error: {e}" for e in errors]

        if args.screenshots:
            out = Path(args.screenshots)
            out.mkdir(parents=True, exist_ok=True)
            run_edge((tmp / "frame.html").as_uri(), profile, "--window-size=800,1600",
                     f"--screenshot={out / 'checklist_phone.png'}")
            run_edge((tmp / "harness.html").as_uri(), profile, "--window-size=1000,1400",
                     f"--screenshot={out / 'checklist_desktop.png'}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n".join(lines))
    failed = [l for l in lines if l.startswith("FAIL")]
    print(f"{len(lines) - len(failed)}/{len(lines)} PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
