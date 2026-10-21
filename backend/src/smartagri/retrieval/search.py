from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Callable, Dict, List, Optional, Sequence

from ..core.types import AdviceType, Passage

# Terms added to the query per advice type, so that a short question still reaches the right passages.
EXPANSION = {
    AdviceType.IRRIGATION_TIMING: "navodnjavanje voda zemljiste padavine evapotranspiracija termin",
    AdviceType.IRRIGATION_AMOUNT: "navodnjavanje norma bruto neto efikasnost kolicina vode zemljiste",
    AdviceType.FERTILIZATION_PLAN: "prihrana azot doza djubrivo analiza zemljista prinos",
    AdviceType.FERTILIZATION_TIMING: "prihrana azot faza listova termin kisa",
    AdviceType.FIELD_OPS_WINDOW: "prskanje setva obrada vetar padavine temperatura mraz zemljiste",
    AdviceType.SCOUTING: "indeks vegetacije NDVI snimak obilazak razlike parcela uzrok",
}
STOP = set("i u na je se da za od do sa su ili a ali kao koji koja koje sto po iz ne o the of and to in is for".split())
STEM_LEN = 6
K1, B = 1.5, 0.75


def fold(text: str) -> str:
    text = text.lower().replace("đ", "dj")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> List[str]:
    """Lowercase, strip diacritics, drop stop words, truncate to a crude stem (Serbian is heavily inflected)."""
    return [t[:STEM_LEN] for t in re.findall(r"[a-z0-9]+", fold(text)) if t not in STOP and len(t) > 1]


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> List[str]:
    scores: Dict[str, float] = {}
    for ranking in rankings:
        for rank, pid in enumerate(ranking):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank + 1)
    return [pid for pid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


class Retriever:
    """BM25 over passages. If an embedding function is supplied, its ranking is fused with BM25.

    embed: callable mapping a list of texts to a list of equal-length vectors. Left as None by
    default so the system has no model download or network dependency. The dense side ranks on the
    question alone; the advice-type expansion terms are for the lexical side.
    """

    def __init__(self, passages: List[Passage], embed: Optional[Callable[[List[str]], List[List[float]]]] = None,
                 dense_rank: Optional[Callable[[str], List[str]]] = None):
        self.passages = passages
        self.docs = [tokenize(p.text) for p in passages]
        self.avg_len = sum(len(d) for d in self.docs) / float(max(1, len(self.docs)))
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]
        # dense_rank: an external index (pgvector) that returns passage ids ranked for a query.
        self.dense_rank = dense_rank
        self.embed = None if dense_rank else embed
        self.vectors = self.embed([p.text for p in passages]) if self.embed else None

    @property
    def mode(self) -> str:
        if self.dense_rank:
            return "hybrid (BM25 + pgvector)"
        return "hybrid (BM25 + in-memory vectors)" if self.embed else "lexical (BM25)"

    def _bm25(self, query: str) -> List[str]:
        q = tokenize(query)
        scored = []
        for i, tf in enumerate(self.tf):
            score = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    score += self.idf.get(t, 0.0) * f * (K1 + 1) / (f + K1 * (1 - B + B * len(self.docs[i]) / self.avg_len))
            if score > 0:
                scored.append((score, self.passages[i].id))
        return [pid for _, pid in sorted(scored, key=lambda s: (-s[0], s[1]))]

    def _dense(self, query: str) -> List[str]:
        qv = self.embed([query])[0]
        def cos(a, b):
            na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
            return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0
        scored = sorted(((cos(qv, v), self.passages[i].id) for i, v in enumerate(self.vectors)), key=lambda s: (-s[0], s[1]))
        return [pid for _, pid in scored]

    def search(self, question: str, advice_type: AdviceType, k: int = 20) -> List[Passage]:
        query = question + " " + EXPANSION.get(advice_type, "")
        rankings = [self._bm25(query)]
        if self.dense_rank:
            rankings.append(self.dense_rank(question))
        elif self.embed:
            rankings.append(self._dense(question))
        order = reciprocal_rank_fusion(rankings) if len(rankings) > 1 else rankings[0]
        by_id = {p.id: p for p in self.passages}
        return [by_id[pid] for pid in order[:k]]
