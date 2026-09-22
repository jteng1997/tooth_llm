"""Run the scripted evaluation suite from llm/eval.

    python src/run_evals.py --models qwen3:14b qwen3:4b --synthetic 60

Test 1 (rules) is deterministic and model-free, so it runs once. Tests 2
and 3 run per model, which is the size comparison the eval spec asks for:
the development model against the size you would actually embed.

Test 4 is the human one. This writes eval_samples.md — 30 explanations
spanning the urgency levels — for a dentist to score on clarity, wording,
hedging and referral advice.

Results land in runs/evals/.
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import check_faithfulness
import check_symptoms
from eval_data import generate
from retrieval import Knowledge

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "runs" / "evals"
SAMPLE_TARGET = 30


def test1_rules() -> dict:
    """Deterministic, so shell out to the existing checker and record it."""
    proc = subprocess.run([sys.executable, str(Path(__file__).parent / "check_rules.py")],
                          capture_output=True, text=True)
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout else ""
    print(proc.stdout.strip().splitlines()[-1] if proc.stdout else proc.stderr)
    return {"passed": proc.returncode == 0, "summary": tail}


def write_samples(faithfulness: dict, path: Path) -> int:
    """Test 4 prep: explanations spanning urgency levels, for a human."""
    by_urgency = defaultdict(list)
    for case in faithfulness["cases"]:
        by_urgency[case["urgency"]].append(case)

    picked, index = [], 0
    while len(picked) < SAMPLE_TARGET and any(len(v) > index for v in by_urgency.values()):
        for urgency in sorted(by_urgency):
            if len(by_urgency[urgency]) > index and len(picked) < SAMPLE_TARGET:
                picked.append(by_urgency[urgency][index])
        index += 1

    lines = ["# Explanation quality review (Test 4)", "",
             "Score each 1-5 on: clarity, medical correctness of wording, appropriate",
             "hedging, and whether the referral advice is right. Add free-text concerns.",
             "", f"{len(picked)} samples across {len(by_urgency)} urgency levels.", ""]
    for case in picked:
        lines += [f"## {case['id']} — {case['urgency']}", "", case["text"].strip(), "",
                  "| clarity | wording | hedging | referral |", "|---|---|---|---|",
                  "|  |  |  |  |", "", "Concerns:", "", "---", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(picked)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen3:14b", "qwen3:4b"])
    ap.add_argument("--synthetic", type=int, default=60,
                    help="Synthetic findings per model for Test 2 (0 = seed cases only)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    knowledge = Knowledge()
    summary = {"test1_rules": test1_rules(), "models": {}}

    if args.synthetic:
        cases = generate(args.synthetic, args.seed)
    else:
        spec = json.loads((REPO_ROOT / "llm" / "eval" / "faithfulness_cases.json").read_text(encoding="utf-8"))
        bases = json.loads((REPO_ROOT / "llm" / "eval" / "rule_cases.json").read_text(encoding="utf-8"))
        cases = [{"id": c["id"], "note": c["note"],
                  "findings": check_faithfulness.build_findings(c, bases),
                  "symptoms": c.get("symptoms")} for c in spec["cases"]]

    for model in args.models:
        print(f"\n===== {model} — Test 2 faithfulness ({len(cases)} cases)")
        faith = check_faithfulness.evaluate(cases, model, knowledge, verbose=False)
        n = faith["n"]
        for rate in ("hallucination", "omission", "contradiction"):
            print(f"  {rate:14s} {faith[rate]}/{n} ({faith[rate] / n:.1%})")

        print(f"===== {model} — Test 3 symptom extraction")
        symptoms = check_symptoms.evaluate(model, verbose=False)
        print(f"  exact dialogues {symptoms['exact']}/{symptoms['n']}"
              f"  field accuracy {symptoms['field_accuracy']:.1%}"
              f"  guessed {symptoms['guessed']}  missed {symptoms['missed']}")

        tag = model.replace(":", "_")
        (OUT_DIR / f"faithfulness_{tag}.json").write_text(
            json.dumps(faith, indent=2, ensure_ascii=False), encoding="utf-8")
        (OUT_DIR / f"symptoms_{tag}.json").write_text(
            json.dumps(symptoms, indent=2, ensure_ascii=False), encoding="utf-8")
        summary["models"][model] = {
            "faithfulness": {k: faith[k] for k in ("n", "hallucination", "omission", "contradiction")},
            "symptoms": {k: symptoms[k] for k in
                         ("n", "exact", "field_accuracy", "guessed", "missed", "per_field_accuracy")},
        }
        if model == args.models[0]:
            count = write_samples(faith, OUT_DIR / "eval_samples.md")
            summary["test4_samples"] = {"model": model, "count": count,
                                        "file": str((OUT_DIR / 'eval_samples.md').relative_to(REPO_ROOT))}

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n===== size comparison")
    header = f"{'model':<12} {'halluc':>8} {'omission':>9} {'contra':>8} {'sympt exact':>12} {'field acc':>10}"
    print(header)
    for model, r in summary["models"].items():
        f, s = r["faithfulness"], r["symptoms"]
        print(f"{model:<12} {f['hallucination'] / f['n']:>7.1%} {f['omission'] / f['n']:>8.1%} "
              f"{f['contradiction'] / f['n']:>7.1%} {s['exact']:>7}/{s['n']:<4} {s['field_accuracy']:>9.1%}")
    print(f"\nwrote {OUT_DIR}")


if __name__ == "__main__":
    main()
