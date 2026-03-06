"""
DistilBERT Predictor – Layer 3 of the Correction Hierarchy.

Uses distilbert-base-multilingual-cased with fill-mask pipeline to predict
contextual replacements for low-confidence words flagged by Whisper.

Flow:
  1. Receive the transcript text + list of low-confidence words
  2. For each low-confidence word, mask it in context
  3. Ask DistilBERT to predict the most likely word in that position
  4. If the prediction differs from the original AND has high model confidence,
     propose the correction
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-loaded pipeline (heavy import)
_pipeline = None
_MASK_TOKEN = "[MASK]"


def _get_pipeline():
    """Lazy-load the fill-mask pipeline to avoid slow startup."""
    global _pipeline
    if _pipeline is None:
        logger.info("Loading DistilBERT fill-mask pipeline (first call)...")
        from transformers import pipeline
        _pipeline = pipeline(
            "fill-mask",
            model="distilbert-base-multilingual-cased",
            top_k=5,
        )
        logger.info("DistilBERT pipeline ready.")
    return _pipeline


def predict_masked_word(
    text: str,
    target_word: str,
    target_start: Optional[float] = None,
    min_model_score: float = 0.15,
) -> Optional[tuple[str, float]]:
    """
    Mask *target_word* in *text* and ask DistilBERT to predict the fill.

    Returns (predicted_word, model_score) if the prediction differs from
    the original and exceeds min_model_score. Otherwise returns None.

    Args:
        text: The full segment text.
        target_word: The low-confidence word to mask.
        target_start: Optional start time for disambiguation (not used by model).
        min_model_score: Minimum model confidence to accept a prediction.

    Returns:
        (predicted_word, score) or None if no viable replacement found.
    """
    pipe = _get_pipeline()

    # Replace the FIRST occurrence of target_word with [MASK]
    # Use word-boundary-aware replacement to avoid partial matches
    pattern = re.compile(r"\b" + re.escape(target_word) + r"\b", re.IGNORECASE)
    masked_text = pattern.sub(_MASK_TOKEN, text, count=1)

    if _MASK_TOKEN not in masked_text:
        # Word not found in text (edge case)
        return None

    # Truncate to ~400 chars around the mask to stay within model limits
    mask_pos = masked_text.index(_MASK_TOKEN)
    window_start = max(0, mask_pos - 200)
    window_end = min(len(masked_text), mask_pos + 200)
    windowed = masked_text[window_start:window_end]

    try:
        predictions = pipe(windowed)
    except Exception as e:
        logger.warning("DistilBERT prediction failed: %s", e)
        return None

    if not predictions:
        return None

    # predictions is a list of dicts: [{"score": 0.9, "token_str": "line", ...}]
    for pred in predictions:
        predicted = pred["token_str"].strip()
        score = pred["score"]

        # Skip if the prediction is the same as the original
        if predicted.lower() == target_word.lower():
            continue

        # Skip very short or punctuation-only predictions
        if len(predicted) < 2 or not any(c.isalpha() for c in predicted):
            continue

        # Only accept if model is reasonably confident
        if score >= min_model_score:
            logger.info(
                "DistilBERT: '%s' → '%s' (score=%.3f)",
                target_word, predicted, score,
            )
            return (predicted, score)

    return None
