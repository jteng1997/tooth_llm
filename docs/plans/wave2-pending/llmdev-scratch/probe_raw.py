import runpy, sys
sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import explain
real = explain.chat
def logged(messages, model=None, **kw):
    out = real(messages, model, **kw)
    if explain.places_pain(out, None):
        print("   [REJECTED DRAFT]", out.replace("\n", " "))
    return out
explain.chat = logged
runpy.run_path(r"C:\Users\user\.claude\jobs\480511cf\tmp\llmdev\probe_explain.py", run_name="__main__")
