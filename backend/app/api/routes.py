"""Phoenix 3.0 API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
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
from app.core.whisper_client import transcribe_audio
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

@router.post("/transcribe", response_model=RefinementResponse)
async def transcribe_and_refine(
    file: UploadFile = File(...),
    speaker: Optional[str] = Query(None, description="agent or client"),
    language: Optional[str] = Query(None, description="e.g. en, tl"),
    user: dict = Depends(get_current_user),
) -> RefinementResponse:
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
            detail=f"Groq Whisper transcription failed: {exc}",
        )

    request = RefinementRequest(segments=segments, speaker=speaker)
    result = _engine.refine(request)

    # Save session to DB
    _save_session(
        filename=file.filename or "audio.wav",
        speaker=speaker,
        user_id=user["id"],
        result=result,
    )

    return result


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
            "SELECT id, filename, speaker, total_segments, total_corrections, created_at "
            "FROM transcription_sessions "
            "WHERE user_id = %s "
            "ORDER BY created_at DESC",
            (user["id"],),
        )
        rows = cur.fetchall()
    return {"sessions": [dict(r) for r in rows]}


@router.get("/sessions/{session_id}")
def get_session(session_id: int, user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, filename, speaker, total_segments, total_corrections, "
            "result_json, created_at "
            "FROM transcription_sessions "
            "WHERE id = %s AND user_id = %s",
            (session_id, user["id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return dict(row)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, user: dict = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM transcription_sessions WHERE id = %s AND user_id = %s",
            (session_id, user["id"]),
        )
    return {"status": "deleted"}


def _save_session(
    filename: str,
    speaker: Optional[str],
    user_id: int,
    result: RefinementResponse,
) -> None:
    result_dict = result.model_dump(mode="json")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO transcription_sessions "
            "(filename, speaker, user_id, total_segments, total_corrections, result_json) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                filename,
                speaker,
                user_id,
                len(result.segments),
                result.total_corrections,
                json.dumps(result_dict),
            ),
        )


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


# ===================================================================
# HEALTH (public)
# ===================================================================

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "phoenix-3.0-refiner"}
