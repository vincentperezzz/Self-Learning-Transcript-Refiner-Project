"""
Correction Log – Self-Learning Loop.

Every correction is logged.  When a specific correction reaches 5 occurrences
(Rule of 5), it is flagged for Gemini 2.5 Flash audit.  If verified, the
rule is promoted to a Permanent Lexicon Rule in Table A.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import CORRECTION_THRESHOLD
from app.database import get_db
from app.models.schemas import CorrectionSource


@dataclass
class PendingPromotion:
    """A correction that has reached the promotion threshold."""
    original_phrase: str
    corrected_phrase: str
    source: str
    occurrences: int


class CorrectionLogger:
    """Logs corrections and surfaces promotion candidates."""

    def log(
        self,
        original: str,
        corrected: str,
        source: CorrectionSource,
    ) -> int:
        """
        Record a correction.  Returns the new occurrence count.
        Uses UPSERT so repeated identical corrections increment the counter.
        """
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO correction_log (original_phrase, corrected_phrase, source, occurrences)
                VALUES (%s, %s, %s, 1)
                ON CONFLICT(original_phrase, corrected_phrase)
                DO UPDATE SET
                    occurrences = correction_log.occurrences + 1,
                    last_seen_at = now()
                """,
                (original, corrected, source.value),
            )
            cur = conn.execute(
                "SELECT occurrences FROM correction_log "
                "WHERE original_phrase = %s AND corrected_phrase = %s",
                (original, corrected),
            )
            row = cur.fetchone()
        return row["occurrences"] if row else 1

    def get_promotion_candidates(self) -> list[PendingPromotion]:
        """Return all corrections that hit the Rule-of-5 threshold but aren't promoted yet."""
        with get_db() as conn:
            cur = conn.execute(
                "SELECT original_phrase, corrected_phrase, source, occurrences "
                "FROM correction_log "
                "WHERE occurrences >= %s AND promoted = FALSE "
                "ORDER BY occurrences DESC",
                (CORRECTION_THRESHOLD,),
            )
            rows = cur.fetchall()
        return [
            PendingPromotion(
                original_phrase=r["original_phrase"],
                corrected_phrase=r["corrected_phrase"],
                source=r["source"],
                occurrences=r["occurrences"],
            )
            for r in rows
        ]

    def mark_promoted(self, original: str, corrected: str) -> None:
        """Flag a correction as promoted (added to permanent lexicon)."""
        with get_db() as conn:
            conn.execute(
                "UPDATE correction_log SET promoted = TRUE "
                "WHERE original_phrase = %s AND corrected_phrase = %s",
                (original, corrected),
            )
