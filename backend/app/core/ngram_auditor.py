"""
NGramAuditor – Trigram frequency analysis for contextual rescoring.

Queries the PostgreSQL `ngram_frequency` table (Table B) with Redis caching
to determine whether a 3-word chain from Whisper output is statistically
plausible versus an alternative correction.

Flow (from the architecture diagram):
  1. Break transcript into overlapping trigrams.
  2. Look up each trigram's frequency in Table B (Redis cache → PG fallback).
  3. If an alternative trigram scores significantly higher AND the differing
     word is phonetically similar (edit distance), flag for swap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.cache import (
    cache_get,
    cache_set,
    ngram_alt_cache_key,
    ngram_alt_suffix_cache_key,
    ngram_cache_key,
)
from app.database import get_db


# ---------------------------------------------------------------------------
# Levenshtein distance for phonetic similarity guard
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _is_phonetically_similar(original: str, suggested: str) -> bool:
    """
    Guard: only allow swap when the differing words are plausibly
    phonetic confusions (not completely unrelated words).

    Rules:
      - Short words (len <= 2): block all swaps
      - Length ratio (shorter/longer) must be >= 0.6
      - Words len 3-4: edit distance <= 1
      - Longer words: edit distance <= ceil(max_len * 0.3)
    """
    a, b = original.lower(), suggested.lower()
    if a == b:
        return True
    min_len = min(len(a), len(b))
    max_len = max(len(a), len(b))
    if max_len <= 2:
        return False  # don't swap tiny words like "ni"→"of", "to"→"me"
    # Block when words differ too much in length (different word entirely)
    if min_len / max_len < 0.6:
        return False
    dist = _levenshtein(a, b)
    if max_len <= 4:
        return dist <= 1
    return dist <= -(-max_len * 30 // 100)  # ceil(max_len * 0.3)


@dataclass
class TrigramCandidate:
    """A potential correction suggested by N-Gram analysis."""
    original_trigram: tuple[str, str, str]
    original_frequency: int
    suggested_trigram: tuple[str, str, str]
    suggested_frequency: int
    confidence: float  # suggested_freq / (suggested_freq + original_freq)


class NGramAuditor:
    """
    Queries the trigram frequency table and suggests corrections when
    an alternative 3-word sequence is overwhelmingly more common.

    Guards against false positives:
      - Only swaps when original trigram has ZERO frequency (unknown)
      - Suggested alternative must have frequency >= MIN_SUGGESTED_FREQ
      - Differing word must pass phonetic similarity check (edit distance)
      - Confidence ratio must exceed SWAP_THRESHOLD (0.97)

    Usage:
        auditor = NGramAuditor()
        auditor.build_trigrams("over the recorded deadline")
        candidates = auditor.audit()
    """

    SWAP_THRESHOLD: float = 0.97
    MIN_SUGGESTED_FREQ: int = 5

    def __init__(self, swap_threshold: Optional[float] = None) -> None:
        if swap_threshold is not None:
            self.SWAP_THRESHOLD = swap_threshold
        self._trigrams: list[tuple[str, str, str]] = []

    # ------------------------------------------------------------------
    # Trigram construction
    # ------------------------------------------------------------------

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Lowercase and split into word tokens."""
        return re.findall(r"[a-záéíóúñ]+(?:'[a-z]+)?", text.lower())

    def build_trigrams(self, text: str) -> list[tuple[str, str, str]]:
        """Break *text* into overlapping 3-word windows."""
        tokens = self.tokenize(text)
        self._trigrams = [
            (tokens[i], tokens[i + 1], tokens[i + 2])
            for i in range(len(tokens) - 2)
        ]
        return list(self._trigrams)

    # ------------------------------------------------------------------
    # DB queries
    # ------------------------------------------------------------------

    @staticmethod
    def lookup_frequency(w1: str, w2: str, w3: str) -> int:
        """Return the stored frequency for a specific trigram, or 0."""
        key = ngram_cache_key(w1.lower(), w2.lower(), w3.lower())
        cached = cache_get(key)
        if cached is not None:
            return cached

        with get_db() as conn:
            cur = conn.execute(
                "SELECT frequency FROM ngram_frequency "
                "WHERE word1 = %s AND word2 = %s AND word3 = %s",
                (w1.lower(), w2.lower(), w3.lower()),
            )
            row = cur.fetchone()
        freq = row["frequency"] if row else 0
        cache_set(key, freq)
        return freq

    @staticmethod
    def find_alternatives(w1: str, w2: str) -> list[tuple[str, int]]:
        """
        Given the first two words of a trigram, find all known completions
        ordered by frequency descending.
        """
        key = ngram_alt_cache_key(w1.lower(), w2.lower())
        cached = cache_get(key)
        if cached is not None:
            return [tuple(x) for x in cached]

        with get_db() as conn:
            cur = conn.execute(
                "SELECT word3, frequency FROM ngram_frequency "
                "WHERE word1 = %s AND word2 = %s "
                "ORDER BY frequency DESC",
                (w1.lower(), w2.lower()),
            )
            rows = cur.fetchall()
        result = [(r["word3"], r["frequency"]) for r in rows]
        cache_set(key, result)
        return result

    @staticmethod
    def find_alternatives_by_suffix(w2: str, w3: str) -> list[tuple[str, int]]:
        """
        Given the last two words of a trigram, find all known prefixes
        ordered by frequency descending.
        """
        key = ngram_alt_suffix_cache_key(w2.lower(), w3.lower())
        cached = cache_get(key)
        if cached is not None:
            return [tuple(x) for x in cached]

        with get_db() as conn:
            cur = conn.execute(
                "SELECT word1, frequency FROM ngram_frequency "
                "WHERE word2 = %s AND word3 = %s "
                "ORDER BY frequency DESC",
                (w2.lower(), w3.lower()),
            )
            rows = cur.fetchall()
        result = [(r["word1"], r["frequency"]) for r in rows]
        cache_set(key, result)
        return result

    # ------------------------------------------------------------------
    # Audit logic
    # ------------------------------------------------------------------

    def audit(self) -> list[TrigramCandidate]:
        """
        For each trigram from the last `build_trigrams` call, check if a
        higher-frequency alternative exists.

        Guards:
          1. Original trigram must have frequency == 0 (unknown to the system).
          2. Alternative must have frequency >= MIN_SUGGESTED_FREQ.
          3. The differing word must be phonetically similar (edit distance).
          4. Confidence must exceed SWAP_THRESHOLD.
        """
        candidates: list[TrigramCandidate] = []

        for tri in self._trigrams:
            w1, w2, w3 = tri
            orig_freq = self.lookup_frequency(w1, w2, w3)

            # Guard 1: If the original trigram has any frequency at all,
            # it's a known-valid sequence – skip it entirely.
            if orig_freq > 0:
                continue

            # Strategy 1: same prefix (w1, w2), different w3
            for alt_w3, alt_freq in self.find_alternatives(w1, w2):
                if alt_w3 == w3:
                    continue
                # Guard 2: alternative must be well-attested
                if alt_freq < self.MIN_SUGGESTED_FREQ:
                    continue
                # Guard 3: phonetic similarity check
                if not _is_phonetically_similar(w3, alt_w3):
                    continue
                total = alt_freq + orig_freq
                conf = alt_freq / total
                if conf >= self.SWAP_THRESHOLD:
                    candidates.append(
                        TrigramCandidate(
                            original_trigram=tri,
                            original_frequency=orig_freq,
                            suggested_trigram=(w1, w2, alt_w3),
                            suggested_frequency=alt_freq,
                            confidence=conf,
                        )
                    )

            # Strategy 2: same suffix (w2, w3), different w1
            for alt_w1, alt_freq in self.find_alternatives_by_suffix(w2, w3):
                if alt_w1 == w1:
                    continue
                # Guard 2: alternative must be well-attested
                if alt_freq < self.MIN_SUGGESTED_FREQ:
                    continue
                # Guard 3: phonetic similarity check
                if not _is_phonetically_similar(w1, alt_w1):
                    continue
                total = alt_freq + orig_freq
                conf = alt_freq / total
                if conf >= self.SWAP_THRESHOLD:
                    candidates.append(
                        TrigramCandidate(
                            original_trigram=tri,
                            original_frequency=orig_freq,
                            suggested_trigram=(alt_w1, w2, w3),
                            suggested_frequency=alt_freq,
                            confidence=conf,
                        )
                    )

        return candidates

    # ------------------------------------------------------------------
    # Ingestion (learning)
    # ------------------------------------------------------------------

    @staticmethod
    def ingest_text(text: str) -> int:
        """
        Extract trigrams from *text* and upsert them into the frequency table.
        Returns the number of trigrams processed.
        """
        tokens = NGramAuditor.tokenize(text)
        trigrams = [
            (tokens[i], tokens[i + 1], tokens[i + 2])
            for i in range(len(tokens) - 2)
        ]
        with get_db() as conn:
            for w1, w2, w3 in trigrams:
                conn.execute(
                    """
                    INSERT INTO ngram_frequency (word1, word2, word3, frequency)
                    VALUES (%s, %s, %s, 1)
                    ON CONFLICT(word1, word2, word3)
                    DO UPDATE SET frequency = ngram_frequency.frequency + 1
                    """,
                    (w1, w2, w3),
                )
        return len(trigrams)

    @staticmethod
    def bulk_ingest(texts: list[str]) -> int:
        """Ingest multiple texts and return total trigrams processed."""
        total = 0
        for t in texts:
            total += NGramAuditor.ingest_text(t)
        return total
