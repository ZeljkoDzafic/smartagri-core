"""Spec 003 US2: folding, tokenisation, BM25, RRF (T011), in-memory dense path (T012), FastEmbedder smoke (T013)."""
import os

import pytest

from smartagri.core.types import AdviceType, Passage
from smartagri.retrieval import load_corpus, make_retriever
from smartagri.retrieval.search import EXPANSION, Retriever, fold, reciprocal_rank_fusion, tokenize


def test_fold_strips_serbian_diacritics_and_spells_dj():
    assert fold("Đubrivo ČAĆ šŽ đ") == "djubrivo cac sz dj"
    assert fold("navodnjavanje kukuruza") == fold("navodnjavanje kukuruza")


def test_tokenize_drops_stop_words_short_tokens_and_truncates_stems():
    assert tokenize("Da li je navodnjavanje u fazi svilanja potrebno?") == ["li", "navodn", "fazi", "svilan", "potreb"]
    assert tokenize("a i u x") == []
    # inflected forms with and without diacritics collapse to the same stem
    assert tokenize("đubrenje")[0] == tokenize("djubrenjem")[0] == "djubre"
    assert tokenize("Prihrana kukuruza") == tokenize("prihranu kukuruzu")


def _toy():
    texts = {
        "a": "navodnjavanje kukuruza u fazi svilanja",
        "b": "navodnjavanje navodnjavanje navodnjavanje kukuruza",
        "c": "prihrana azotom u fazi listova",
        "d": "navodnjavanje",
    }
    return [Passage(pid, text=t) for pid, t in texts.items()]


def test_bm25_orders_by_term_weight_and_skips_non_matching_passages():
    r = Retriever(_toy())
    ranked = r._bm25("navodnjavanje svilanje")
    assert ranked[0] == "a"                               # the only passage with the rare term
    assert "c" not in ranked                              # no shared token: not a candidate
    # avg length 3.25 tokens; tf 3 in 4 tokens (b) scores 7.5/4.76 = 1.58 > tf 1 in 1 token (d) 2.5/1.72 = 1.45
    # > tf 1 in 4 tokens (a): term frequency saturates (k1 = 1.5) and long passages are damped (b = 0.75)
    assert r._bm25("navodnjavanje") == ["b", "d", "a"]
    assert r._bm25("nepostojeca rec") == []


def test_bm25_ties_are_broken_by_passage_id():
    r = Retriever([Passage("z", text="setva kukuruza"), Passage("m", text="setva kukuruza")])
    assert r._bm25("setva") == ["m", "z"]


def test_rrf_scores_and_tie_break():
    assert reciprocal_rank_fusion([["a", "b"], ["b", "a"]]) == ["a", "b"]           # equal scores: by id
    assert reciprocal_rank_fusion([["x", "a"], ["a", "y"]]) == ["a", "x", "y"]
    # 1/61 + 1/62 for 'a' beats 1/61 for 'x' alone
    scores = {"a": 1 / 62.0 + 1 / 61.0, "x": 1 / 61.0}
    assert scores["a"] > scores["x"]
    assert reciprocal_rank_fusion([["b", "c"], ["c"]], k=0) == ["c", "b"]            # 1/2 + 1 > 1


def test_search_expands_the_lexical_query_by_advice_type_and_caps_k():
    r = Retriever(_toy())
    assert [p.id for p in r.search("kukuruz", AdviceType.FERTILIZATION_TIMING, k=1)] == ["c"]
    assert len(r.search("", AdviceType.IRRIGATION_TIMING, k=2)) == 2


class FakeEmbedder:
    """Deterministic bag of hashed character trigrams (no model download)."""
    model = "fake-trigram"

    def __init__(self):
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            v = [0.0] * 64
            t = fold(t)
            for i in range(len(t) - 2):
                v[sum(ord(c) * (k + 1) for k, c in enumerate(t[i:i + 3])) % 64] += 1.0
            out.append(v)
        return out


def test_in_memory_dense_path_embeds_once_and_fuses_with_bm25():
    corpus = load_corpus()
    emb = FakeEmbedder()
    r = Retriever(corpus.passages, embed=emb)
    assert r.mode == "hybrid (BM25 + in-memory vectors)" and len(emb.calls) == 1
    target = corpus.passage("note-ndvi-not-a-diagnosis")
    assert r._dense(target.text)[0] == target.id
    question = "Koji deo parcele da obiđem prvo?"
    hits = r.search(question, AdviceType.SCOUTING, k=20)
    assert emb.calls[-1] == [question]                               # dense side sees the question only
    expected = reciprocal_rank_fusion([r._bm25(question + " " + EXPANSION[AdviceType.SCOUTING]), r._dense(question)])[:20]
    assert [p.id for p in hits] == expected
    assert "note-ndvi-scouting-priority" in [p.id for p in hits[:6]]


def test_make_retriever_uses_in_memory_vectors_on_sqlite(monkeypatch):
    import smartagri.retrieval as retrieval
    monkeypatch.setattr(retrieval, "make_embedder", lambda: FakeEmbedder())
    assert make_retriever(load_corpus(), store=None).mode == "hybrid (BM25 + in-memory vectors)"
    monkeypatch.setattr(retrieval, "make_embedder", lambda: None)
    assert make_retriever(load_corpus()).mode == "lexical (BM25)"


def test_fastembedder_smoke():
    """T013: the real model, only where fastembed and its model cache are available (container, CI job)."""
    pytest.importorskip("fastembed")
    if os.environ.get("SMARTAGRI_SKIP_MODEL_TESTS") == "1":
        pytest.skip("model tests disabled")
    from smartagri.retrieval.embed import FastEmbedder
    try:
        emb = FastEmbedder()
    except Exception as exc:                                         # no network and no cached model
        pytest.skip("embedding model not available: %s" % exc.__class__.__name__)
    vecs = emb(["Navodnjavanje kukuruza u fazi svilanja.", "Prihrana azotom.", "navodnjavanje kukuruza svilanje"])
    assert len(vecs) == 3 and all(len(v) == 384 for v in vecs)

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b)) / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))
    assert cos(vecs[0], vecs[2]) > cos(vecs[1], vecs[2])
