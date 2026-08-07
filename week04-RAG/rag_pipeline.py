"""
Week 04 - RAG workflow for technical accounting research.

Pipeline: load -> chunk -> embed -> retrieve -> assemble grounded context.

Corpus:   ./data/*.txt   (synthetic pooled commission plan)
Queries:  ./RAGprompts.txt (four ASC 340-40 research questions)
Output:   ./retrieved_context.md  (audit trail of what was retrieved, with
          chunk IDs and similarity scores, for each question)

Embedding backend is pluggable:
  - "tfidf"  (default, zero-dependency beyond scikit-learn, fully offline,
              deterministic -- desirable for a reproducible workpaper)
  - "openai" (set OPENAI_API_KEY and pass --backend openai for dense
              semantic retrieval)

Usage:
    python rag_pipeline.py
    python rag_pipeline.py --k 4 --backend openai
"""

from __future__ import annotations

import argparse
import os
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROMPTS = ROOT / "RAGprompts.txt"
OUTPUT = ROOT / "retrieved_context.md"


# --------------------------------------------------------------------------
# 1. LOAD
# --------------------------------------------------------------------------
@dataclass
class Document:
    source: str
    text: str


def load_documents(data_dir: Path = DATA_DIR) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(data_dir.glob("*.txt")):
        docs.append(Document(source=path.name, text=path.read_text(encoding="utf-8")))
    if not docs:
        raise FileNotFoundError(f"No .txt files found in {data_dir}")
    return docs


# --------------------------------------------------------------------------
# 2. CHUNK
# --------------------------------------------------------------------------
@dataclass
class Chunk:
    chunk_id: str
    source: str
    section: str
    text: str
    embedding: np.ndarray | None = field(default=None, repr=False)


# A numbered heading such as "3. FUNDING MECHANISM OF THE POOL" or a bare
# "ADDENDUM" line. Contracts are structurally sectioned, so section-aware
# chunking preserves the citation unit an auditor actually wants to reference.
HEADING_RE = re.compile(r"^(?:\d+\.\s+[A-Z][^a-z\n]{3,}|ADDENDUM)\s*$", re.MULTILINE)


def split_into_sections(doc: Document) -> list[tuple[str, str]]:
    """Return [(section_title, section_body), ...] preserving document order."""
    matches = list(HEADING_RE.finditer(doc.text))
    if not matches:
        return [("Full document", doc.text.strip())]

    sections: list[tuple[str, str]] = []
    preamble = doc.text[: matches[0].start()].strip()
    if preamble:
        sections.append(("Preamble", preamble))

    for i, m in enumerate(matches):
        title = m.group(0).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(doc.text)
        body = doc.text[m.end() : end].strip()
        if body:
            sections.append((title, body))
    return sections


def window(tokens: Sequence[str], size: int, overlap: int):
    step = max(size - overlap, 1)
    for start in range(0, max(len(tokens), 1), step):
        piece = tokens[start : start + size]
        if piece:
            yield piece
        if start + size >= len(tokens):
            break


def chunk_documents(
    docs: list[Document], chunk_tokens: int = 160, overlap: int = 40
) -> list[Chunk]:
    """Section-aware chunking with a sliding word window inside long sections.

    Overlap matters here: the operative facts (3.5% initial vs 0.5% renewal,
    12-month term, 15% renewal discount) sit in adjacent sentences, and a hard
    split between them would strand a fact from its qualifier.
    """
    chunks: list[Chunk] = []
    for doc in docs:
        for s_idx, (title, body) in enumerate(split_into_sections(doc), start=1):
            words = body.split()
            for w_idx, piece in enumerate(window(words, chunk_tokens, overlap), start=1):
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc.source}#S{s_idx}.{w_idx}",
                        source=doc.source,
                        section=title,
                        text=" ".join(piece),
                    )
                )
    return chunks


