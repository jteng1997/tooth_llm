import io
import json
import sys

sys.path.insert(0, r"D:\jonathan\tooth-llm\.claude\worktrees\llm-triage-wave2\src")
import check_symptoms as cs  # noqa: E402
import interview  # noqa: E402
import protocol as P  # noqa: E402

ids = sys.argv[1:]
spec = json.loads(io.open(cs.DIALOGUES, encoding="utf-8").read())
proto = P.load(allow_unreviewed=True)


def llm(messages, schema):
    out = interview.chat(messages, interview.DEFAULT_MODEL, schema=schema)
    raw = json.loads(out)
    last = [m["content"] for m in messages if m["role"] == "user"][-2]
    print(f"   << {last!r}")
    print("   >> " + json.dumps({k: v for k, v in raw.items() if v.get("value") is not None},
                                ensure_ascii=False))
    return out


for case in spec["cases"]:
    if case["id"] not in ids:
        continue
    print(f"== {case['id']}")
    played = cs.run_case(case, interview.DEFAULT_MODEL, proto, llm)
    got = played["symptoms"]
    for f, want in case["expected"].items():
        g = got.get(f)
        ok = (sorted(g or []) == sorted(want)) if isinstance(want, list) else g == want
        print(f"   {'ok ' if ok else 'BAD'} {f}: want {want!r} got {g!r}")
