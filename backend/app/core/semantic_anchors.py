"""
SemanticAnchorManager – Context-aware "Mode" switching.

Patterns are loaded from the database (semantic_anchors table) and cached
in Redis. Two classification passes:

  Pass 1 (L2 hint): Quick regex scan on raw text for N-gram scoring bias.
  Pass 2 (final):   Full classification on corrected text with:
     - DB-backed regex vote counting (weighted)
     - Conversation position zones (opening/body/closing)
     - Look-back window (previous segment context)
     - Question detection heuristic (Filipino + English)
     - Gemini escalation for ambiguous ties (Phase 3)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.models.schemas import AnchorMode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Anchor:
    """A single semantic anchor definition."""
    pattern: re.Pattern[str]
    mode: AnchorMode
    label: str
    weight: int = 1


@dataclass
class AnchorHit:
    """Result of an anchor match against a text span."""
    mode: AnchorMode
    label: str
    matched_text: str
    span: tuple[int, int]


# ---------------------------------------------------------------------------
# Question detection heuristic patterns
# ---------------------------------------------------------------------------

_QUESTION_RE = re.compile(
    r"(\?|"  # explicit question mark
    r"\bano\s+(ba|ho|po)\b|"  # "ano ba/ho/po" (what?)
    r"\bano\s+yan\b|"  # "ano yan" (what's that?)
    r"\bba\s*\?|"  # "ba?" particle
    r"\bbakit\b|"  # why
    r"\bgaano\b|"  # how much/many
    r"\bmagkano\b|"  # how much (price)
    r"\bkailan\b|"  # when
    r"\bpaano\b|"  # how
    r"\bsaan\b|"  # where
    r"\bsino\b|"  # who
    r"\balin\b"  # which
    r")",
    re.IGNORECASE,
)

# Modes associated with "inquiry" when question is detected
_INQUIRY_BOOST_MODES = {
    AnchorMode.PROBING_RFD,
    AnchorMode.PROBING_SOF,
    AnchorMode.VERIFICATION,
}


# ---------------------------------------------------------------------------
# DB loading helper
# ---------------------------------------------------------------------------

def _load_anchors_from_db() -> list[Anchor]:
    """Load active anchor patterns from the database, with Redis caching."""
    from app.cache import cache_get, cache_set

    cache_key = "anchors:active"
    cached = cache_get(cache_key)
    if cached is not None:
        anchors = []
        for row in cached:
            try:
                mode = AnchorMode(row["mode"])
                anchors.append(Anchor(
                    pattern=re.compile(row["pattern"], re.IGNORECASE),
                    mode=mode,
                    label=row["label"],
                    weight=row.get("weight", 1),
                ))
            except (ValueError, re.error) as e:
                logger.warning("Skipping bad anchor %s: %s", row.get("label"), e)
        return anchors

    try:
        from app.database import get_db
        with get_db() as conn:
            cur = conn.execute(
                "SELECT mode, label, pattern, weight FROM semantic_anchors "
                "WHERE is_active = TRUE ORDER BY mode, label"
            )
            rows = [dict(r) for r in cur.fetchall()]

        # Cache the raw rows (not compiled patterns)
        cache_set(cache_key, rows, ttl=300)

        anchors = []
        for row in rows:
            try:
                mode = AnchorMode(row["mode"])
                anchors.append(Anchor(
                    pattern=re.compile(row["pattern"], re.IGNORECASE),
                    mode=mode,
                    label=row["label"],
                    weight=row.get("weight", 1),
                ))
            except (ValueError, re.error) as e:
                logger.warning("Skipping bad anchor %s: %s", row.get("label"), e)
        return anchors
    except Exception as e:
        logger.error("Failed to load anchors from DB: %s", e)
        return []


# ---------------------------------------------------------------------------
# Gemini escalation for tied segments (Phase 3)
# ---------------------------------------------------------------------------

def _gemini_classify_segment(
    segment_text: str,
    previous_mode: Optional[AnchorMode],
    tied_modes: list[AnchorMode],
) -> Optional[AnchorMode]:
    """
    Ask Gemini to break a tie between anchor modes.
    Returns the chosen mode, or None if Gemini is unavailable/fails.
    """
    from app.config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return None

    import httpx

    mode_options = ", ".join(m.value for m in tied_modes)
    context_hint = f"The previous segment was classified as: {previous_mode.value}" if previous_mode else "This is the first segment."

    prompt = (
        "You are classifying segments of a Filipino/English debt collection call transcript.\n"
        f"Segment text: \"{segment_text}\"\n"
        f"{context_hint}\n"
        f"The classification is tied between these modes: [{mode_options}]\n"
        "Pick the single most appropriate mode from the tied options. "
        "Reply with ONLY the mode value, nothing else."
    )

    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        )
        resp = httpx.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 30, "temperature": 0.1},
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            logger.warning("Gemini anchor classify returned %d", resp.status_code)
            return None

        data = resp.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
            .lower()
        )

        # Match against tied modes
        for mode in tied_modes:
            if mode.value == text:
                logger.info("Gemini broke tie → %s for: %s", mode.value, segment_text[:50])
                return mode

        # Fuzzy match (Gemini might return slightly different format)
        for mode in tied_modes:
            if mode.value in text:
                logger.info("Gemini broke tie (fuzzy) → %s for: %s", mode.value, segment_text[:50])
                return mode

    except Exception as e:
        logger.warning("Gemini anchor classify failed: %s", e)

    return None


class SemanticAnchorManager:
    """
    Manages semantic anchors loaded from the database.

    Two-pass classification:
      - scan_segment(): Quick L2 hint (raw text, no context engine)
      - classify_segment(): Full classification (corrected text + context)

    Usage:
        manager = SemanticAnchorManager()
        mode = manager.scan_segment(seg.text, ctx_before, ctx_after)  # L2 hint
        mode = manager.classify_segment(text, idx, total, prev_modes)  # Final
    """

    def __init__(self, custom_anchors: Optional[list[dict]] = None) -> None:
        if custom_anchors is not None:
            self._anchors: list[Anchor] = [
                Anchor(
                    pattern=re.compile(a["pattern"], re.IGNORECASE),
                    mode=a["mode"],
                    label=a["label"],
                    weight=a.get("weight", 1),
                )
                for a in custom_anchors
            ]
        else:
            self._anchors = _load_anchors_from_db()
        self._hits: list[AnchorHit] = []
        self._mode_votes: dict[AnchorMode, int] = {}
        self._active_mode: AnchorMode = AnchorMode.GENERAL

    def reload(self) -> None:
        """Reload anchor patterns from the database (cache-busted)."""
        from app.cache import cache_delete_pattern
        cache_delete_pattern("anchors:")
        self._anchors = _load_anchors_from_db()

    # ------------------------------------------------------------------
    # Pass 1: Quick L2 hint (used during correction, before full context)
    # ------------------------------------------------------------------

    def scan(self, text: str) -> list[AnchorHit]:
        """Scan text against all registered anchors. Updates active mode."""
        self._hits.clear()
        self._mode_votes.clear()

        for anchor in self._anchors:
            for match in anchor.pattern.finditer(text):
                hit = AnchorHit(
                    mode=anchor.mode,
                    label=anchor.label,
                    matched_text=match.group(),
                    span=match.span(),
                )
                self._hits.append(hit)
                self._mode_votes[anchor.mode] = (
                    self._mode_votes.get(anchor.mode, 0) + anchor.weight
                )

        if self._mode_votes:
            self._active_mode = max(
                self._mode_votes,
                key=lambda m: self._mode_votes[m],
            )
        else:
            self._active_mode = AnchorMode.GENERAL

        return list(self._hits)

    def scan_segment(
        self,
        segment_text: str,
        context_before: str = "",
        context_after: str = "",
    ) -> AnchorMode:
        """
        Quick scan for L2 hint during correction pipeline.
        Uses regex votes only (no context engine).
        """
        combined = f"{context_before} {segment_text} {context_after}"
        votes: dict[AnchorMode, int] = {}
        for anchor in self._anchors:
            for _ in anchor.pattern.finditer(combined):
                votes[anchor.mode] = votes.get(anchor.mode, 0) + anchor.weight
        if votes:
            return max(votes, key=lambda m: votes[m])
        return AnchorMode.GENERAL

    # ------------------------------------------------------------------
    # Pass 2: Full classification (corrected text + context engine)
    # ------------------------------------------------------------------

    def classify_segment(
        self,
        segment_text: str,
        segment_index: int,
        total_segments: int,
        previous_modes: list[AnchorMode],
    ) -> AnchorMode:
        """
        Full context-aware classification for a corrected segment.

        Steps:
          1. Regex pattern vote counting (weighted)
          2. Conversation position zone bias (CRITICAL for closing)
          3. Look-back window adjustment
          4. Question detection heuristic
          5. Return winner (or GENERAL if no votes)
        """
        # Step 1: Weighted regex votes
        votes: dict[AnchorMode, float] = {}
        for anchor in self._anchors:
            for _ in anchor.pattern.finditer(segment_text):
                votes[anchor.mode] = votes.get(anchor.mode, 0) + anchor.weight

        if not votes:
            return AnchorMode.GENERAL

        # Step 2: Conversation position zone bias
        # Calculate position ratio
        position_ratio = segment_index / total_segments if total_segments > 0 else 0.5

        # Opening zone: first 10%
        if position_ratio < 0.10:
            for m in (AnchorMode.GREETING, AnchorMode.INTRODUCTION,
                      AnchorMode.CONSENT_TO_RECORD, AnchorMode.VERIFICATION):
                if m in votes:
                    votes[m] += 2
            # SUPPRESS closing in opening zone (a "thank you" early is NOT closing)
            if AnchorMode.CLOSING in votes:
                votes[AnchorMode.CLOSING] = 0

        # Middle zone: 10% - 80%
        elif position_ratio < 0.80:
            # SUPPRESS closing in middle zone - "salamat" mid-conversation is gratitude, not closing
            # Only apply if CLOSING is the ONLY mode detected (standalone thanks)
            if AnchorMode.CLOSING in votes:
                # Check if other modes are also present
                other_votes = {m: v for m, v in votes.items() if m != AnchorMode.CLOSING and v > 0}
                if other_votes:
                    # Other modes present — CLOSING competes, reduce its weight
                    votes[AnchorMode.CLOSING] = max(0, votes[AnchorMode.CLOSING] - 2)
                else:
                    # CLOSING is the only mode — suppress it entirely in mid-conversation
                    votes[AnchorMode.CLOSING] = 0

        # Closing zone: last 20% (expanded from 12% for better detection)
        elif position_ratio >= 0.80:
            if AnchorMode.CLOSING in votes:
                votes[AnchorMode.CLOSING] += 3  # Strong boost in closing zone
            # Also check for classic closing phrases that should always trigger closing here
            closing_phrases = re.compile(
                r"(good\s*(bye|day)|have\s*a\s*(good|nice|great)\s*day|take\s*care|ingat\s*po|"
                r"for\s*any\s*(concern|question).*reach\s*out|walang\s*anuman)",
                re.IGNORECASE
            )
            if closing_phrases.search(segment_text):
                votes[AnchorMode.CLOSING] = votes.get(AnchorMode.CLOSING, 0) + 3

        # Step 3: Look-back window (reduce repeated mode and contextual bias)
        if previous_modes:
            last_2 = previous_modes[-2:] if len(previous_modes) >= 2 else previous_modes
            # If the same mode dominated recent segments, reduce its weight
            # (conversation typically moves forward, not stays in same mode)
            for m in set(last_2):
                # Only reduce modes that appear in votes AND dominated recently
                if m in votes and last_2.count(m) >= 2:
                    votes[m] = max(0, votes[m] - 1)

        # Step 4: Question detection heuristic
        if _QUESTION_RE.search(segment_text):
            # Questions are more likely inquiry/probing, less likely PTP
            for m in _INQUIRY_BOOST_MODES:
                if m in votes:
                    votes[m] += 1
            # Reduce PTP for question-style segments
            if AnchorMode.PTP_COMMITMENT in votes:
                votes[AnchorMode.PTP_COMMITMENT] = max(
                    0, votes[AnchorMode.PTP_COMMITMENT] - 1
                )

        # Step 5: Detect ties and escalate to Gemini if needed
        sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_votes) >= 2 and sorted_votes[0][1] == sorted_votes[1][1]:
            # Tie detected — try Gemini escalation
            tied_modes = [m for m, v in sorted_votes if v == sorted_votes[0][1]]
            gemini_result = _gemini_classify_segment(
                segment_text, previous_modes[-1] if previous_modes else None, tied_modes
            )
            if gemini_result is not None:
                return gemini_result

        # Pick winner
        if votes:
            winner = max(votes, key=lambda m: votes[m])
            if votes[winner] > 0:
                return winner
        return AnchorMode.GENERAL

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active_mode(self) -> AnchorMode:
        return self._active_mode

    @property
    def hits(self) -> list[AnchorHit]:
        return list(self._hits)

    def reset(self) -> None:
        """Clear all scan state."""
        self._hits.clear()
        self._mode_votes.clear()
        self._active_mode = AnchorMode.GENERAL

    def add_anchor(self, pattern: str, mode: AnchorMode, label: str) -> None:
        """Register a new anchor at runtime."""
        self._anchors.append(
            Anchor(
                pattern=re.compile(pattern, re.IGNORECASE),
                mode=mode,
                label=label,
            )
        )

    def get_context_bias(self) -> dict[str, float]:
        """
        Return a dict of label -> weight that downstream components
        (N-Gram, Gemini) can use to bias their scoring.
        """
        total = len(self._hits) or 1
        bias: dict[str, float] = {}
        for hit in self._hits:
            bias[hit.label] = bias.get(hit.label, 0) + (1 / total)
        return bias
