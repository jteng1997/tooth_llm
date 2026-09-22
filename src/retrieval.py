"""Retrieval over the llm/knowledge/ fact sheets.

Step 4 of llm/README.md: one chunk per `##` section, multilingual-e5-small
embeddings, plain cosine top-k. No vector database — 32 sections fit in a
single matrix, and a brute-force dot product over them is instant.

    python src/retrieval.py "does brushing harder fix a cavity?"
    python src/retrieval.py --rebuild

The index is cached in models/knowledge_index.npz and rebuilt whenever a
knowledge file changes. e5 models need their "query: " / "passage: "
prefixes — without them the scores are noticeably worse.

Each chunk keeps its file's `review_status`, so the explanation step can
refuse to ship anything still marked DRAFT-UNREVIEWED.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = REPO_ROOT / "llm" / "knowledge"
INDEX_PATH = REPO_ROOT / "models" / "knowledge_index.npz"
EMBED_MODEL = "intfloat/multilingual-e5-small"
TOP_K = 4

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _front_matter(text: str) -> dict:
    match = FRONTMATTER.match(text)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"')
    return fields


def load_chunks() -> list:
    """One chunk per `##` section, carrying its file's metadata."""
    chunks = []
    for path in sorted(KNOWLEDGE_DIR.glob("[0-9][0-9]_*.md")):
        text = path.read_text(encoding="utf-8")
        meta = _front_matter(text)
        body = FRONTMATTER.sub("", text)
        sections = re.split(r"^## ", body, flags=re.MULTILINE)[1:]
        for section in sections:
            heading, _, content = section.partition("\n")
            content = content.strip()
            if not content:
                continue
            chunks.append({
                "file": path.name,
                "doc_id": meta.get("id", path.stem),
                "review_status": meta.get("review_status", "UNKNOWN"),
                "heading": heading.strip(),
                "text": content,
            })
    return chunks


def _fingerprint(chunks: list) -> str:
    payload = json.dumps([(c["file"], c["heading"], c["text"]) for c in chunks], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Knowledge:
    def __init__(self, rebuild: bool = False):
        self.chunks = load_chunks()
        fingerprint = _fingerprint(self.chunks)
        if not rebuild and INDEX_PATH.exists():
            cached = np.load(INDEX_PATH, allow_pickle=True)
            if str(cached["fingerprint"]) == fingerprint:
                self.embeddings = cached["embeddings"]
                self._model = None
                return
        self._model = self._load_model()
        passages = [f"passage: {c['heading']}\n{c['text']}" for c in self.chunks]
        self.embeddings = self._encode(passages)
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.savez(INDEX_PATH, embeddings=self.embeddings, fingerprint=fingerprint)

    @staticmethod
    def _load_model():
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(EMBED_MODEL)

    def _encode(self, texts: list) -> np.ndarray:
        if self._model is None:
            self._model = self._load_model()
        return self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    def search(self, query: str, k: int = TOP_K) -> list:
        vector = self._encode([f"query: {query}"])[0]
        scores = self.embeddings @ vector
        order = np.argsort(-scores)[:k]
        return [{**self.chunks[i], "score": round(float(scores[i]), 4)} for i in order]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*")
    ap.add_argument("-k", type=int, default=TOP_K)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    knowledge = Knowledge(rebuild=args.rebuild)
    print(f"{len(knowledge.chunks)} sections indexed from {KNOWLEDGE_DIR.name}/")
    if not args.query:
        return
    for hit in knowledge.search(" ".join(args.query), args.k):
        print(f"\n[{hit['score']:.3f}] {hit['file']} — {hit['heading']}  ({hit['review_status']})")
        print("  " + hit["text"].replace("\n", "\n  ")[:300])


if __name__ == "__main__":
    main()
