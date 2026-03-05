"""
SemanticAnchorManager – Context-aware "Mode" switching.

Scans transcript text for regex-based anchor phrases and activates the
appropriate domain mode (e.g., Banking, Collections, Verification).
When a mode is active, downstream components use it to bias corrections.

Flow (from the architecture diagram):
  1. Regex anchors fire on keyword clusters.
  2. The matching mode is set (e.g., "banking").
  3. Mode context is passed to the N-Gram auditor and lexicon checker
     so they can weight domain-specific corrections higher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.models.schemas import AnchorMode


@dataclass(frozen=True)
class Anchor:
    """A single semantic anchor definition."""
    pattern: re.Pattern[str]
    mode: AnchorMode
    label: str  # human-readable tag, e.g. "credit_card_account"


@dataclass
class AnchorHit:
    """Result of an anchor match against a text span."""
    mode: AnchorMode
    label: str
    matched_text: str
    span: tuple[int, int]


# ---------------------------------------------------------------------------
# Default anchor catalogue – extends from reference regex patterns + domain
# ---------------------------------------------------------------------------

_DEFAULT_ANCHORS: list[dict] = [
    # Banking / Account
    {
        "pattern": r"credit\s*card\s*account",
        "mode": AnchorMode.BANKING,
        "label": "credit_card_account",
    },
    {
        "pattern": r"past\s*due",
        "mode": AnchorMode.BANKING,
        "label": "past_due",
    },
    {
        "pattern": r"minimum\s*amount\s*due",
        "mode": AnchorMode.BANKING,
        "label": "minimum_amount_due",
    },
    {
        "pattern": r"total\s*amount\s*due",
        "mode": AnchorMode.BANKING,
        "label": "total_amount_due",
    },
    {
        "pattern": r"subject\s*(for|to)\s*suspension",
        "mode": AnchorMode.BANKING,
        "label": "suspension_notice",
    },
    {
        "pattern": r"(settle|settlement)\s*(of|the|your)?\s*(account|balance|amount)",
        "mode": AnchorMode.BANKING,
        "label": "settlement_request",
    },
    {
        "pattern": r"online\s*banking",
        "mode": AnchorMode.BANKING,
        "label": "online_banking",
    },
    {
        "pattern": r"account\s*number\s*(ending\s*in)?",
        "mode": AnchorMode.BANKING,
        "label": "account_number",
    },
    # Collections / Legal
    {
        "pattern": r"(SP|Asti)\s*Madrid\s*(Law\s*Firm|and\s*Associates)",
        "mode": AnchorMode.COLLECTIONS,
        "label": "law_firm_intro",
    },
    {
        "pattern": r"on\s*behalf\s*of\s*Future\s*Bank",
        "mode": AnchorMode.COLLECTIONS,
        "label": "on_behalf_bank",
    },
    {
        "pattern": r"accredited\s*service\s*provider",
        "mode": AnchorMode.COLLECTIONS,
        "label": "accredited_provider",
    },
    {
        "pattern": r"over\s*the\s*recorded\s*line",
        "mode": AnchorMode.COLLECTIONS,
        "label": "recorded_line",
    },
    {
        "pattern": r"(remittance|source\s*of\s*funds)",
        "mode": AnchorMode.COLLECTIONS,
        "label": "source_of_funds",
    },
    # Verification
    {
        "pattern": r"(verification\s*purposes|verify\s*your\s*birthday|dictate\s*your\s*birthdate)",
        "mode": AnchorMode.VERIFICATION,
        "label": "identity_verification",
    },
    {
        "pattern": r"(birthdate|birthday)",
        "mode": AnchorMode.VERIFICATION,
        "label": "birthdate_check",
    },
    # Note-taking / detail capture (pen and paper context)
    {
        "pattern": r"(pen\s*and\s*paper|take\s*note|take\s*down|jot\s*down)",
        "mode": AnchorMode.COLLECTIONS,
        "label": "note_taking",
    },
    {
        "pattern": r"(email\s*address|contact\s*number|ticket\s*number|reference\s*number)",
        "mode": AnchorMode.COLLECTIONS,
        "label": "detail_capture",
    },
]


class SemanticAnchorManager:
    """
    Manages semantic anchors and determines the active mode for a transcript.

    Usage:
        manager = SemanticAnchorManager()
        hits = manager.scan("...some transcript text...")
        mode = manager.active_mode  # e.g. AnchorMode.BANKING
    """

    def __init__(self, custom_anchors: Optional[list[dict]] = None) -> None:
        raw = custom_anchors if custom_anchors is not None else _DEFAULT_ANCHORS
        self._anchors: list[Anchor] = [
            Anchor(
                pattern=re.compile(a["pattern"], re.IGNORECASE),
                mode=a["mode"],
                label=a["label"],
            )
            for a in raw
        ]
        self._hits: list[AnchorHit] = []
        self._mode_votes: dict[AnchorMode, int] = {}
        self._active_mode: AnchorMode = AnchorMode.GENERAL

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, text: str) -> list[AnchorHit]:
        """
        Scan *text* against all registered anchors.
        Returns list of AnchorHit and updates the active mode.
        """
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
                    self._mode_votes.get(anchor.mode, 0) + 1
                )

        # Mode with highest vote count wins; ties broken by enum order
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
        Scan a single segment (plus optional surrounding context) and return
        the best anchor mode for that segment.  Does NOT alter the manager's
        global state (self._hits / self._active_mode).
        """
        combined = f"{context_before} {segment_text} {context_after}"
        votes: dict[AnchorMode, int] = {}
        for anchor in self._anchors:
            for _ in anchor.pattern.finditer(combined):
                votes[anchor.mode] = votes.get(anchor.mode, 0) + 1
        if votes:
            return max(votes, key=lambda m: votes[m])
        return AnchorMode.GENERAL

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
        (N-Gram, DistilBERT) can use to bias their scoring.

        Weight = (hits for this anchor / total hits).
        """
        total = len(self._hits) or 1
        bias: dict[str, float] = {}
        for hit in self._hits:
            bias[hit.label] = bias.get(hit.label, 0) + (1 / total)
        return bias
