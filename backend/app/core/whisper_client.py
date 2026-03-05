"""
Lightning AI Whisper Client – Sends audio to the remote Whisper API
hosted on Lightning AI and returns raw transcript segments.

The Phoenix backend does NOT run Whisper locally.  Audio files are
forwarded to the Lightning AI endpoint, and the response is parsed
into TranscriptSegment objects for the correction pipeline.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import LIGHTNING_API_URL, LIGHTNING_API_KEY
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
    Send an audio file to the Lightning AI Whisper endpoint.

    Requests word_timestamps=true so we get per-word confidence scores.

    Expected Lightning AI response shape (Whisper with word timestamps):
    {
      "segments": [
        {
          "start": 0.0, "end": 3.4,
          "text": "Hello good morning",
          "avg_logprob": -0.23,
          "words": [
            { "word": "Hello", "start": 0.0, "end": 0.5, "probability": 0.95 },
            { "word": "good",  "start": 0.5, "end": 0.8, "probability": 0.42 },
            ...
          ]
        }
      ]
    }

    Returns a list of TranscriptSegment with per-word confidence data.
    """
    headers: dict[str, str] = {}
    if LIGHTNING_API_KEY:
        headers["Authorization"] = f"Bearer {LIGHTNING_API_KEY}"

    params: dict[str, str] = {"word_timestamps": "true"}
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        logger.info("Sending %s (%d bytes) to Lightning AI Whisper", filename, len(audio_bytes))

        response = await client.post(
            LIGHTNING_API_URL,
            files={"file": (filename, audio_bytes, "audio/wav")},
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        data = response.json()

    segments: list[TranscriptSegment] = []
    for seg in data.get("segments", []):
        # Segment-level confidence from avg_logprob
        logprob = seg.get("avg_logprob", -0.5)
        confidence = max(0.0, min(1.0, 1.0 + logprob))

        # Per-word confidence
        words: list[WordInfo] | None = None
        raw_words = seg.get("words")
        if raw_words:
            words = [
                WordInfo(
                    word=w["word"].strip(),
                    start=w["start"],
                    end=w["end"],
                    probability=round(w.get("probability", 0.0), 4),
                )
                for w in raw_words
            ]

        segments.append(
            TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
                confidence=round(confidence, 4),
                words=words,
            )
        )

    logger.info("Received %d segments from Lightning AI", len(segments))
    return segments
