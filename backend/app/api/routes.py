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
from app.core.lexicon import LexiconChecker
from app.core.ngram_auditor import NGramAuditor
from app.core.whisper_client import transcribe_audio_sync
from app.database import get_db
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
    try:
        log.info("BG task started for session %s", session_id)
        segments = transcribe_audio_sync(
            audio_bytes=audio_bytes,
            filename=filename,
            language=language,
        )

        request = RefinementRequest(segments=segments, speaker=speaker)
        result = _engine.refine(request)
        result_dict = result.model_dump(mode="json")

        with get_db() as conn:
            conn.execute(
                "UPDATE transcription_sessions "
                "SET status = 'completed', total_segments = %s, "
                "total_corrections = %s, result_json = %s "
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
# SESSIONS / HISTORY
# ===================================================================

@router.get("/sessions")
def list_sessions(user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, session_key, filename, speaker, status, total_segments, total_corrections, created_at "
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
            "SELECT id, session_key, filename, speaker, status, total_segments, total_corrections, "
            "result_json, error_message, created_at "
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
def delete_lexicon_rule(
    rule_id: int,
    _user: dict = Depends(get_current_user),
) -> dict:
    with get_db() as conn:
        conn.execute("DELETE FROM lexicon WHERE id = %s", (rule_id,))
    from app.cache import cache_delete_pattern
    cache_delete_pattern("lexicon:*")
    return {"status": "deleted"}


# ===================================================================
# N-GRAM
# ===================================================================

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

    candidates = _logger.get_promotion_candidates()
    if not candidates:
        return {"promoted": 0, "rejected": 0, "results": [], "message": "No candidates ready for promotion"}

    results = []
    promoted = 0
    rejected = 0

    for cand in candidates:
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
            "LIMIT 100"
        )
        rows = cur.fetchall()
    return {"entries": [dict(r) for r in rows]}


# ===================================================================
# HEALTH (public)
# ===================================================================

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "phoenix-3.0-refiner"}
