"""
Gemini 2.5 Flash Auditor – Validates promotion candidates.

When a correction reaches the Rule-of-5 threshold, this module sends the
correction with surrounding context to Gemini 2.5 Flash for validation.

Context window: 3 words before + the correction + 5 words after
(as specified in the architecture diagram).

If Gemini confirms the correction is legitimate for Philippine call-center
transcripts, the correction is promoted to a permanent lexicon rule.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

SYSTEM_PROMPT = """\
You are a QA auditor for Philippine call-center transcripts produced by Whisper ASR.

You will receive a proposed correction rule. Your job is to decide whether
this correction should become a PERMANENT lexicon replacement rule.

Consider:
1. Is the "wrong" phrase a common Whisper mis-transcription?
2. Is the "correct" phrase the right replacement in Philippine English / Filipino
   call-center context?
3. Does the surrounding context support this replacement?
4. Would applying this rule always be safe, or could it cause false positives?

Respond with EXACTLY one JSON object (no markdown fencing):
{"approved": true, "reason": "short explanation"}
or
{"approved": false, "reason": "short explanation"}
"""

AUDIT_TEMPLATE = """\
Proposed correction rule:
  Wrong phrase:   "{original}"
  Correct phrase: "{corrected}"
  Source layer:   {source}
  Times seen:     {occurrences}

Recent context examples where this correction was applied:
{context_examples}

Should this become a permanent lexicon rule? Respond with JSON only.
"""


@dataclass
class AuditResult:
    """Result of a Gemini audit on a promotion candidate."""
    original: str
    corrected: str
    approved: bool
    reason: str


def _build_context_window(
    full_text: str,
    original_phrase: str,
    words_before: int = 3,
    words_after: int = 5,
) -> str:
    """
    Extract a context window around the original phrase in the full text.
    Returns: "... word1 word2 word3 [ORIGINAL] word4 word5 word6 word7 word8 ..."
    """
    import re

    pattern = re.compile(re.escape(original_phrase), re.IGNORECASE)
    match = pattern.search(full_text)
    if not match:
        return full_text[:200]  # fallback

    # Get all words and find position
    words = full_text.split()
    # Find which word index the match starts at
    char_pos = 0
    start_word_idx = 0
    for i, w in enumerate(words):
        if char_pos >= match.start():
            start_word_idx = i
            break
        char_pos += len(w) + 1  # +1 for space

    # Calculate word span of the original phrase
    orig_word_count = len(original_phrase.split())
    end_word_idx = start_word_idx + orig_word_count

    before_start = max(0, start_word_idx - words_before)
    after_end = min(len(words), end_word_idx + words_after)

    before_ctx = " ".join(words[before_start:start_word_idx])
    after_ctx = " ".join(words[end_word_idx:after_end])

    return f"...{before_ctx} [{original_phrase}] {after_ctx}..."


async def audit_candidate(
    original: str,
    corrected: str,
    source: str,
    occurrences: int,
    context_texts: Optional[list[str]] = None,
) -> AuditResult:
    """
    Send a promotion candidate to Gemini 2.5 Flash for validation.

    Args:
        original: The wrong phrase
        corrected: The proposed correct phrase
        source: Which layer produced this correction (lexicon/ngram/distilbert)
        occurrences: How many times this correction has been seen
        context_texts: Optional list of full text snippets where the correction occurred

    Returns:
        AuditResult with approved=True/False and reason
    """
    if not GEMINI_API_KEY:
        logger.warning(
            "GEMINI_API_KEY not set – auto-approving candidate: '%s' → '%s'",
            original, corrected,
        )
        return AuditResult(
            original=original,
            corrected=corrected,
            approved=True,
            reason="Auto-approved (no Gemini API key configured)",
        )

    # Build context examples
    context_examples = ""
    if context_texts:
        for i, ctx in enumerate(context_texts[:3], 1):  # Max 3 examples
            window = _build_context_window(ctx, original)
            context_examples += f"  Example {i}: {window}\n"
    else:
        context_examples = "  (no context examples available)\n"

    user_message = AUDIT_TEMPLATE.format(
        original=original,
        corrected=corrected,
        source=source,
        occurrences=occurrences,
        context_examples=context_examples,
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT + "\n\n" + user_message}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 256,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GEMINI_API_URL,
                params={"key": GEMINI_API_KEY},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract the text response
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        # Strip markdown code fences if present
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        result = json.loads(text)
        approved = bool(result.get("approved", False))
        reason = str(result.get("reason", "No reason provided"))

        logger.info(
            "Gemini audit: '%s' → '%s' : %s (%s)",
            original, corrected,
            "APPROVED" if approved else "REJECTED",
            reason,
        )

        return AuditResult(
            original=original,
            corrected=corrected,
            approved=approved,
            reason=reason,
        )

    except httpx.HTTPStatusError as e:
        logger.error("Gemini API HTTP error: %s – %s", e.response.status_code, e.response.text[:300])
        return AuditResult(
            original=original,
            corrected=corrected,
            approved=False,
            reason=f"Gemini API error: {e.response.status_code}",
        )
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error("Failed to parse Gemini response: %s", e)
        return AuditResult(
            original=original,
            corrected=corrected,
            approved=False,
            reason=f"Failed to parse Gemini response: {e}",
        )
    except Exception as e:
        logger.error("Gemini audit failed: %s", e)
        return AuditResult(
            original=original,
            corrected=corrected,
            approved=False,
            reason=f"Audit failed: {e}",
        )
