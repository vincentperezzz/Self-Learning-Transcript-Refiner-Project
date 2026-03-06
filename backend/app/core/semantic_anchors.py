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
    # ── GREETING ──
    {
        "pattern": r"(hello|good\s*(morning|afternoon|evening)|kamusta)",
        "mode": AnchorMode.GREETING,
        "label": "greeting",
    },
    # ── INTRODUCTION (agent identifies self/agency) ──
    {
        "pattern": r"(SP|Asti)\s*Madrid\s*(Law\s*Firm|and\s*Associates)",
        "mode": AnchorMode.INTRODUCTION,
        "label": "law_firm_intro",
    },
    {
        "pattern": r"(this\s*is|ako\s*(si|po))\s*\w+.*from",
        "mode": AnchorMode.INTRODUCTION,
        "label": "agent_intro",
    },
    {
        "pattern": r"on\s*behalf\s*of\s*Future\s*Bank",
        "mode": AnchorMode.INTRODUCTION,
        "label": "on_behalf_bank",
    },
    {
        "pattern": r"accredited\s*service\s*provider",
        "mode": AnchorMode.INTRODUCTION,
        "label": "accredited_provider",
    },
    # ── CONSENT TO RECORD ──
    {
        "pattern": r"over\s*the\s*recorded\s*line",
        "mode": AnchorMode.CONSENT_TO_RECORD,
        "label": "recorded_line",
    },
    {
        "pattern": r"(line|call)\s*(will\s*be|is\s*being)\s*recorded",
        "mode": AnchorMode.CONSENT_TO_RECORD,
        "label": "consent_record",
    },
    # ── VERIFICATION ──
    {
        "pattern": r"(verification\s*purposes|verify\s*your\s*(birthday|identity)|dictate\s*your\s*birthdate)",
        "mode": AnchorMode.VERIFICATION,
        "label": "identity_verification",
    },
    {
        "pattern": r"(birthdate|birthday|tama\s*(ho|po)\s*ba)",
        "mode": AnchorMode.VERIFICATION,
        "label": "birthdate_check",
    },
    {
        "pattern": r"thank\s*you\s*for\s*(the\s*)?(verification|confirmation)",
        "mode": AnchorMode.VERIFICATION,
        "label": "verification_confirmed",
    },
    # ── ACCOUNT STATUS ──
    {
        "pattern": r"credit\s*card\s*account",
        "mode": AnchorMode.ACCOUNT_STATUS,
        "label": "credit_card_account",
    },
    {
        "pattern": r"past\s*due",
        "mode": AnchorMode.ACCOUNT_STATUS,
        "label": "past_due",
    },
    {
        "pattern": r"(minimum|total)\s*amount\s*due",
        "mode": AnchorMode.ACCOUNT_STATUS,
        "label": "amount_due",
    },
    {
        "pattern": r"outstanding\s*balance",
        "mode": AnchorMode.ACCOUNT_STATUS,
        "label": "outstanding_balance",
    },
    {
        "pattern": r"subject\s*(for|to)\s*suspension",
        "mode": AnchorMode.ACCOUNT_STATUS,
        "label": "suspension_notice",
    },
    {
        "pattern": r"daily\s*interest",
        "mode": AnchorMode.ACCOUNT_STATUS,
        "label": "daily_interest",
    },
    # ── PROBING: RFD (Reason for Delay/Delinquency) ──
    {
        "pattern": r"(reason|dahilan|bakit).*(delay|hindi.*settle|past\s*due|delinquent|unsettled|napabayaan)",
        "mode": AnchorMode.PROBING_RFD,
        "label": "rfd_probing",
    },
    {
        "pattern": r"(ano|anong).*(nangyari|problem|issue).*(account|settle|delay|payment)",
        "mode": AnchorMode.PROBING_RFD,
        "label": "rfd_inquiry",
    },
    {
        "pattern": r"reason\s*for\s*(the\s*)?(delay|non[- ]?payment|broken\s*promise)",
        "mode": AnchorMode.PROBING_RFD,
        "label": "rfd_english",
    },
    # ── PROBING: SOF/SOI (Source of Funds/Income) ──
    {
        "pattern": r"source\s*of\s*(funds|income)",
        "mode": AnchorMode.PROBING_SOF,
        "label": "source_of_funds",
    },
    {
        "pattern": r"(remittance|allotment|salary|sweldo|sahod|trabaho|employed|negosyo|business)",
        "mode": AnchorMode.PROBING_SOF,
        "label": "income_source",
    },
    {
        "pattern": r"capacity\s*to\s*pay",
        "mode": AnchorMode.PROBING_SOF,
        "label": "capacity_to_pay",
    },
    # ── NEGOTIATION ──
    {
        "pattern": r"(settle|settlement|mag-?settle|ma-?settle|i-?settle)\s*(of|the|your|ng|sa)?\s*(account|balance|amount)?",
        "mode": AnchorMode.NEGOTIATION,
        "label": "settlement_request",
    },
    {
        "pattern": r"(pay\s*in\s*full|full\s*payment|PIF)\s*(today|tomorrow|ngayon|bukas)?",
        "mode": AnchorMode.NEGOTIATION,
        "label": "pif_offer",
    },
    {
        "pattern": r"partial\s*(payment|amount|settle)",
        "mode": AnchorMode.NEGOTIATION,
        "label": "partial_payment",
    },
    {
        "pattern": r"(magawan|gawan)\s*(ng|ito)\s*paraan",
        "mode": AnchorMode.NEGOTIATION,
        "label": "find_solution",
    },
    {
        "pattern": r"(makakapag-?settle|masettle|mababayaran|bayaran)",
        "mode": AnchorMode.NEGOTIATION,
        "label": "can_you_settle",
    },
    {
        "pattern": r"(discount|amnesty|waiver|promo|installment|restructure)",
        "mode": AnchorMode.NEGOTIATION,
        "label": "special_offer",
    },
    # ── BENEFITS ──
    {
        "pattern": r"(good\s*standing|maintain.*account|active.*account|keep.*account.*active)",
        "mode": AnchorMode.BENEFITS,
        "label": "account_benefit",
    },
    {
        "pattern": r"(credit\s*score|avoid.*impact|maiwasan.*impact)",
        "mode": AnchorMode.BENEFITS,
        "label": "credit_benefit",
    },
    # ── CONSEQUENCES ──
    {
        "pattern": r"(suspension|ma-?suspend|tuloy.*suspension|i-?suspend)",
        "mode": AnchorMode.CONSEQUENCES,
        "label": "suspension_warning",
    },
    {
        "pattern": r"(legal\s*proceedings|case\s*filing|higher\s*department|further\s*collection|escalat)",
        "mode": AnchorMode.CONSEQUENCES,
        "label": "escalation_warning",
    },
    {
        "pattern": r"(para\s*maiwasan|to\s*avoid|iwas)",
        "mode": AnchorMode.CONSEQUENCES,
        "label": "avoidance_framing",
    },
    # ── PTP / COMMITMENT TO PAY ──
    {
        "pattern": r"(commitment|promise)\s*to\s*pay",
        "mode": AnchorMode.PTP_COMMITMENT,
        "label": "ptp_commitment",
    },
    {
        "pattern": r"(kailan|when).*((mag-?bayad|settle|payment)|(babayaran|i-?settle))",
        "mode": AnchorMode.PTP_COMMITMENT,
        "label": "ptp_when",
    },
    {
        "pattern": r"(sige|okay|will\s*do|babayaran\s*ko|i.?ll\s*(pay|settle|see\s*what))",
        "mode": AnchorMode.PTP_COMMITMENT,
        "label": "borrower_agreement",
    },
    # ── PAYMENT CHANNEL ──
    {
        "pattern": r"(online\s*banking|mobile\s*banking|gcash|bayad\s*center|over\s*the\s*counter|branch)",
        "mode": AnchorMode.PAYMENT_CHANNEL,
        "label": "payment_channel",
    },
    {
        "pattern": r"account\s*number\s*(ending\s*in)?",
        "mode": AnchorMode.PAYMENT_CHANNEL,
        "label": "account_number",
    },
    {
        "pattern": r"(pakisend|send|email).*receipt",
        "mode": AnchorMode.PAYMENT_CHANNEL,
        "label": "proof_of_payment",
    },
    # ── RECAP ──
    {
        "pattern": r"(recap|summarize|i-?summarize|recap\s*natin|napag-?usapan)",
        "mode": AnchorMode.RECAP,
        "label": "recap_arrangement",
    },
    # ── EMPATHY ──
    {
        "pattern": r"(naiintindihan|naintindihan|understand|i\s*understand)\s*(ko\s*po|po|your\s*situation)?",
        "mode": AnchorMode.EMPATHY,
        "label": "empathy_statement",
    },
    {
        "pattern": r"(mahirap|hirap|sorry\s*to\s*hear|I.?m\s*sorry)",
        "mode": AnchorMode.EMPATHY,
        "label": "empathy_difficulty",
    },
    # ── OBJECTION HANDLING ──
    {
        "pattern": r"(hindi\s*(ko|pa)\s*(kaya|kayang)|can.?t\s*afford|wala.*pera|wala.*pambayad)",
        "mode": AnchorMode.OBJECTION_HANDLING,
        "label": "cant_afford",
    },
    {
        "pattern": r"(i-?hold\s*muna|hold\s*muna|hindi\s*pa\s*ngayon|later|mamaya|bukas)",
        "mode": AnchorMode.OBJECTION_HANDLING,
        "label": "delay_request",
    },
    # ── THIRD PARTY CONTACT ──
    {
        "pattern": r"(alternate|alternative|ibang)\s*(number|contact|phone)",
        "mode": AnchorMode.THIRD_PARTY,
        "label": "alternative_number",
    },
    {
        "pattern": r"(relation|relasyon|kamag-?anak).*borrower",
        "mode": AnchorMode.THIRD_PARTY,
        "label": "relation_inquiry",
    },
    {
        "pattern": r"best\s*time\s*(to\s*call|tawag)",
        "mode": AnchorMode.THIRD_PARTY,
        "label": "best_time_to_call",
    },
    # ── CLOSING ──
    {
        "pattern": r"(thank\s*you|salamat|maraming\s*salamat).*(good\s*day|nice\s*day|po)",
        "mode": AnchorMode.CLOSING,
        "label": "closing_greeting",
    },
    {
        "pattern": r"(walang\s*anuman|ingat\s*po|anything\s*else|assist\s*with)",
        "mode": AnchorMode.CLOSING,
        "label": "closing_courtesy",
    },
    # ── Detail capture (email, contact) → falls under payment channel context ──
    {
        "pattern": r"(email\s*address|contact\s*number|ticket\s*number|reference\s*number)",
        "mode": AnchorMode.PAYMENT_CHANNEL,
        "label": "detail_capture",
    },
    {
        "pattern": r"(pen\s*and\s*paper|take\s*note|take\s*down|jot\s*down)",
        "mode": AnchorMode.PAYMENT_CHANNEL,
        "label": "note_taking",
    },
]


class SemanticAnchorManager:
    """
    Manages semantic anchors and determines the active mode for a transcript.

    Usage:
        manager = SemanticAnchorManager()
        hits = manager.scan("...some transcript text...")
        mode = manager.active_mode  # e.g. AnchorMode.ACCOUNT_STATUS
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
        (N-Gram, Gemini) can use to bias their scoring.

        Weight = (hits for this anchor / total hits).
        """
        total = len(self._hits) or 1
        bias: dict[str, float] = {}
        for hit in self._hits:
            bias[hit.label] = bias.get(hit.label, 0) + (1 / total)
        return bias
