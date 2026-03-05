"""
Whisper Client – Sends audio to Groq's hosted Whisper large-v3-turbo
and returns raw transcript segments.

Groq provides an OpenAI-compatible /audio/transcriptions endpoint
running Whisper large-v3-turbo on their infrastructure.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import GROQ_API_KEY, GROQ_WHISPER_URL
from app.models.schemas import TranscriptSegment, WordInfo

logger = logging.getLogger(__name__)

# Timeout: 5 min for long audio files
_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    language: Optional[str] = None,
) -> list[TranscriptSegment]:
    """
    Send an audio file to Groq's Whisper API.

    Uses response_format=verbose_json with timestamp_granularities[]=word
    to get per-word confidence scores.

    Returns a list of TranscriptSegment with per-word confidence data.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")

    # Request both segment and word granularities.
    # Groq requires both to return non-null segments AND top-level words.
    form_data: dict[str, str | list[str]] = {
        "model": "whisper-large-v3-turbo",
        "response_format": "verbose_json",
        "timestamp_granularities[]": ["word", "segment"],
    }
    if language:
        form_data["language"] = language

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        logger.info("Sending %s (%d bytes) to Groq Whisper API", filename, len(audio_bytes))

        response = await client.post(
            GROQ_WHISPER_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            data=form_data,
            files={"file": (filename, audio_bytes, "audio/wav")},
        )
        response.raise_for_status()
        data = response.json()

    # Groq returns:
    #   "segments": [{id, start, end, text, avg_logprob, ...}]
    #   "words": [{word, start, end}]  (no per-word probability)
    segments: list[TranscriptSegment] = []

    raw_segments = data.get("segments") or []
    raw_words_all = data.get("words") or []

    for seg in raw_segments:
        seg_start = seg["start"]
        seg_end = seg["end"]

        # Segment-level confidence from avg_logprob
        logprob = seg.get("avg_logprob", -0.5)
        confidence = max(0.0, min(1.0, 1.0 + logprob))

        # Collect words that fall within this segment's time range
        words: list[WordInfo] = []
        for w in raw_words_all:
            w_start = w.get("start", 0.0)
            if seg_start <= w_start < seg_end:
                words.append(
                    WordInfo(
                        word=w["word"].strip(),
                        start=w_start,
                        end=w.get("end", w_start),
                        # Groq doesn't provide per-word probability;
                        # use segment-level confidence as fallback
                        probability=round(confidence, 4),
                    )
                )

        segments.append(
            TranscriptSegment(
                start=seg_start,
                end=seg_end,
                text=seg["text"].strip(),
                confidence=round(confidence, 4),
                words=words if words else None,
            )
        )

    logger.info("Received %d segments from Groq Whisper", len(segments))
    return segments
