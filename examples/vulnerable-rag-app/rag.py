"""RAG retriever.

Deliberately simple: keyword-overlap scoring against the bundled corpus.
A real production RAG would use embeddings + a vector store. The
vulnerability is identical either way: untrusted retrieved content is
concatenated into the model's prompt without sanitization (vulnerability
#1 from the README).

We use the simpler retriever to keep the demo dependency tree small and
the vulnerability obvious. The structure of the code mirrors what a real
RAG pipeline does at the relevant layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpus"
_WORD_RE = re.compile(r"[A-Za-z]{3,}")


@dataclass(frozen=True)
class Document:
    name: str
    content: str

    @property
    def tokens(self) -> set[str]:
        return {w.lower() for w in _WORD_RE.findall(self.content)}


def _load_corpus() -> list[Document]:
    docs: list[Document] = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        docs.append(Document(name=path.name, content=path.read_text()))
    return docs


_CORPUS_CACHE: list[Document] | None = None


def get_corpus() -> list[Document]:
    global _CORPUS_CACHE
    if _CORPUS_CACHE is None:
        _CORPUS_CACHE = _load_corpus()
    return _CORPUS_CACHE


def retrieve(query: str, k: int = 2) -> list[Document]:
    """Return the top-k documents by token-overlap with the query."""
    query_tokens = {w.lower() for w in _WORD_RE.findall(query)}
    if not query_tokens:
        return []
    scored = [
        (len(query_tokens & d.tokens), d)
        for d in get_corpus()
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    # Filter out zero-overlap matches; return top k of the rest.
    return [doc for score, doc in scored if score > 0][:k]
