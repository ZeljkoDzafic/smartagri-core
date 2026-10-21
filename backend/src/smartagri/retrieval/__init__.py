"""Corpus loading and hybrid retrieval (BM25 with optional dense ranking, fused by reciprocal rank)."""
from .corpus import Corpus, load_corpus
from .embed import make_embedder, pgvector_ranker
from .search import Retriever, reciprocal_rank_fusion

__all__ = ["Corpus", "load_corpus", "Retriever", "reciprocal_rank_fusion", "make_embedder", "pgvector_ranker", "make_retriever"]


def make_retriever(corpus: Corpus, store=None) -> Retriever:
    """BM25 alone, or fused with a dense ranking when an embedder is configured.

    With PostgreSQL the vectors live in pgvector; otherwise they are held in memory."""
    embedder = make_embedder()
    if embedder is None:
        return Retriever(corpus.passages)
    if store is not None and getattr(store, "backend", "") == "postgresql":
        return Retriever(corpus.passages, dense_rank=pgvector_ranker(store, corpus, embedder))
    return Retriever(corpus.passages, embed=embedder)
