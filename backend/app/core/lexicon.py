"""
Lexicon – Layer 1 of the Correction Hierarchy.

Performs fast, deterministic lookups against the Lexicon table
for known Whisper errors and their corrections.
Both permanent and probationary rules are applied.
Uses Redis cache for repeated lookups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.cache import cache_get, cache_set, cache_delete, lexicon_cache_key
from app.database import get_db
from app.models.schemas import AnchorMode


@dataclass
class LexiconMatch:
    wrong_phrase: str
    correct_phrase: str
    anchor_mode: Optional[str]
    span: tuple[int, int]


class LexiconChecker:
    """
    Checks transcript text against all lexicon rules (permanent + probationary).
    Optionally filters by anchor_mode for context-aware corrections.
    """

    def check(
        self,
        text: str,
        anchor_mode: Optional[AnchorMode] = None,
    ) -> list[LexiconMatch]:
        rules = self._load_rules(anchor_mode)
        matches: list[LexiconMatch] = []

        for rule in rules:
            pattern = re.compile(
                r'\b' + re.escape(rule["wrong_phrase"]) + r'\b', re.IGNORECASE
            )
            for m in pattern.finditer(text):
                matches.append(
                    LexiconMatch(
                        wrong_phrase=rule["wrong_phrase"],
                        correct_phrase=rule["correct_phrase"],
                        anchor_mode=rule["anchor_mode"],
                        span=m.span(),
                    )
                )

        return matches

    def apply(
        self,
        text: str,
        anchor_mode: Optional[AnchorMode] = None,
    ) -> tuple[str, list[LexiconMatch]]:
        """Apply lexicon rules sequentially — each rule runs against the
        result of the previous, so chained corrections work correctly.
        Rules are tried longest-first to give specific phrases priority."""
        rules = self._load_rules(anchor_mode)
        corrected = text
        all_matches: list[LexiconMatch] = []

        for rule in rules:
            pattern = re.compile(
                r'\b' + re.escape(rule["wrong_phrase"]) + r'\b', re.IGNORECASE
            )
            m = pattern.search(corrected)
            if m:
                corrected = corrected[:m.start()] + rule["correct_phrase"] + corrected[m.end():]
                all_matches.append(
                    LexiconMatch(
                        wrong_phrase=rule["wrong_phrase"],
                        correct_phrase=rule["correct_phrase"],
                        anchor_mode=rule["anchor_mode"],
                        span=m.span(),
                    )
                )

        return corrected, all_matches

    # ------------------------------------------------------------------
    # DB access (with Redis cache)
    # ------------------------------------------------------------------

    @staticmethod
    def _load_rules(anchor_mode: Optional[AnchorMode] = None) -> list[dict]:
        cache_key = lexicon_cache_key(anchor_mode.value if anchor_mode else None)
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        with get_db() as conn:
            if anchor_mode:
                cur = conn.execute(
                    "SELECT wrong_phrase, correct_phrase, anchor_mode "
                    "FROM lexicon "
                    "WHERE (anchor_mode IS NULL OR anchor_mode = %s) "
                    "ORDER BY length(wrong_phrase) DESC",
                    (anchor_mode.value,),
                )
            else:
                cur = conn.execute(
                    "SELECT wrong_phrase, correct_phrase, anchor_mode "
                    "FROM lexicon "
                    "ORDER BY length(wrong_phrase) DESC",
                )
            rows = cur.fetchall()
        result = [dict(r) for r in rows]
        cache_set(cache_key, result)
        return result

    @staticmethod
    def add_rule(
        wrong_phrase: str,
        correct_phrase: str,
        context_hint: Optional[str] = None,
        anchor_mode: Optional[AnchorMode] = None,
    ) -> None:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO lexicon "
                "(wrong_phrase, correct_phrase, context_hint, anchor_mode) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (wrong_phrase, correct_phrase) DO NOTHING",
                (
                    wrong_phrase,
                    correct_phrase,
                    context_hint,
                    anchor_mode.value if anchor_mode else None,
                ),
            )
        # Invalidate lexicon caches so new rule is picked up
        cache_delete(lexicon_cache_key(anchor_mode.value if anchor_mode else None))
        cache_delete(lexicon_cache_key(None))
