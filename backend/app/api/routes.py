"""Phoenix 3.0 API routes."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import PlainTextResponse
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional

from app.auth import (
    UserCreate,
    UserOut,
    PasswordChange,
    TokenResponse,
    create_access_token,
    create_user_in_db,
    get_current_user,
    get_user_by_username,
    hash_password,
    require_superadmin,
    verify_password,
)
from app.core.correction_engine import CorrectionEngine
from app.core.correction_log import CorrectionLogger
from app.core.gemini_corrector import correct_segment_with_instruction
from app.core.lexicon import LexiconChecker
from app.core.ngram_auditor import NGramAuditor
from app.core.whisper_client import transcribe_audio_sync
from app.database import get_db
from app.models.schemas import (
    CorrectionSource,
    LexiconRule,
    NGramEntry,
    PlainTextImportRequest,
    RefinementRequest,
    RefinementResponse,
    TranscriptSegment,
)

router = APIRouter()

# Singletons
_engine = CorrectionEngine()
_logger = CorrectionLogger()


# ===================================================================
# AUTH
# ===================================================================

@router.post("/auth/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    user = get_user_by_username(form.username)
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user["id"], user["username"], user["role"])
    return TokenResponse(access_token=token)


@router.get("/auth/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)) -> UserOut:
    return UserOut(**user)


@router.put("/auth/password")
def change_password(
    payload: PasswordChange,
    user: dict = Depends(get_current_user),
) -> dict:
    db_user = get_user_by_username(user["username"])
    if not db_user or not verify_password(payload.current_password, db_user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_hash = hash_password(payload.new_password)
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (new_hash, user["id"]),
        )
    return {"status": "password_updated"}


@router.post("/auth/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    _admin: dict = Depends(require_superadmin),
) -> UserOut:
    existing = get_user_by_username(payload.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")
    row = create_user_in_db(payload.username, payload.password, payload.role)
    return UserOut(**row)


@router.get("/auth/users")
def list_users(_admin: dict = Depends(require_superadmin)) -> dict:
    with get_db() as conn:
        cur = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
        rows = cur.fetchall()
    return {"users": [dict(r) for r in rows]}


@router.delete("/auth/users/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(require_superadmin)) -> dict:
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    return {"status": "deleted"}


# ===================================================================
# TRANSCRIPTION (protected)
# ===================================================================

@router.post("/transcribe")
async def transcribe_and_refine(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    speaker: Optional[str] = Query(None, description="agent or client"),
    language: Optional[str] = Query(None, description="e.g. en, tl"),
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Upload audio → create session immediately (status=processing)
    → process transcription + refinement in background.
    Returns the session ID so frontend can redirect and poll.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    filename = file.filename or "audio.wav"
    session_key = uuid.uuid4().hex

    # Create session immediately with "processing" status
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO transcription_sessions "
            "(session_key, filename, speaker, user_id, status, total_segments, total_corrections) "
            "VALUES (%s, %s, %s, %s, 'processing', 0, 0) RETURNING id",
            (session_key, filename, speaker, user["id"]),
        )
        row = cur.fetchone()
        session_id = row["id"]

    # Process in background (sync — runs in thread pool)
    background_tasks.add_task(
        _process_transcription_sync, session_id, audio_bytes, filename, speaker, language
    )

    return {"session_key": session_key, "status": "processing"}


def _process_transcription_sync(
    session_id: int,
    audio_bytes: bytes,
    filename: str,
    speaker: Optional[str],
    language: Optional[str],
) -> None:
    """Background task (sync): transcribe via Groq, refine, update session."""
    import logging
    log = logging.getLogger(__name__)

    def _set_stage(stage: str) -> None:
        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions SET processing_stage = %s WHERE id = %s",
                (stage, session_id),
            )

    try:
        log.info("BG task started for session %s", session_id)

        # Stage 1: Whisper transcription
        _set_stage("whisper")
        segments = transcribe_audio_sync(
            audio_bytes=audio_bytes,
            filename=filename,
            language=language,
        )

        # Stage 2: Lexicon + N-Gram correction
        _set_stage("lexicon")
        request = RefinementRequest(segments=segments, speaker=speaker)
        result = _engine.refine(request, on_stage=_set_stage)
        result_dict = result.model_dump(mode="json")

        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions "
                "SET status = 'completed', processing_stage = NULL, total_segments = %s, "
                "total_corrections = %s, result_json = %s, completed_at = now() "
                "WHERE id = %s",
                (
                    len(result.segments),
                    result.total_corrections,
                    json.dumps(result_dict),
                    session_id,
                ),
            )
        log.info("BG task completed for session %s: %d segments, %d corrections",
                 session_id, len(result.segments), result.total_corrections)
    except Exception as exc:
        log.error("Transcription failed for session %s: %s", session_id, exc, exc_info=True)
        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions "
                "SET status = 'failed', error_message = %s "
                "WHERE id = %s",
                (str(exc)[:500], session_id),
            )


@router.post("/refine", response_model=RefinementResponse)
def refine_transcript(
    payload: RefinementRequest,
    _user: dict = Depends(get_current_user),
) -> RefinementResponse:
    return _engine.refine(payload)


# ===================================================================
# PLAIN TEXT IMPORT
# ===================================================================

import re as _re

_SPEAKER_PREFIX_RE = _re.compile(r'^(Agent|Client|Mixed):\s*', _re.IGNORECASE)


def _parse_plain_text_transcript(text: str) -> list[TranscriptSegment]:
    """Parse plain text with Agent:/Client:/Mixed: prefixes into segments.

    Rules:
    - Lines starting with Agent:/Client:/Mixed: create new segments
    - Lines without a prefix are appended to the previous segment
    - Empty lines are ignored
    - Timestamps are synthetic (0.0 for start, incremented by segment)
    """
    lines = text.strip().split('\n')
    segments: list[TranscriptSegment] = []
    current_speaker: str | None = None
    current_text: list[str] = []

    def flush_segment():
        nonlocal current_speaker, current_text
        if current_speaker and current_text:
            idx = len(segments)
            segments.append(TranscriptSegment(
                start=float(idx),
                end=float(idx + 1),
                text=' '.join(current_text).strip(),
                confidence=1.0,  # Placeholder since no Whisper confidence
                words=None,
            ))
        current_text = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = _SPEAKER_PREFIX_RE.match(line)
        if match:
            # Flush previous segment
            flush_segment()
            # Start new segment
            speaker = match.group(1).lower()
            current_speaker = speaker
            rest = line[match.end():]
            if rest:
                current_text.append(rest)
        elif current_speaker:
            # Continuation of previous segment
            current_text.append(line)
        else:
            # No speaker yet, treat as standalone segment
            current_speaker = 'mixed'
            current_text.append(line)

    # Flush final segment
    flush_segment()

    return segments


@router.post("/import-text")
async def import_plain_text(
    payload: PlainTextImportRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
) -> dict:
    """Import plain text transcript and create a session for it.

    Text format:
        Agent: Hello, this is calling from SP Madrid.
        Client: Yes po, I received the letter.
        Agent: OK po, regarding your outstanding balance...

    Returns session_key for tracking the refinement process.
    """
    from datetime import datetime

    segments = _parse_plain_text_transcript(payload.text)
    if not segments:
        raise HTTPException(status_code=400, detail="No segments found in text")

    # Create session with timestamped filename
    session_key = str(uuid.uuid4())[:12].replace("-", "")
    timestamp = datetime.now().strftime("%Y-%m-%d %H.%M.%S")
    filename = f"text_import_{timestamp}.txt"

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO transcription_sessions "
            "(session_key, filename, speaker, status, processing_stage, user_id) "
            "VALUES (%s, %s, %s, 'processing', 'refinement', %s) "
            "RETURNING id",
            (session_key, filename, "mixed", user["id"]),
        )
        session_id = cur.fetchone()["id"]

    # Process in background (like audio transcription)
    background_tasks.add_task(
        _process_text_import,
        session_id,
        session_key,
        segments,
    )

    return {"session_key": session_key, "status": "processing", "segment_count": len(segments)}


def _process_text_import(
    session_id: int,
    session_key: str,
    segments: list[TranscriptSegment],
):
    """Background task to refine imported text segments."""
    import logging
    log = logging.getLogger(__name__)

    def _set_stage(stage: str) -> None:
        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions SET processing_stage = %s WHERE id = %s",
                (stage, session_id),
            )

    try:
        log.info("Text import processing started for session %s", session_id)

        # Build refinement request (already at 'refinement' stage, skipping whisper)
        _set_stage("lexicon")
        request = RefinementRequest(segments=segments, speaker="mixed")
        result = _engine.refine(request, on_stage=_set_stage)

        # Save result
        result_data = {
            "segments": [seg.model_dump() for seg in result.segments],
            "total_corrections": result.total_corrections,
        }

        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions "
                "SET status = 'completed', processing_stage = 'done', "
                "result_json = %s, total_segments = %s, total_corrections = %s, "
                "completed_at = NOW() "
                "WHERE id = %s",
                (
                    json.dumps(result_data),
                    len(result.segments),
                    result.total_corrections,
                    session_id,
                ),
            )

    except Exception as exc:
        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions "
                "SET status = 'failed', error_message = %s "
                "WHERE id = %s",
                (str(exc)[:500], session_id),
            )


# ===================================================================
# SESSIONS / HISTORY
# ===================================================================

@router.get("/sessions")
def list_sessions(user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, session_key, filename, speaker, status, processing_stage, "
            "total_segments, total_corrections, created_at, completed_at "
            "FROM transcription_sessions "
            "WHERE user_id = %s "
            "ORDER BY created_at DESC",
            (user["id"],),
        )
        rows = cur.fetchall()
    return {"sessions": [dict(r) for r in rows]}


@router.get("/sessions/{session_key}")
def get_session(session_key: str, user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, session_key, filename, speaker, status, processing_stage, total_segments, total_corrections, "
            "result_json, error_message, created_at, completed_at "
            "FROM transcription_sessions "
            "WHERE session_key = %s AND user_id = %s",
            (session_key, user["id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    out = dict(row)
    # Ensure result_json is parsed (PG may return it as a string)
    if isinstance(out.get("result_json"), str):
        out["result_json"] = json.loads(out["result_json"])
    return out


@router.delete("/sessions/{session_key}")
def delete_session(session_key: str, user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM transcription_sessions WHERE session_key = %s AND user_id = %s",
            (session_key, user["id"]),
        )
    return {"status": "deleted"}


@router.post("/sessions/{session_key}/correct-segment")
def correct_segment(
    session_key: str,
    payload: dict,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Human-guided Gemini correction for a single segment.
    Payload: { "segment_index": int, "instruction": str }
    """
    seg_idx = payload.get("segment_index")
    instruction = payload.get("instruction", "").strip()
    if seg_idx is None or not instruction:
        raise HTTPException(status_code=422, detail="segment_index and instruction are required")

    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, result_json FROM transcription_sessions "
            "WHERE session_key = %s AND user_id = %s",
            (session_key, user["id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    result = row["result_json"]
    if isinstance(result, str):
        result = json.loads(result)

    segments = result.get("segments", [])
    if seg_idx < 0 or seg_idx >= len(segments):
        raise HTTPException(status_code=422, detail="segment_index out of range")

    seg = segments[seg_idx]
    original_text = seg["refined_text"]

    # Call Gemini with user instruction
    gemini_result = correct_segment_with_instruction(original_text, instruction)

    # Check for API errors (e.g., rate limit)
    if "error" in gemini_result:
        raise HTTPException(status_code=503, detail=gemini_result["error"])

    corrected_text = gemini_result.get("corrected_text", original_text)
    changes = gemini_result.get("changes", [])

    if corrected_text != original_text and changes:
        # Update the segment
        seg["refined_text"] = corrected_text
        for change in changes:
            orig = change.get("original", "")
            corr = change.get("corrected", "")
            if orig and corr:
                seg.setdefault("corrections", []).append({
                    "original": orig,
                    "corrected": corr,
                    "source": "gemini",
                })
                # Reverse detection: handle conflicting lexicon rules
                try:
                    with get_db() as conn:
                        # Delete probationary rules whose correct_phrase matches
                        # the word the human says is wrong (no second chance)
                        del_result = conn.execute(
                            "DELETE FROM lexicon WHERE correct_phrase ILIKE %s "
                            "AND is_permanent = FALSE",
                            (orig,),
                        )
                        # Demote permanent rules whose correct_phrase matches
                        # the word the human says is wrong (trust erosion)
                        demote_result = conn.execute(
                            "UPDATE lexicon SET is_permanent = FALSE, "
                            "context_hint = COALESCE(context_hint, '') || ' [demoted by human override]' "
                            "WHERE correct_phrase ILIKE %s "
                            "AND is_permanent = TRUE",
                            (orig,),
                        )
                except Exception as e:
                    # Log the error for debugging — trust erosion bugs are critical
                    import logging
                    logging.getLogger(__name__).warning(
                        "Trust erosion failed for '%s' → '%s': %s", orig, corr, e
                    )
                # Auto-add new correction as probationary (must earn permanent)
                try:
                    with get_db() as conn:
                        conn.execute(
                            "INSERT INTO lexicon (wrong_phrase, correct_phrase, context_hint, is_permanent) "
                            "VALUES (%s, %s, %s, FALSE) ON CONFLICT (wrong_phrase) DO UPDATE "
                            "SET correct_phrase = EXCLUDED.correct_phrase, "
                            "context_hint = EXCLUDED.context_hint, is_permanent = FALSE",
                            (orig.lower(), corr, "human-guided Gemini correction (probationary)"),
                        )
                except Exception:
                    pass
                # Log the correction
                _logger.log(orig, corr, CorrectionSource.GEMINI)

        # Apply N-gram correction feedback: penalize original, reward corrected
        # This helps clean the N-gram corpus of patterns from uncorrected Whisper errors
        try:
            feedback = NGramAuditor.apply_correction_feedback(original_text, corrected_text)
            import logging
            logging.getLogger(__name__).info(
                "N-gram feedback for segment %d: penalized=%d, rewarded=%d",
                seg_idx, feedback["penalized"], feedback["rewarded"],
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("N-gram feedback failed: %s", e)

        # Persist updated result_json
        total_new = sum(1 for c in changes if c.get("original") and c.get("corrected"))
        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions SET result_json = %s, "
                "total_corrections = total_corrections + %s WHERE id = %s",
                (json.dumps(result), total_new, row["id"]),
            )

        # Flush lexicon cache
        from app.cache import cache_delete_pattern
        cache_delete_pattern("lexicon:*")

    return {
        "corrected_text": corrected_text,
        "changes": changes,
        "segment_index": seg_idx,
    }


@router.get("/sessions/{session_key}/download")
def download_session(
    session_key: str,
    format: str = Query("timestamped", description="transcript | timestamped | results"),
    user: dict = Depends(get_current_user),
) -> PlainTextResponse:
    """
    Download transcript in one of three formats:
    - transcript: plain text only
    - timestamped: text with [start - end] timestamps
    - results: timestamped + correction annotations
    """
    with get_db() as conn:
        cur = conn.execute(
            "SELECT filename, result_json FROM transcription_sessions "
            "WHERE session_key = %s AND user_id = %s",
            (session_key, user["id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    result = row["result_json"]
    if isinstance(result, str):
        result = json.loads(result)

    segments = result.get("segments", [])
    lines: list[str] = []

    for seg in segments:
        start = seg["start"]
        end = seg["end"]

        if format == "transcript":
            lines.append(seg["refined_text"])
        elif format == "timestamped":
            lines.append(f"[{_fmt_ts(start)} - {_fmt_ts(end)}]  {seg['refined_text']}")
        elif format == "results":
            lines.append(f"[{_fmt_ts(start)} - {_fmt_ts(end)}]  {seg['refined_text']}")
            if seg.get("corrections"):
                for c in seg["corrections"]:
                    lines.append(
                        f"    ✓ [{c['source']}] \"{c['original']}\" → \"{c['corrected']}\""
                    )
            if seg["original_text"] != seg["refined_text"]:
                lines.append(f"    (original: {seg['original_text']})")
        else:
            raise HTTPException(status_code=400, detail="format must be: transcript | timestamped | results")

    basename = row["filename"].rsplit(".", 1)[0] if "." in row["filename"] else row["filename"]
    content = "\n".join(lines)
    return PlainTextResponse(
        content=content,
        headers={
            "Content-Disposition": f'attachment; filename="{basename}_{format}.txt"',
        },
    )


def _fmt_ts(seconds: float) -> str:
    m = int(seconds) // 60
    s = int(seconds) % 60
    ms = int((seconds % 1) * 10)
    return f"{m}:{s:02d}.{ms}"


# ===================================================================
# LEXICON CRUD (protected)
# ===================================================================

@router.get("/lexicon")
def list_lexicon_rules(_user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, wrong_phrase, correct_phrase, context_hint, "
            "anchor_mode, is_permanent, created_at "
            "FROM lexicon ORDER BY id"
        )
        rows = cur.fetchall()
    return {"rules": [dict(r) for r in rows]}


@router.post("/lexicon", status_code=201)
def add_lexicon_rule(
    rule: LexiconRule,
    _user: dict = Depends(get_current_user),
) -> dict:
    LexiconChecker.add_rule(
        wrong_phrase=rule.wrong_phrase,
        correct_phrase=rule.correct_phrase,
        context_hint=rule.context_hint,
        anchor_mode=rule.anchor_mode,
    )
    return {"status": "created", "wrong_phrase": rule.wrong_phrase}


@router.put("/lexicon/{rule_id}")
def update_lexicon_rule(
    rule_id: int,
    rule: LexiconRule,
    _user: dict = Depends(get_current_user),
) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE lexicon SET wrong_phrase = %s, correct_phrase = %s, "
            "context_hint = %s, anchor_mode = %s "
            "WHERE id = %s RETURNING id",
            (rule.wrong_phrase, rule.correct_phrase, rule.context_hint,
             rule.anchor_mode.value if rule.anchor_mode else None, rule_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("lexicon:*")
    return {"status": "updated", "id": rule_id}


@router.delete("/lexicon/{rule_id}")
def ban_lexicon_rule(
    rule_id: int,
    reason: str = Query("", description="Reason for banning"),
    _user: dict = Depends(get_current_user),
) -> dict:
    """Delete a lexicon rule AND add it to the blocklist so it can never be re-learned."""
    with get_db() as conn:
        # Fetch the rule first so we can blocklist it
        cur = conn.execute(
            "SELECT wrong_phrase, correct_phrase FROM lexicon WHERE id = %s",
            (rule_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")

        # Add to blocklist
        conn.execute(
            "INSERT INTO lexicon_blocklist (wrong_phrase, correct_phrase, reason, banned_by) "
            "VALUES (%s, %s, %s, 'manual') "
            "ON CONFLICT (wrong_phrase, correct_phrase) DO NOTHING",
            (row["wrong_phrase"], row["correct_phrase"], reason or None),
        )

        # Delete the rule
        conn.execute("DELETE FROM lexicon WHERE id = %s", (rule_id,))

    from app.cache import cache_delete_pattern
    cache_delete_pattern("lexicon:*")
    return {"status": "banned", "wrong_phrase": row["wrong_phrase"], "correct_phrase": row["correct_phrase"]}


# ===================================================================
# BLOCKLIST
# ===================================================================

@router.get("/blocklist")
def list_blocklist(
    search: str = "",
    _user: dict = Depends(get_current_user),
) -> dict:
    """Return all blocklisted correction pairs."""
    with get_db() as conn:
        if search:
            cur = conn.execute(
                "SELECT id, wrong_phrase, correct_phrase, reason, banned_by, created_at "
                "FROM lexicon_blocklist "
                "WHERE wrong_phrase ILIKE %s OR correct_phrase ILIKE %s "
                "ORDER BY created_at DESC",
                (f"%{search}%", f"%{search}%"),
            )
        else:
            cur = conn.execute(
                "SELECT id, wrong_phrase, correct_phrase, reason, banned_by, created_at "
                "FROM lexicon_blocklist ORDER BY created_at DESC"
            )
        rows = cur.fetchall()
    return {"rules": [dict(r) for r in rows]}


@router.post("/blocklist", status_code=201)
def add_blocklist_rule(
    payload: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Manually add a correction pair to the blocklist."""
    wrong = payload.get("wrong_phrase", "").strip().lower()
    correct = payload.get("correct_phrase", "").strip()
    reason = payload.get("reason", "")
    if not wrong or not correct:
        raise HTTPException(status_code=422, detail="wrong_phrase and correct_phrase required")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO lexicon_blocklist (wrong_phrase, correct_phrase, reason, banned_by) "
            "VALUES (%s, %s, %s, 'manual') "
            "ON CONFLICT (wrong_phrase, correct_phrase) DO NOTHING",
            (wrong, correct, reason or None),
        )
    return {"status": "created", "wrong_phrase": wrong, "correct_phrase": correct}


@router.delete("/blocklist/{blocklist_id}")
def unban_blocklist_rule(
    blocklist_id: int,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Remove a correction pair from the blocklist (unban)."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM lexicon_blocklist WHERE id = %s RETURNING id", (blocklist_id,)
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Blocklist entry not found")
    return {"status": "unbanned"}


# ===================================================================
# DOWNVOTE CORRECTION (from session detail)
# ===================================================================

@router.post("/corrections/downvote")
def downvote_correction(
    payload: dict,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Downvote a correction — blocklist it and optionally demote from lexicon.

    Payload:
        original: str - the wrong phrase
        corrected: str - the corrected phrase
        action: "blocklist" | "demote" | "both"
        reason: str (optional) - why it's being downvoted
    """
    original = payload.get("original", "").strip()
    corrected = payload.get("corrected", "").strip()
    action = payload.get("action", "blocklist")
    reason = payload.get("reason", "User downvoted from session detail")

    if not original or not corrected:
        raise HTTPException(status_code=400, detail="original and corrected are required")

    results = {"blocklisted": False, "demoted": False, "deleted": False}

    with get_db() as conn:
        # Always blocklist to prevent re-learning
        if action in ("blocklist", "both"):
            try:
                conn.execute(
                    "INSERT INTO lexicon_blocklist (wrong_phrase, correct_phrase, reason, banned_by) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (wrong_phrase, correct_phrase) DO NOTHING",
                    (original, corrected, reason, user["username"]),
                )
                results["blocklisted"] = True
            except Exception:
                pass  # Already blocklisted

        # Find matching lexicon rule
        cur = conn.execute(
            "SELECT id, is_permanent FROM lexicon "
            "WHERE wrong_phrase = %s AND correct_phrase = %s",
            (original, corrected),
        )
        rule = cur.fetchone()

        if rule:
            if action == "demote" or action == "both":
                if rule["is_permanent"]:
                    # Demote to probationary
                    conn.execute(
                        "UPDATE lexicon SET is_permanent = FALSE WHERE id = %s",
                        (rule["id"],),
                    )
                    results["demoted"] = True
                else:
                    # Already probationary — delete it
                    conn.execute("DELETE FROM lexicon WHERE id = %s", (rule["id"],))
                    results["deleted"] = True

        # Invalidate lexicon cache
        from app.cache import cache_delete_pattern
        cache_delete_pattern("lexicon:")

    return {"status": "ok", **results}


@router.patch("/lexicon/{rule_id}/promote")
def promote_lexicon_rule(
    rule_id: int,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Manually promote a probationary lexicon rule to permanent."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE lexicon SET is_permanent = TRUE, "
            "context_hint = COALESCE(context_hint, '') || ' [manually promoted]' "
            "WHERE id = %s AND is_permanent = FALSE RETURNING id",
            (rule_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found or already permanent")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("lexicon:*")
    return {"status": "promoted", "id": rule_id}


@router.patch("/lexicon/{rule_id}/demote")
def demote_lexicon_rule(
    rule_id: int,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Manually demote a permanent lexicon rule to probationary."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE lexicon SET is_permanent = FALSE, "
            "context_hint = COALESCE(context_hint, '') || ' [manually demoted]' "
            "WHERE id = %s AND is_permanent = TRUE RETURNING id",
            (rule_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found or already probationary")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("lexicon:*")
    return {"status": "demoted", "id": rule_id}


# ===================================================================
# N-GRAM
# ===================================================================

@router.get("/ngram")
def list_ngrams(
    search: str = "",
    limit: int = 200,
    offset: int = 0,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Return top N-grams sorted by frequency descending."""
    with get_db() as conn:
        if search:
            rows = conn.execute(
                """SELECT id, word1, word2, word3, frequency
                   FROM ngram_frequency
                   WHERE word1 ILIKE %s OR word2 ILIKE %s OR word3 ILIKE %s
                   ORDER BY frequency DESC
                   LIMIT %s OFFSET %s""",
                (f"%{search}%", f"%{search}%", f"%{search}%", limit, offset),
            ).fetchall()
            total = conn.execute(
                """SELECT COUNT(*) AS cnt FROM ngram_frequency
                   WHERE word1 ILIKE %s OR word2 ILIKE %s OR word3 ILIKE %s""",
                (f"%{search}%", f"%{search}%", f"%{search}%"),
            ).fetchone()["cnt"]
        else:
            rows = conn.execute(
                """SELECT id, word1, word2, word3, frequency
                   FROM ngram_frequency
                   ORDER BY frequency DESC
                   LIMIT %s OFFSET %s""",
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS cnt FROM ngram_frequency").fetchone()["cnt"]
    return {
        "total": total,
        "ngrams": [
            {"id": r["id"], "word1": r["word1"], "word2": r["word2"], "word3": r["word3"], "frequency": r["frequency"]}
            for r in rows
        ],
    }


@router.post("/ngram/ingest")
def ingest_ngrams(
    payload: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    texts = payload.get("texts")
    if not texts or not isinstance(texts, list):
        raise HTTPException(status_code=422, detail="'texts' must be a list of strings")
    count = NGramAuditor.bulk_ingest(texts)
    return {"trigrams_processed": count}


@router.get("/ngram/lookup")
def lookup_ngram(
    w1: str, w2: str, w3: str,
    _user: dict = Depends(get_current_user),
) -> dict:
    freq = NGramAuditor.lookup_frequency(w1, w2, w3)
    return {"trigram": [w1, w2, w3], "frequency": freq}


@router.delete("/ngram/{ngram_id}")
def delete_ngram(ngram_id: int, _user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        conn.execute("DELETE FROM ngram_frequency WHERE id = %s", (ngram_id,))
    return {"status": "deleted"}


@router.patch("/ngram/{ngram_id}")
def update_ngram_frequency(
    ngram_id: int,
    payload: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    freq = payload.get("frequency")
    if freq is None or not isinstance(freq, int) or freq < 0:
        raise HTTPException(status_code=422, detail="'frequency' must be a non-negative integer")
    with get_db() as conn:
        conn.execute(
            "UPDATE ngram_frequency SET frequency = %s WHERE id = %s",
            (freq, ngram_id),
        )
    return {"status": "updated"}


# ===================================================================
# SELF-LEARNING / PROMOTION
# ===================================================================

@router.get("/corrections/candidates")
def promotion_candidates(_user: dict = Depends(get_current_user)) -> dict:
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


@router.post("/corrections/promote")
async def auto_promote(user: dict = Depends(get_current_user)) -> dict:
    """
    Trigger the self-learning promotion loop:
    1. Fetch all corrections that reached Rule-of-5
    2. Send each to Gemini 2.5 Flash for audit
    3. If approved, promote to permanent lexicon rule
    """
    from app.core.gemini_auditor import audit_candidate
    import asyncio

    candidates = _logger.get_promotion_candidates()
    if not candidates:
        return {"promoted": 0, "rejected": 0, "results": [], "message": "No candidates ready for promotion"}

    results = []
    promoted = 0
    rejected = 0

    for i, cand in enumerate(candidates):
        if i > 0:
            await asyncio.sleep(4)  # rate-limit: 4s between Gemini calls (free tier: 15 RPM)
        audit = await audit_candidate(
            original=cand.original_phrase,
            corrected=cand.corrected_phrase,
            source=cand.source,
            occurrences=cand.occurrences,
        )

        if audit.approved:
            # Promote: add to permanent lexicon
            LexiconChecker.add_rule(
                wrong_phrase=cand.original_phrase,
                correct_phrase=cand.corrected_phrase,
                context_hint=f"Auto-promoted from {cand.source} (seen {cand.occurrences}x)",
            )
            _logger.mark_promoted(cand.original_phrase, cand.corrected_phrase)
            promoted += 1
        else:
            rejected += 1

        results.append({
            "original": audit.original,
            "corrected": audit.corrected,
            "approved": audit.approved,
            "reason": audit.reason,
        })

    return {
        "promoted": promoted,
        "rejected": rejected,
        "results": results,
    }


@router.get("/corrections/log")
def correction_log(_user: dict = Depends(get_current_user)) -> dict:
    """Return the full correction log for visibility."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT original_phrase, corrected_phrase, source, occurrences, "
            "promoted, last_seen_at "
            "FROM correction_log "
            "ORDER BY occurrences DESC "
            "LIMIT 500"
        )
        rows = cur.fetchall()
    return {"entries": [dict(r) for r in rows], "promotion_threshold": 3}


# ===================================================================
# SEMANTIC ANCHORS
# ===================================================================

@router.get("/anchors")
def list_anchors(
    search: str = "",
    mode: str = "",
    _user: dict = Depends(get_current_user),
) -> dict:
    """Return all semantic anchor patterns."""
    with get_db() as conn:
        clauses = []
        params: list = []
        if search:
            clauses.append("(label ILIKE %s OR pattern ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        if mode:
            clauses.append("mode = %s")
            params.append(mode)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cur = conn.execute(
            f"SELECT id, mode, label, pattern, weight, is_active, source, created_at, updated_at "
            f"FROM semantic_anchors {where} ORDER BY mode, label",
            params,
        )
        rows = cur.fetchall()
    return {"anchors": [dict(r) for r in rows]}


@router.post("/anchors", status_code=201)
def add_anchor(
    payload: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Add a new semantic anchor pattern."""
    mode = payload.get("mode", "").strip()
    label = payload.get("label", "").strip()
    pattern = payload.get("pattern", "").strip()
    weight = payload.get("weight", 1)
    if not mode or not label or not pattern:
        raise HTTPException(status_code=422, detail="mode, label, and pattern are required")
    # Validate regex
    import re as _re
    try:
        _re.compile(pattern)
    except _re.error as e:
        raise HTTPException(status_code=422, detail=f"Invalid regex: {e}")
    with get_db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO semantic_anchors (mode, label, pattern, weight, source) "
                "VALUES (%s, %s, %s, %s, 'manual') RETURNING id",
                (mode, label, pattern, weight),
            )
            row = cur.fetchone()
        except Exception:
            raise HTTPException(status_code=409, detail="Anchor with this mode+label already exists")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("anchors:")
    return {"status": "created", "id": row["id"]}


@router.put("/anchors/{anchor_id}")
def update_anchor(
    anchor_id: int,
    payload: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Update a semantic anchor pattern."""
    mode = payload.get("mode", "").strip()
    label = payload.get("label", "").strip()
    pattern = payload.get("pattern", "").strip()
    weight = payload.get("weight", 1)
    is_active = payload.get("is_active", True)
    if not mode or not label or not pattern:
        raise HTTPException(status_code=422, detail="mode, label, and pattern are required")
    import re as _re
    try:
        _re.compile(pattern)
    except _re.error as e:
        raise HTTPException(status_code=422, detail=f"Invalid regex: {e}")
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE semantic_anchors SET mode = %s, label = %s, pattern = %s, "
            "weight = %s, is_active = %s, updated_at = now() "
            "WHERE id = %s RETURNING id",
            (mode, label, pattern, weight, is_active, anchor_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Anchor not found")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("anchors:")
    return {"status": "updated", "id": anchor_id}


@router.delete("/anchors/{anchor_id}")
def delete_anchor(
    anchor_id: int,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Delete a semantic anchor pattern."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM semantic_anchors WHERE id = %s RETURNING id",
            (anchor_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Anchor not found")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("anchors:")
    return {"status": "deleted"}


@router.patch("/anchors/{anchor_id}/toggle")
def toggle_anchor(
    anchor_id: int,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Toggle an anchor pattern on/off."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE semantic_anchors SET is_active = NOT is_active, updated_at = now() "
            "WHERE id = %s RETURNING id, is_active",
            (anchor_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Anchor not found")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("anchors:")
    return {"status": "toggled", "id": anchor_id, "is_active": row["is_active"]}


# ===================================================================
# ANCHOR OVERRIDES (segment mode corrections)
# ===================================================================

@router.post("/sessions/{session_key}/override-anchor")
def override_segment_anchor(
    session_key: str,
    payload: dict,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Override the anchor mode for a specific segment.
    Payload: { "segment_index": int, "corrected_mode": str }
    Updates the session result_json and logs the override for learning.
    """
    seg_idx = payload.get("segment_index")
    corrected_mode = payload.get("corrected_mode", "").strip()
    if seg_idx is None or not corrected_mode:
        raise HTTPException(status_code=422, detail="segment_index and corrected_mode are required")

    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, result_json FROM transcription_sessions "
            "WHERE session_key = %s AND user_id = %s",
            (session_key, user["id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    result = row["result_json"]
    if isinstance(result, str):
        result = json.loads(result)

    segments = result.get("segments", [])
    if seg_idx < 0 or seg_idx >= len(segments):
        raise HTTPException(status_code=422, detail="segment_index out of range")

    seg = segments[seg_idx]
    original_mode = seg.get("anchor_mode", "general")
    segment_text = seg.get("refined_text", seg.get("original_text", ""))

    # Update the segment's anchor mode in result_json
    seg["anchor_mode"] = corrected_mode

    with get_db() as conn:
        # Persist updated result_json
        conn.execute(
            "UPDATE transcription_sessions SET result_json = %s WHERE id = %s",
            (json.dumps(result), row["id"]),
        )
        # Log the override for learning
        conn.execute(
            "INSERT INTO anchor_overrides "
            "(session_id, segment_index, segment_text, original_mode, corrected_mode, source) "
            "VALUES (%s, %s, %s, %s, %s, 'manual')",
            (row["id"], seg_idx, segment_text[:500], original_mode, corrected_mode),
        )

    return {
        "status": "overridden",
        "segment_index": seg_idx,
        "original_mode": original_mode,
        "corrected_mode": corrected_mode,
    }


@router.get("/anchor-overrides")
def list_anchor_overrides(_user: dict = Depends(get_current_user)) -> dict:
    """Return all anchor overrides for analytics."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT ao.id, ao.segment_text, ao.original_mode, ao.corrected_mode, "
            "ao.source, ao.created_at, ts.filename "
            "FROM anchor_overrides ao "
            "JOIN transcription_sessions ts ON ts.id = ao.session_id "
            "ORDER BY ao.created_at DESC LIMIT 200"
        )
        rows = cur.fetchall()
    return {"overrides": [dict(r) for r in rows]}


# ===================================================================
# DOMAIN GLOSSARY
# ===================================================================

@router.get("/glossary")
def list_glossary(
    mode: Optional[str] = None,
    search: Optional[str] = None,
    _user: dict = Depends(get_current_user),
) -> dict:
    """List domain glossary terms, optionally filtered by mode or search."""
    conditions: list[str] = []
    params: list[str] = []
    if mode:
        conditions.append("anchor_mode = %s")
        params.append(mode)
    if search:
        conditions.append("term ILIKE %s")
        params.append(f"%{search}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with get_db() as conn:
        cur = conn.execute(
            f"SELECT * FROM domain_glossary {where} ORDER BY anchor_mode, term",
            params,
        )
        rows = cur.fetchall()
    return {"terms": [dict(r) for r in rows]}


@router.post("/glossary", status_code=201)
def add_glossary_term(
    payload: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Add a new domain glossary term."""
    anchor_mode = (payload.get("anchor_mode") or "").strip().lower()
    term = (payload.get("term") or "").strip()
    if not anchor_mode or not term:
        raise HTTPException(400, "anchor_mode and term are required")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO domain_glossary (anchor_mode, term) "
            "VALUES (%s, %s) ON CONFLICT (anchor_mode, term) DO NOTHING RETURNING *",
            (anchor_mode, term),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(409, "Term already exists for this mode")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("glossary:")
    return {"term": dict(row)}


@router.put("/glossary/{term_id}")
def update_glossary_term(
    term_id: int,
    payload: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Update a glossary term."""
    anchor_mode = (payload.get("anchor_mode") or "").strip().lower()
    term = (payload.get("term") or "").strip()
    if not anchor_mode or not term:
        raise HTTPException(400, "anchor_mode and term are required")
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE domain_glossary SET anchor_mode = %s, term = %s WHERE id = %s RETURNING *",
            (anchor_mode, term, term_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Term not found")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("glossary:")
    return {"term": dict(row)}


@router.delete("/glossary/{term_id}")
def delete_glossary_term(
    term_id: int,
    _user: dict = Depends(get_current_user),
) -> dict:
    """Delete a glossary term."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM domain_glossary WHERE id = %s RETURNING id", (term_id,)
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Term not found")
    from app.cache import cache_delete_pattern
    cache_delete_pattern("glossary:")
    return {"deleted": True}


# ===================================================================
# HEALTH (public)
# ===================================================================

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "phoenix-3.0-refiner"}
