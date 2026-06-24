"""Pydantic schemas for CostCutter Refiner API."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CorrectionSource(str, Enum):
    LEXICON = "lexicon"
    NGRAM_ANCHOR = "ngram_anchor"
    GEMINI = "gemini"


class AnchorMode(str, Enum):
    GREETING = "greeting"
    INTRODUCTION = "introduction"
    CONSENT_TO_RECORD = "consent_to_record"
    VERIFICATION = "verification"
    ACCOUNT_STATUS = "account_status"
    PROBING_RFD = "probing_rfd"
    PROBING_SOF = "probing_sof"
    NEGOTIATION = "negotiation"
    BENEFITS = "benefits"
    CONSEQUENCES = "consequences"
    PTP_COMMITMENT = "ptp_commitment"
    PAYMENT_CHANNEL = "payment_channel"
    CONTACT_INFO = "contact_info"
    RECAP = "recap"
    EMPATHY = "empathy"
    OBJECTION_HANDLING = "objection_handling"
    CLOSING = "closing"
    THIRD_PARTY = "third_party"
    GENERAL = "general"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class WordInfo(BaseModel):
    """Per-word confidence data from Whisper (word_timestamps=True)."""
    word: str
    start: float = Field(..., description="Word start time in seconds")
    end: float = Field(..., description="Word end time in seconds")
    probability: float = Field(..., ge=0.0, le=1.0, description="Whisper confidence for this word")


class TranscriptSegment(BaseModel):
    """A single timestamped segment from Whisper output."""
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Raw transcription text")
    speaker: Optional[str] = Field(None, description="Speaker: agent, client, or mixed")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Segment-level avg confidence")
    words: Optional[list[WordInfo]] = Field(None, description="Per-word timestamps and confidence from Whisper")


class RefinementRequest(BaseModel):
    """Payload sent to the /refine endpoint."""
    segments: list[TranscriptSegment]
    speaker: Optional[str] = Field(None, description="agent or client")


class CorrectionDetail(BaseModel):
    original: str
    corrected: str
    source: CorrectionSource
    confidence_delta: Optional[float] = None


class FlaggedWord(BaseModel):
    """A word with confidence below the threshold, flagged for Layer 3."""
    word: str
    probability: float
    start: float
    end: float


class RefinedSegment(BaseModel):
    start: float
    end: float
    original_text: str
    refined_text: str
    speaker: Optional[str] = Field(None, description="Speaker: agent, client, or mixed")
    corrections: list[CorrectionDetail] = []
    anchor_mode: Optional[AnchorMode] = None
    low_confidence_words: list[FlaggedWord] = Field(
        default_factory=list,
        description="Words below the confidence threshold (candidates for Layer 3 Gemini)",
    )


class RefinementResponse(BaseModel):
    segments: list[RefinedSegment]
    total_corrections: int
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class PlainTextImportRequest(BaseModel):
    """Import plain text transcript with speaker labels.

    Text format example:
        Agent: Good morning, thank you for calling SP Madrid and Associates.
        Client: Hello, yes po.
        Mixed: [Both speaking at once]

    Speaker prefixes:
        - "Agent:" - Agent speaking
        - "Client:" - Client/borrower speaking
        - "Mixed:" - Both speakers (overlapping)

    Each line starting with a speaker prefix becomes a segment.
    Lines without a prefix are appended to the previous segment.
    """
    text: str = Field(..., description="Plain text transcript with Agent:/Client:/Mixed: prefixes")


# ---------------------------------------------------------------------------
# Lexicon / N-Gram models
# ---------------------------------------------------------------------------

class LexiconRule(BaseModel):
    id: Optional[int] = None
    wrong_phrase: str
    correct_phrase: str
    context_hint: Optional[str] = None
    anchor_mode: Optional[AnchorMode] = None
    is_permanent: bool = True


class NGramEntry(BaseModel):
    id: Optional[int] = None
    word1: str
    word2: str
    word3: str
    frequency: int = 1


class CorrectionLogEntry(BaseModel):
    id: Optional[int] = None
    original_phrase: str
    corrected_phrase: str
    source: CorrectionSource
    occurrences: int = 1
    promoted: bool = False
