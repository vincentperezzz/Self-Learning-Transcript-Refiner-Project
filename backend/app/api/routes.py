"""Phoenix 3.0 API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from typing import Optional

from app.config import LIGHTNING_API_URL
from app.core.correction_engine import CorrectionEngine
from app.core.correction_log import CorrectionLogger
from app.core.lexicon import LexiconChecker
from app.core.ngram_auditor import NGramAuditor
from app.core.whisper_client import transcribe_audio
from app.models.schemas import (
    LexiconRule,
    NGramEntry,
    RefinementRequest,
    RefinementResponse,
)

router = APIRouter()

# Singletons
_engine = CorrectionEngine()
_logger = CorrectionLogger()


# ------------------------------------------------------------------
# Full pipeline: Audio → Lightning AI Whisper → Refiner
# ------------------------------------------------------------------

@router.post("/transcribe", response_model=RefinementResponse)
async def transcribe_and_refine(
    file: UploadFile = File(...),
    speaker: Optional[str] = Query(None, description="agent or client"),
    language: Optional[str] = Query(None, description="e.g. en, tl"),
) -> RefinementResponse:
    """
    Upload an audio file.  It is sent to Lightning AI's Whisper endpoint
    for transcription, then the raw segments are run through the 3-layer
    correction hierarchy and returned as refined output.
    """
    if not LIGHTNING_API_URL:
        raise HTTPException(
            status_code=503,
            detail="LIGHTNING_API_URL is not configured. Set it in the environment.",
        )

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    try:
        segments = await transcribe_audio(
            audio_bytes=audio_bytes,
            filename=file.filename or "audio.wav",
            language=language,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Lightning AI Whisper call failed: {exc}",
        )

    request = RefinementRequest(segments=segments, speaker=speaker)
    return _engine.refine(request)


# ------------------------------------------------------------------
# Core endpoint
# ------------------------------------------------------------------

@router.post("/refine", response_model=RefinementResponse)
def refine_transcript(payload: RefinementRequest) -> RefinementResponse:
    """
    Accept raw Whisper segments, run the 3-layer correction hierarchy,
    and return refined segments with correction details.
    """
    return _engine.refine(payload)


# ------------------------------------------------------------------
# Lexicon CRUD
# ------------------------------------------------------------------

@router.post("/lexicon", status_code=201)
def add_lexicon_rule(rule: LexiconRule) -> dict:
    """Add a permanent lexicon rule (Table A)."""
    LexiconChecker.add_rule(
        wrong_phrase=rule.wrong_phrase,
        correct_phrase=rule.correct_phrase,
        context_hint=rule.context_hint,
        anchor_mode=rule.anchor_mode,
    )
    return {"status": "created", "wrong_phrase": rule.wrong_phrase}


# ------------------------------------------------------------------
# N-Gram ingestion
# ------------------------------------------------------------------

@router.post("/ngram/ingest")
def ingest_ngrams(payload: dict) -> dict:
    """
    Ingest text into the N-Gram frequency table.
    Body: { "texts": ["sentence one", "sentence two"] }
    """
    texts = payload.get("texts")
    if not texts or not isinstance(texts, list):
        raise HTTPException(status_code=422, detail="'texts' must be a list of strings")
    count = NGramAuditor.bulk_ingest(texts)
    return {"trigrams_processed": count}


@router.get("/ngram/lookup")
def lookup_ngram(w1: str, w2: str, w3: str) -> dict:
    """Look up the frequency of a specific trigram."""
    freq = NGramAuditor.lookup_frequency(w1, w2, w3)
    return {"trigram": [w1, w2, w3], "frequency": freq}


# ------------------------------------------------------------------
# Self-learning / promotion
# ------------------------------------------------------------------

@router.get("/corrections/candidates")
def promotion_candidates() -> dict:
    """List corrections that reached the Rule-of-5 threshold."""
    candidates = _logger.get_promotion_candidates()
    return {
        "count": len(candidates),
        "candidates": [
            {
                "original": c.original_phrase,
                "corrected": c.corrected_phrase,
                "source": c.source,
                "occurrences": c.occurrences,
            }
            for c in candidates
        ],
    }


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "phoenix-3.0-refiner"}
