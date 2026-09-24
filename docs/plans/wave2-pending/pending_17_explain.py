# DRAFT for task #17 -- insert into src/explain.py after calls_missing_decay(); apply with v0.2.

# User decision 2026-09-23 (sentence B): when the photos found nothing, never
# deny a tooth cause. Photos miss things; only a dentist can tell.
_DENIES_TOOTH_CAUSE = re.compile(
    r"\bnot (?:be )?(?:coming|caused|come|from) (?:from |by )?(?:a|any|your|the|one of your) "
    r"(?:tooth|teeth)\b"
    r"|\b(?:isn't|is not|doesn't|does not|won't|can't be|cannot be|unlikely to be) "
    r"(?:be )?(?:coming|come|caused|from) (?:from |by )?(?:a|any|your|the) (?:tooth|teeth)\b"
    r"|\bnot an? (?:tooth|dental) (?:problem|issue|cause)\b"
    r"|\b(?:nothing|no problem|nothing is) wrong with your teeth\b"
    r"|\byour teeth (?:are|look|seem) (?:fine|healthy|ok|okay|normal|good)\b"
    r"|\bno (?:problems?|issues?) with your teeth\b"
    r"|\b(?:rule[sd]? out|ruling out) (?:a )?(?:tooth|dental)\b", re.I)


# "This does not mean your teeth are fine" is the message we want, not a denial.
_NEGATED = re.compile(r"\b(?:not|n't|never) (?:mean|say|prove|show|tell us)\b[^.]*$", re.I)


def denies_tooth_cause(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        m = _DENIES_TOOTH_CAUSE.search(sentence)
        if m and not _NEGATED.search(sentence[:m.start()]):
            return True
    return False

# In _checked_turn.violations(), after the missing-decay check:
#     if not (decay_or_missing_reported) and denies_tooth_cause(text):
#         found.append("says the pain is not from a tooth or the teeth are fine; the photos "
#                      "can miss a problem and only a dentist can tell what causes the pain")
# where decay_or_missing_reported = any(split_flagged(self.assessment, self.findings)).

# system_explain.md, new hard rule 13:
# 13. If the photos found nothing, never say or imply that the pain is not
#     coming from a tooth, or that the teeth are fine. Say, in substance: the
#     photos did not show a problem, but they can miss one, and only a dentist
#     can tell what is causing the pain.

# tests/test_explain_guardrails.py (NoFindingsDenial):
#  caught on no findings: "No, the pain when biting is not coming from a tooth we found." ,
#    "Your pain is not caused by your teeth.", "Your teeth look fine.",
#    "There is nothing wrong with your teeth."
#  allowed: "The photos did not show a problem, but they can miss one. Only a dentist can tell
#    what is causing your pain.", "No issues were found on any teeth in the photos."
#  checked turn: no-findings session, denial reply -> rewritten.
