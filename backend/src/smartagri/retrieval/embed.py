"""Sentence embeddings for dense retrieval, and the pgvector-backed index.

The model is a small multilingual one that runs on CPU through ONNX (fastembed). It is loaded
lazily and only when EMBEDDINGS_PROVIDER=fastembed, so the package works without it.
"""
from __future__ import annotations

import os
from typing import Callable, List, Optional

from .corpus import Corpus

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"   # 384 dimensions


class FastEmbedder:
    def __init__(self, model: Optional[str] = None):
        from fastembed import TextEmbedding            # optional dependency
        self.model = model or os.environ.get("EMBEDDINGS_MODEL", DEFAULT_MODEL)
        self._model = TextEmbedding(model_name=self.model)

    def __call__(self, texts: List[str]) -> List[List[float]]:
        return [[float(x) for x in v] for v in self._model.embed(texts)]


def make_embedder():
    """Return an embedder, or None when dense retrieval is not configured or not installable."""
    if os.environ.get("EMBEDDINGS_PROVIDER", "none") != "fastembed":
        return None
    try:
        return FastEmbedder()
    except Exception:                                   # missing package or model download failure
        return None


def pgvector_ranker(store, corpus: Corpus, embedder) -> Callable[[str], List[str]]:
    """Index the corpus in PostgreSQL (re-indexing only when the corpus or model changed) and
    return a function that ranks passage ids by cosine distance to a query."""
    indexed = store.indexed_corpus()
    if not indexed or indexed["corpus_hash"] != corpus.hash or indexed["model"] != embedder.model \
            or indexed["n"] != len(corpus.passages):
        vectors = embedder([p.text for p in corpus.passages])
        store.replace_chunks(corpus.hash, embedder.model, [
            {"id": p.id, "document_id": p.document_id, "text": p.text, "meta": p.meta.to_dict(), "embedding": v}
            for p, v in zip(corpus.passages, vectors)])

    def rank(query: str) -> List[str]:
        return store.nearest_chunks(embedder([query])[0], k=len(corpus.passages))
    return rank
