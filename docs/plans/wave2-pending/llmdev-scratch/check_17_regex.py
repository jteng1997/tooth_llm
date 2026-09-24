import re

src = open(r"C:\Users\user\.claude\jobs\480511cf\tmp\llmdev\pending_17_explain.py", encoding="utf-8").read()
ns = {"re": re}
exec(src, ns)
deny = ns["denies_tooth_cause"]
bad = ["No, the pain when biting is not coming from a tooth we found.",
       "Your pain is not caused by your teeth.", "Your teeth look fine.",
       "There is nothing wrong with your teeth.", "It is unlikely to be coming from a tooth.",
       "This is not a dental problem."]
ok = ["The photos did not show a problem, but they can miss one. Only a dentist can tell what "
      "is causing your pain.", "No issues were found on any teeth in the photos.",
      "We cannot say which tooth is causing the pain.",
      "It is not a diagnosis and does not mean your teeth are fine.",
      "Nothing found does not show that the pain is not coming from a tooth.",
      "The pain when biting may be related to the tooth we found, but only a dentist can confirm this."]
print("caught:", [deny(t) for t in bad])
print("passed:", [not deny(t) for t in ok])