# --------------------------------------------------------------------------
# 3. EMBED
# --------------------------------------------------------------------------
class TfidfBackend:
    """Deterministic, offline lexical retrieval.

    Word 1-2 grams capture accounting phrases ("renewal option", "New ARR");
    char 3-5 grams keep numerals and percentages ("3.5%", "0.5%", "15%")
    matchable even when tokenization differs between query and contract.
    """

    name = "tfidf"

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.pipeline import FeatureUnion

        self.vec = FeatureUnion(
            [
                ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                         stop_words="english")),
                ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                         sublinear_tf=True)),
            ]
        )

    def fit_transform(self, texts: list[str]) -> np.ndarray:
        return self._norm(self.vec.fit_transform(texts).toarray())

    def transform(self, texts: list[str]) -> np.ndarray:
        return self._norm(self.vec.transform(texts).toarray())

    @staticmethod
    def _norm(m: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(m, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return m / n


class OpenAIBackend:
    """Dense semantic retrieval. Requires OPENAI_API_KEY."""

    name = "openai"

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        from openai import OpenAI  # imported lazily

        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = model

    def _embed(self, texts: list[str]) -> np.ndarray:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        m = np.array([d.embedding for d in resp.data], dtype=float)
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    fit_transform = _embed
    transform = _embed


def get_backend(name: str):
    return {"tfidf": TfidfBackend, "openai": OpenAIBackend}[name]()


# --------------------------------------------------------------------------
# 4. RETRIEVE
# --------------------------------------------------------------------------
class VectorStore:
    def __init__(self, chunks: list[Chunk], backend) -> None:
        self.chunks = chunks
        self.backend = backend
        self.matrix = backend.fit_transform([c.text for c in chunks])
        for c, v in zip(chunks, self.matrix):
            c.embedding = v

    def query(self, text: str, k: int = 3) -> list[tuple[Chunk, float]]:
        q = self.backend.transform([text])[0]
        scores = self.matrix @ q  # cosine: vectors are L2-normalised
        order = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in order]


# --------------------------------------------------------------------------
# 5. QUERIES
# --------------------------------------------------------------------------
QUESTION_RE = re.compile(r"^\d+\.\s+[A-Z]", re.MULTILINE)


def load_questions(path: Path = PROMPTS) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    starts = [m.start() for m in QUESTION_RE.finditer(raw)]
    questions = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(raw)
        questions.append(" ".join(raw[s:e].split()))
    return questions


# --------------------------------------------------------------------------
# 6. ASSEMBLE GROUNDED CONTEXT
# --------------------------------------------------------------------------
def build_report(questions: list[str], store: VectorStore, k: int) -> str:
    lines = [
        "# Retrieved Context — Pooled Commission Plan (ASC 340-40 analysis)",
        "",
        f"Backend: `{store.backend.name}`  |  Chunks indexed: {len(store.chunks)}  "
        f"|  Top-k per question: {k}",
        "",
        "Each question below is answered *only* from the chunks listed under it. "
        "Chunk IDs are `<source>#S<section>.<window>` and scores are cosine "
        "similarity, so every assertion in the memorandum can be traced back to "
        "a specific passage of the plan document.",
        "",
    ]
    for qi, q in enumerate(questions, start=1):
        lines.append(f"## Q{qi}")
        lines.append("")
        lines.append("> " + textwrap.fill(q, 96).replace("\n", "\n> "))
        lines.append("")
        for chunk, score in store.query(q, k=k):
            lines.append(f"### `{chunk.chunk_id}` — {chunk.section}  (score {score:.3f})")
            lines.append("")
            lines.append(textwrap.fill(chunk.text, 96))
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, default=3, help="chunks retrieved per question")
    ap.add_argument("--backend", default="tfidf", choices=["tfidf", "openai"])
    ap.add_argument("--chunk-tokens", type=int, default=160)
    ap.add_argument("--overlap", type=int, default=40)
    args = ap.parse_args()

    docs = load_documents()
    chunks = chunk_documents(docs, args.chunk_tokens, args.overlap)
    store = VectorStore(chunks, get_backend(args.backend))
    questions = load_questions()

    report = build_report(questions, store, args.k)
    OUTPUT.write_text(report, encoding="utf-8")

    print(f"Loaded {len(docs)} document(s), built {len(chunks)} chunks.")
    print(f"Answered {len(questions)} question(s) -> {OUTPUT.name}")
    for qi, q in enumerate(questions, start=1):
        top = store.query(q, k=args.k)
        ids = ", ".join(f"{c.chunk_id} ({s:.2f})" for c, s in top)
        print(f"  Q{qi}: {ids}")


if __name__ == "__main__":
    main()
