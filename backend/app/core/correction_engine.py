"""
CorrectionEngine – Orchestrates the correction pipeline.

Layer 1: Lexicon Check (Permanent Rules / Known Fixes)
Layer 2: N-Gram + Anchor logic for contextual rescoring
Post:    Currency normalizer (P/$→₱) + double-word deduplication
Layer 3: Gemini 2.5 Flash (analyzes remaining errors, teaches the lexicon)

Gemini acts as a "teacher" — corrections are applied to the current transcript
AND auto-added to the lexicon so future transcripts are handled by L1 directly.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from app.core.correction_log import CorrectionLogger
from app.core.gemini_corrector import GeminiCorrection, correct_transcript_sync
from app.core.lexicon import LexiconChecker
from app.core.ngram_auditor import NGramAuditor
from app.core.semantic_anchors import SemanticAnchorManager
from app.config import LOW_CONFIDENCE_THRESHOLD
from app.database import get_db
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

    def refine(self, request: RefinementRequest, on_stage: Callable[[str], None] | None = None) -> RefinementResponse:
        """Run the full correction pipeline on a list of segments."""

        segments = request.segments
        refined_segments: list[RefinedSegment] = []
        total_corrections = 0

        # --- Pass 1: Lexicon + N-Gram + post-processing per segment ---
        all_flagged: list[dict] = []
        applied_lexicon_rules: list[tuple[str, str]] = []
        for idx, seg in enumerate(segments):
            ctx_before = segments[idx - 1].text if idx > 0 else ""
            ctx_after = segments[idx + 1].text if idx < len(segments) - 1 else ""

            seg_mode = self.anchor_manager.scan_segment(
                seg.text, ctx_before, ctx_after
            )

            refined, corrections = self._refine_segment(seg, seg_mode)
            total_corrections += len(corrections)
            refined_segments.append(refined)

            # Track which lexicon rules were applied
            for c in corrections:
                if c.source == CorrectionSource.LEXICON:
                    applied_lexicon_rules.append((c.original, c.corrected))

            # Collect low-confidence words for Gemini
            for fw in refined.low_confidence_words:
                all_flagged.append({
                    "segment_index": idx,
                    "word": fw.word,
                    "probability": fw.probability,
                })

            # Signal ngram stage after first segment is processed
            if idx == 0 and on_stage:
                on_stage("ngram")

        # --- Pass 2: Gemini correction for remaining issues ---
        # Determine which segments need Gemini analysis:
        #   1) Segments with low-confidence words
        #   2) Segments where L1/L2 made no corrections (unknown patterns)
        needs_gemini = False
        for idx, rs in enumerate(refined_segments):
            has_low_conf = len(rs.low_confidence_words) > 0
            had_no_fixes = len(rs.corrections) == 0
            if has_low_conf or had_no_fixes:
                needs_gemini = True
                break

        if needs_gemini:
            if on_stage:
                on_stage("gemini")
            gemini_input = [
                {
                    "index": idx,
                    "text": rs.refined_text,
                    "start": rs.start,
                    "end": rs.end,
                }
                for idx, rs in enumerate(refined_segments)
            ]

            gemini_corrections = correct_transcript_sync(
                segments=gemini_input,
                low_confidence_words=all_flagged if all_flagged else None,
                applied_rules=applied_lexicon_rules if applied_lexicon_rules else None,
            )

            # Apply Gemini corrections and auto-learn
            # Build set of already-applied rules for duplicate filtering (Option E)
            applied_set = set(applied_lexicon_rules)
            for gc in gemini_corrections:
                # Skip if L1 already applied this exact correction
                if (gc.original, gc.corrected) in applied_set:
                    logger.debug("Skipping Gemini duplicate: '%s' → '%s'", gc.original, gc.corrected)
                    continue
                if 0 <= gc.segment_index < len(refined_segments):
                    rs = refined_segments[gc.segment_index]
                    # Apply correction to the refined text
                    pattern = re.compile(re.escape(gc.original), re.IGNORECASE)
                    new_text = pattern.sub(gc.corrected, rs.refined_text, count=1)
                    if new_text != rs.refined_text:
                        rs.refined_text = new_text
                        correction = CorrectionDetail(
                            original=gc.original,
                            corrected=gc.corrected,
                            source=CorrectionSource.GEMINI,
                        )
                        rs.corrections.append(correction)
                        total_corrections += 1

                        # Log for self-learning
                        self.correction_logger.log(
                            gc.original, gc.corrected, CorrectionSource.GEMINI
                        )

                        # Auto-add to lexicon for future matching
                        self._auto_add_lexicon_rule(gc)
                        logger.info(
                            "Gemini corrected [seg %d]: '%s' → '%s'",
                            gc.segment_index, gc.original, gc.corrected,
                        )

        # Ingest the *corrected* text into N-Gram table for learning
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

        # --- Post-processing: currency normalizer ---
        text, currency_corrections = self._post_currency(text)
        all_corrections.extend(currency_corrections)

        # --- Post-processing: written-out peso amounts ---
        text, pesos_corrections = self._post_pesos_text(text)
        all_corrections.extend(pesos_corrections)

        # --- Post-processing: double-word deduplication ---
        text, dedup_corrections = self._post_dedup_words(text)
        all_corrections.extend(dedup_corrections)

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
                # Auto-add as probationary lexicon rule
                self._auto_add_ngram_rule(orig_phrase, sugg_phrase)
        return text, details

    def _auto_add_lexicon_rule(self, gc: GeminiCorrection) -> None:
        """Add a Gemini correction to the lexicon so L1 catches it next time."""
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO lexicon (wrong_phrase, correct_phrase, context_hint, is_permanent) "
                    "VALUES (%s, %s, %s, TRUE) "
                    "ON CONFLICT (wrong_phrase) DO NOTHING",
                    (gc.original.lower(), gc.corrected, "auto-learned from Gemini"),
                )
        except Exception as e:
            logger.warning("Failed to auto-add lexicon rule '%s': %s", gc.original, e)

    def _auto_add_ngram_rule(self, original: str, corrected: str) -> None:
        """Add an N-Gram correction as a probationary lexicon rule."""
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO lexicon (wrong_phrase, correct_phrase, context_hint, is_permanent) "
                    "VALUES (%s, %s, %s, FALSE) "
                    "ON CONFLICT (wrong_phrase) DO NOTHING",
                    (original.lower(), corrected, "auto-promoted from N-Gram (probationary)"),
                )
        except Exception as e:
            logger.warning("Failed to auto-add N-Gram rule '%s': %s", original, e)

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    # Regex: P or $ followed by digits (currency amounts) → ₱
    _CURRENCY_RE = re.compile(
        r'(?<![a-zA-Z])'   # not preceded by a letter
        r'[P$]'            # P or $
        r'(?=\d)'          # followed by a digit
    )

    # Regex: standalone comma-formatted amounts without any currency prefix
    # Matches patterns like "34,847.72" or "6,828.13" (thousands with comma)
    # but NOT preceded by ₱, P, $, or a letter
    _BARE_AMOUNT_RE = re.compile(
        r'(?<![₱P$a-zA-Z])'        # not preceded by currency or letter
        r'(?<!\d)'                   # not preceded by another digit
        r'(\d{1,3}(?:,\d{3})+\.\d{2})'  # comma-formatted: 1,000.00 or 34,847.72
        r'(?!\d)'                    # not followed by another digit
    )

    def _post_currency(self, text: str) -> tuple[str, list[CorrectionDetail]]:
        """Normalize P5,000 / $5,000 → ₱5,000 and add ₱ to bare amounts."""
        details: list[CorrectionDetail] = []

        # Pass 1: Replace P/$ prefix with ₱
        new_text = self._CURRENCY_RE.sub("₱", text)
        if new_text != text:
            details.append(
                CorrectionDetail(
                    original="P/$ currency prefix",
                    corrected="₱ (PHP)",
                    source=CorrectionSource.LEXICON,
                )
            )

        # Pass 2: Prepend ₱ to bare comma-formatted amounts (Whisper dropped prefix)
        text2 = self._BARE_AMOUNT_RE.sub(r"₱\1", new_text)
        if text2 != new_text:
            details.append(
                CorrectionDetail(
                    original="bare amount (no currency)",
                    corrected="₱ prefix added",
                    source=CorrectionSource.LEXICON,
                )
            )
            new_text = text2

        return new_text, details

    # Regex: "X pesos and Y centavos" / "X pesos" → ₱X.YY
    _PESOS_CENTAVOS_RE = re.compile(
        r'(\d[\d,]*)\s+pesos?\s+and\s+(\d{1,2})\s+centavos?',
        re.IGNORECASE,
    )
    _PESOS_ONLY_RE = re.compile(
        r'(\d[\d,]*)\s+pesos?(?!\s+and\s+\d{1,2}\s+centavo)',
        re.IGNORECASE,
    )

    @staticmethod
    def _pesos_centavos_repl(m: re.Match) -> str:
        whole = m.group(1)
        cents = m.group(2).zfill(2)
        return f"₱{whole}.{cents}"

    @staticmethod
    def _pesos_only_repl(m: re.Match) -> str:
        whole = m.group(1)
        return f"₱{whole}.00"

    # Regex: redundant "centavos" after ₱ amount with decimals
    _REDUNDANT_CENTAVOS_RE = re.compile(
        r'(₱[\d,]+\.\d{2})\s+centavos?',
        re.IGNORECASE,
    )

    def _post_pesos_text(self, text: str) -> tuple[str, list[CorrectionDetail]]:
        """Convert written-out peso amounts to ₱ numeric format and remove redundant centavos."""
        details: list[CorrectionDetail] = []
        # Pass 1: "X pesos and Y centavos"
        new_text = self._PESOS_CENTAVOS_RE.sub(self._pesos_centavos_repl, text)
        # Pass 2: "X pesos" alone
        new_text = self._PESOS_ONLY_RE.sub(self._pesos_only_repl, new_text)
        # Pass 3: Remove redundant "centavos" after ₱X,XXX.XX
        new_text = self._REDUNDANT_CENTAVOS_RE.sub(r'\1', new_text)
        if new_text != text:
            details.append(
                CorrectionDetail(
                    original="written-out peso amount",
                    corrected="₱ numeric format",
                    source=CorrectionSource.LEXICON,
                )
            )
        return new_text, details

    # Regex: consecutive duplicate words (case-insensitive)
    _DOUBLE_WORD_RE = re.compile(
        r'\b(\w+)\s+\1\b',
        re.IGNORECASE,
    )

    def _post_dedup_words(self, text: str) -> tuple[str, list[CorrectionDetail]]:
        """Remove accidental double words: 'birthdate date' isn't caught here,
        but exact duplicates like 'settle settle' are."""
        details: list[CorrectionDetail] = []
        new_text = self._DOUBLE_WORD_RE.sub(r'\1', text)
        if new_text != text:
            details.append(
                CorrectionDetail(
                    original="double word",
                    corrected="deduplicated",
                    source=CorrectionSource.LEXICON,
                )
            )
        return new_text, details
