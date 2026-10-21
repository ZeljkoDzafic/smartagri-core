"""Grounding check gamma.

Numeric part: every number in an answer must come from a tool or the context.
Support part: every sentence a language model writes must be supported by an applicable passage
or by the fact sheet. The default check is lexical (share of a sentence's content words found in
the best supporting text) and therefore conservative and explainable; an entailment model can be
plugged in through `support_check(..., judge=...)`.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List

from .types import ToolResult

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")


def _numbers_in(obj: Any) -> List[float]:
    out: List[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return [float(m.replace(",", ".")) for m in _NUMBER.findall(obj)]
    if isinstance(obj, dict):
        obj = obj.values()
    if isinstance(obj, Iterable):
        for item in obj:
            out.extend(_numbers_in(item))
    return out


def unsupported_numbers(text: str, tools: List[ToolResult], context_values: Any = None,
                        tolerance: float = 0.05) -> List[float]:
    """Numbers in `text` that match neither a tool input/output nor a context value.

    A non-empty result means the answer states a figure nobody computed: remove it, make the
    claim conditional, or downgrade the act.
    """
    supported: List[float] = _numbers_in(context_values)
    for t in tools:
        supported.extend(_numbers_in(t.inputs))
        supported.extend(_numbers_in(t.output))
    bad = []
    for n in _numbers_in(text):
        if not any(abs(n - s) <= tolerance * max(1.0, abs(s)) for s in supported):
            bad.append(n)
    return bad


def _content(text: str):
    from ..retrieval.search import tokenize
    return set(tokenize(text))


ABBREVIATIONS = ("npr", "tj", "itd", "sl", "br", "str", "god", "tzv", "dr", "prof", "sar", "min", "maks", "cca", "oko")


def split_sentences(text: str) -> List[str]:
    """Split on . ! ? followed by space, but not after common Serbian abbreviations or a decimal point."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out: List[str] = []
    for part in parts:
        if out:
            last_word = re.findall(r"(\w+)\.$", out[-1].lower())
            # also do not split dates and ordinals: "20. 9. 2025." or "u 3. nedelji"
            # a new sentence starts with a capital letter, a digit or a dash, never with a lowercase letter
            if (last_word and last_word[0] in ABBREVIATIONS) or re.search(r"(^|[\s(])\d{1,2}\.$", out[-1]) \
                    or part[:1].islower():
                out[-1] = out[-1] + " " + part
                continue
        if part:
            out.append(part)
    return out


def support_check(sentences: List[str], sources: List[str], threshold: float = 0.5,
                  judge=None) -> List[dict]:
    """For each sentence: the best-supporting source index, the support score and a verdict.

    Lexical score = |content words of the sentence found in the source| / |content words of the sentence|.
    A sentence with fewer than three content words is treated as supported (connectives, short replies).
    judge(sentence, source) -> float in [0, 1] replaces the lexical score when given; a judge that
    returns None for a pair (API error, refusal) leaves the lexical score for that pair.
    """
    out = []
    source_words = [_content(s) for s in sources]
    for sentence in sentences:
        words = _content(sentence)
        if len(words) < 3:
            out.append({"sentence": sentence, "score": 1.0, "source": None, "supported": True})
            continue
        best, best_i = 0.0, None
        for i, src in enumerate(sources):
            score = judge(sentence, src) if judge else None
            if score is None:                 # no judge, or the judge gave no verdict: lexical score
                score = len(words & source_words[i]) / float(len(words))
            if score > best:
                best, best_i = score, i
        out.append({"sentence": sentence, "score": round(best, 3), "source": best_i, "supported": best >= threshold})
    return out
