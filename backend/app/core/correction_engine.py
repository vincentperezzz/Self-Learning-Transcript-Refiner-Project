"""
CorrectionEngine – Orchestrates the 3-layer correction hierarchy.

Layer 1: Lexicon Check (Permanent Rules / Known Fixes)
Layer 2: N-Gram + Anchor logic for contextual rescoring
Layer 3: DistilBERT [MASK] prediction (stub – for low-confidence anomalies < 0.90)

Each segment flows through all three layers sequentially.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.correction_log import CorrectionLogger
from app.core.lexicon import LexiconChecker
from app.core.ngram_auditor import NGramAuditor
from app.core.semantic_anchors import SemanticAnchorManager
from app.config import LOW_CONFIDENCE_THRESHOLD
from app.models.schemas import (
    AnchorMode,
    CorrectionDetail,
    CorrectionSource,
    FlaggedWord,
    RefinedSegment,
    RefinementRequest,
    RefinementResponse,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


class CorrectionEngine:
    """
    Main orchestrator.  Instantiate once and call `refine()` per request.
    """

    def __init__(self) -> None:
        self.anchor_manager = SemanticAnchorManager()
        self.ngram_auditor = NGramAuditor()
        self.lexicon = LexiconChecker()
        self.correction_logger = CorrectionLogger()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def refine(self, request: RefinementRequest) -> RefinementResponse:
        """Run the full correction pipeline on a list of segments."""

        # 1. Build full transcript for anchor scanning
        full_text = " ".join(seg.text for seg in request.segments)
        self.anchor_manager.scan(full_text)
        active_mode = self.anchor_manager.active_mode

        refined_segments: list[RefinedSegment] = []
        total_corrections = 0

        for seg in request.segments:
            refined, corrections = self._refine_segment(seg, active_mode)
            total_corrections += len(corrections)
            refined_segments.append(refined)

        # 2. Ingest the *corrected* text into N-Gram table for learning
        corrected_full = " ".join(rs.refined_text for rs in refined_segments)
        self.ngram_auditor.ingest_text(corrected_full)

        return RefinementResponse(
            segments=refined_segments,
            total_corrections=total_corrections,
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _refine_segment(
        self,
        seg: TranscriptSegment,
        mode: AnchorMode,
    ) -> tuple[RefinedSegment, list[CorrectionDetail]]:
        text = seg.text
        all_corrections: list[CorrectionDetail] = []

        # --- Layer 1: Lexicon ---
        text, lex_corrections = self._layer_lexicon(text, mode)
        all_corrections.extend(lex_corrections)

        # --- Layer 2: N-Gram + Anchor ---
        text, ngram_corrections = self._layer_ngram(text, mode)
        all_corrections.extend(ngram_corrections)

        # --- Extract low-confidence words from per-word data ---
        flagged_words: list[FlaggedWord] = []
        if seg.words:
            flagged_words = [
                FlaggedWord(
                    word=w.word,
                    probability=w.probability,
                    start=w.start,
                    end=w.end,
                )
                for w in seg.words
                if w.probability < LOW_CONFIDENCE_THRESHOLD
            ]

        # --- Layer 3: DistilBERT (targets low-confidence words) ---
        has_low_conf = bool(flagged_words) or (
            seg.confidence is not None and seg.confidence < LOW_CONFIDENCE_THRESHOLD
        )
        if has_low_conf:
            text, bert_corrections = self._layer_distilbert(text, flagged_words)
            all_corrections.extend(bert_corrections)

        # Log every correction for the self-learning loop
        for c in all_corrections:
            self.correction_logger.log(c.original, c.corrected, c.source)

        return (
            RefinedSegment(
                start=seg.start,
                end=seg.end,
                original_text=seg.text,
                refined_text=text,
                corrections=all_corrections,
                anchor_mode=mode,
                low_confidence_words=flagged_words,
            ),
            all_corrections,
        )

    def _layer_lexicon(
        self, text: str, mode: AnchorMode
    ) -> tuple[str, list[CorrectionDetail]]:
        corrected, matches = self.lexicon.apply(text, mode)
        details = [
            CorrectionDetail(
                original=m.wrong_phrase,
                corrected=m.correct_phrase,
                source=CorrectionSource.LEXICON,
            )
            for m in matches
        ]
        return corrected, details

    def _layer_ngram(
        self, text: str, mode: Optional[AnchorMode] = None
    ) -> tuple[str, list[CorrectionDetail]]:
        self.ngram_auditor.build_trigrams(text)
        candidates = self.ngram_auditor.audit()

        details: list[CorrectionDetail] = []
        for cand in candidates:
            orig_phrase = " ".join(cand.original_trigram)
            sugg_phrase = " ".join(cand.suggested_trigram)

            # Perform the replacement (case-insensitive, first occurrence)
            import re

            pattern = re.compile(re.escape(orig_phrase), re.IGNORECASE)
            new_text = pattern.sub(sugg_phrase, text, count=1)
            if new_text != text:
                text = new_text
                details.append(
                    CorrectionDetail(
                        original=orig_phrase,
                        corrected=sugg_phrase,
                        source=CorrectionSource.NGRAM_ANCHOR,
                        confidence_delta=cand.confidence,
                    )
                )
        return text, details

    def _layer_distilbert(
        self, text: str, flagged: list[FlaggedWord] | None = None,
    ) -> tuple[str, list[CorrectionDetail]]:
        """
        Placeholder for DistilBERT [MASK] prediction.
        Will target specific low-confidence words when the model is integrated.
        """
        if flagged:
            words_str = ", ".join(f"{fw.word}({fw.probability:.2f})" for fw in flagged)
            logger.info("DistilBERT layer invoked (stub) – low-conf words: %s", words_str)
        else:
            logger.info("DistilBERT layer invoked (stub) for: %s", text[:80])
        return text, []
