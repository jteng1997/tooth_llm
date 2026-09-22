"""Urgency assessment: findings (+ symptoms) -> assessment JSON.

Thin wrapper around llm/rules.py, which owns the decision. Per the
architecture rule in llm/README.md, Python decides urgency and the LLM
only verbalises the result — so nothing here interprets, re-ranks or
second-guesses what rules.assess() returns.

    python src/assess.py --findings findings.json \
                         [--symptoms symptoms.json] [--out assessment.json]

With no --symptoms the interview hasn't happened yet; rules.py treats
that as "no symptoms reported", not as "no symptoms present".
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LLM_DIR = REPO_ROOT / "llm"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

import rules  # noqa: E402  (llm/rules.py, kept where the package ships it)


def assess(findings: dict, symptoms: dict = None) -> dict:
    return rules.assess(findings, symptoms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--symptoms")
    ap.add_argument("--out")
    args = ap.parse_args()

    findings = json.loads(Path(args.findings).read_text())
    symptoms = json.loads(Path(args.symptoms).read_text()) if args.symptoms else None
    text = json.dumps(assess(findings, symptoms), indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
