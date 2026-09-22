# LLM layer package — dental screening assistant

This folder contains everything the LLM layer needs. Drop it into the project
root as `llm/` and wire it into the existing pipeline.

## What already exists in this project (do not rebuild)

- SegmentAnyTooth in `vendor/segmentanytooth` — tooth masks + FDI numbers
- A caries/cavity detector — boxes + confidence
- `src/pipeline.py` — runs the vision stack

## What this package adds

```
llm/
  README.md              <- this file
  interface.md           <- the JSON contract between vision and LLM (READ FIRST)
  rules.py               <- urgency decision. Python only. NOT the LLM.
  prompts/
    system_explain.md    <- system prompt for the explanation step
    system_symptoms.md   <- system prompt for the symptom interview
    symptoms_schema.json <- JSON schema for constrained symptom output
  knowledge/             <- RAG corpus, one topic per file
  eval/                  <- test sets + what to measure
```

## Architecture rule (important, do not violate)

```
photos -> vision models -> findings JSON
                                |
user <-> LLM (symptom interview) -> symptoms JSON
                                |
            findings + symptoms -> rules.py -> urgency (Python decides)
                                |
            findings + symptoms + urgency + RAG -> LLM -> explanation
```

The LLM **never** decides urgency and **never** looks at the raw photo.
It only verbalises `rules.py` output and answers questions from the
retrieved knowledge. This is a hard constraint: it makes the system
auditable and testable.

## Build order for Claude Code

1. Read `interface.md`. Make `src/pipeline.py` emit exactly that JSON.
2. Implement `rules.py` as given. Do not change thresholds without a note.
3. Wire the symptom interview using `prompts/system_symptoms.md` +
   `symptoms_schema.json`, with grammar-constrained JSON output
   (llama.cpp GBNF / JSON schema mode).
4. Build retrieval over `knowledge/` (chunk = one `##` section,
   embeddings = bge-small or multilingual-e5-small, plain cosine top-k=4).
5. Wire the explanation step using `prompts/system_explain.md`.
6. Implement the evaluation scripts described in `eval/README.md`.

## Model

Develop against Qwen3 14B Q4_K_M (or Gemma 4 12B). Then re-run the same
evals at 4B and report the gap — that gap is a result for the paper.

## Status of the knowledge and rules

The clinical content here is a DRAFT written from published guidance
(SDCEP MADP, AAE diagnostic terminology, ICCMS, WHO oral health surveys,
ADA/AAPD caries guidance). It is paraphrased, not copied.

**It must be reviewed and signed off by a dentist before use.**
Every knowledge file has a `review_status` field at the top. Do not ship
with any file still marked `DRAFT-UNREVIEWED`.
