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


def _build_lexicon_pattern(wrong_phrase: str) -> re.Pattern:
    """Build a regex pattern for lexicon matching.

    Uses word boundaries (\b) to avoid substring matches, but intelligently
    handles punctuation at the start and end of phrases:
    - Leading \b only if phrase starts with a word character
    - Trailing \b only if phrase ends with a word character

    This fixes the bug where rules like "minimum amount, you." (ending with
    punctuation) would fail to match because \b expects a word boundary after
    a non-word character.
    """
    # Check first and last characters for word-boundary eligibility
    leading_boundary = r'\b' if wrong_phrase and (wrong_phrase[0].isalnum() or wrong_phrase[0] == '_') else ''
    trailing_boundary = r'\b' if wrong_phrase and (wrong_phrase[-1].isalnum() or wrong_phrase[-1] == '_') else ''

    return re.compile(
        leading_boundary + re.escape(wrong_phrase) + trailing_boundary,
        re.IGNORECASE
    )


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
        """Check text against lexicon rules (for reporting, not applying).
        Uses the same short-word guard as apply() for consistency."""
        rules = self._load_rules(anchor_mode)
        matches: list[LexiconMatch] = []

        for rule in rules:
            wrong = rule["wrong_phrase"]
            rule_anchor = rule["anchor_mode"]

            # Short-word guard: same as apply()
            words = wrong.split()
            if len(words) == 1 and len(wrong) <= 3:
                if rule_anchor is None:
                    continue
                if anchor_mode is None or anchor_mode.value != rule_anchor:
                    continue

            pattern = _build_lexicon_pattern(wrong)
            for m in pattern.finditer(text):
                matches.append(
                    LexiconMatch(
                        wrong_phrase=wrong,
                        correct_phrase=rule["correct_phrase"],
                        anchor_mode=rule_anchor,
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
        Rules are tried longest-first to give specific phrases priority.

        Short-word guard (Fix 3): Single-word rules with ≤3 characters are
        skipped if they have no anchor_mode (universal scope), as they are
        too risky to apply globally. Short rules scoped to an anchor_mode
        are applied only when the segment's anchor_mode matches."""
        rules = self._load_rules(anchor_mode)
        corrected = text
        all_matches: list[LexiconMatch] = []

        for rule in rules:
            wrong = rule["wrong_phrase"]
            rule_anchor = rule["anchor_mode"]

            # Short-word guard: single-word rules ≤3 chars without anchor_mode
            # are too dangerous — skip them to prevent "you" → "po" disasters
            words = wrong.split()
            if len(words) == 1 and len(wrong) <= 3:
                if rule_anchor is None:
                    # No anchor_mode = universal scope — too risky for short words
                    continue
                # Has anchor_mode — only apply if segment matches
                if anchor_mode is None or anchor_mode.value != rule_anchor:
                    continue

            pattern = _build_lexicon_pattern(wrong)
            m = pattern.search(corrected)
            if m:
                corrected = corrected[:m.start()] + rule["correct_phrase"] + corrected[m.end():]
                all_matches.append(
                    LexiconMatch(
                        wrong_phrase=wrong,
                        correct_phrase=rule["correct_phrase"],
                        anchor_mode=rule_anchor,
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
