from __future__ import annotations

import math
import re
from collections import Counter

from devagent.context.indexer import CodeChunk, CodeIndex
from devagent.tools.ai import AIClient

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Retriever:
    def __init__(self, index: CodeIndex):
        self.index = index
        self.ai = AIClient.from_env()

    def search(self, query: str, limit: int = 5) -> list[CodeChunk]:
        query_embedding = self.ai.embed([query])
        if query_embedding and any(record.embedding for record in self.index.records):
            return self._vector_search(query_embedding[0], limit)
        return self._keyword_search(query, limit)

    def _vector_search(self, query_embedding: list[float], limit: int) -> list[CodeChunk]:
        scored = []
        for record in self.index.records:
            if not record.embedding:
                continue
            scored.append((cosine_similarity(query_embedding, record.embedding), record))
        return [record for _, record in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]

    def _keyword_search(self, query: str, limit: int) -> list[CodeChunk]:
        query_tokens = tokenize(query)
        scored = []
        for record in self.index.records:
            text_tokens = tokenize(f"{record.path} {record.text}")
            score = sum(text_tokens[token] * weight for token, weight in query_tokens.items())
            if score:
                scored.append((score, record))
        return [record for _, record in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]


def tokenize(text: str) -> Counter[str]:
    tokens: Counter[str] = Counter()
    for raw in TOKEN_RE.findall(text):
        for token in expand_token(raw):
            tokens[token] += 1
    return tokens


def expand_token(raw: str) -> set[str]:
    lowered = raw.lower()
    pieces = {lowered}
    pieces.update(part for part in lowered.split("_") if part)
    for piece in list(pieces):
        if piece.endswith("tion") and len(piece) > 5:
            pieces.add(f"{piece[:-3]}e")
        if piece.endswith("ing") and len(piece) > 5:
            pieces.add(piece[:-3])
        if piece.endswith("ed") and len(piece) > 4:
            pieces.add(piece[:-2])
    return pieces


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)
