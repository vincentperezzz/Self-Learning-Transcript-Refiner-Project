"""PostgreSQL database layer – Table A (Lexicon), Table B (N-Gram), Correction Log."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL

# ---------------------------------------------------------------------------
# Connection pool  (created lazily on first use)
# ---------------------------------------------------------------------------

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
        )
    return _pool


@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    """Yield a connection from the pool; auto-commit on success, rollback on error."""
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    """Shut down the connection pool (called at app shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- Table A: Permanent Lexicon / Golden Rules
CREATE TABLE IF NOT EXISTS lexicon (
    id              SERIAL PRIMARY KEY,
    wrong_phrase    TEXT    NOT NULL,
    correct_phrase  TEXT    NOT NULL,
    context_hint    TEXT,
    anchor_mode     TEXT,
    is_permanent    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(wrong_phrase, correct_phrase)
);

-- Table B: N-Gram Frequency / Word Chains (trigrams)
CREATE TABLE IF NOT EXISTS ngram_frequency (
    id        SERIAL PRIMARY KEY,
    word1     TEXT    NOT NULL,
    word2     TEXT    NOT NULL,
    word3     TEXT    NOT NULL,
    frequency INTEGER NOT NULL DEFAULT 1,
    UNIQUE(word1, word2, word3)
);

-- Correction Log (self-learning loop)
CREATE TABLE IF NOT EXISTS correction_log (
    id                SERIAL PRIMARY KEY,
    original_phrase   TEXT    NOT NULL,
    corrected_phrase  TEXT    NOT NULL,
    source            TEXT    NOT NULL,
    occurrences       INTEGER NOT NULL DEFAULT 1,
    promoted          BOOLEAN NOT NULL DEFAULT FALSE,
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(original_phrase, corrected_phrase)
);

-- Users
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Transcription Sessions
CREATE TABLE IF NOT EXISTS transcription_sessions (
    id                SERIAL PRIMARY KEY,
    session_key       TEXT    UNIQUE NOT NULL,
    filename          TEXT    NOT NULL,
    speaker           TEXT,
    user_id           INTEGER REFERENCES users(id),
    status            TEXT    NOT NULL DEFAULT 'processing',
    processing_stage  TEXT    DEFAULT 'whisper',
    total_segments    INTEGER NOT NULL DEFAULT 0,
    total_corrections INTEGER NOT NULL DEFAULT 0,
    result_json       JSONB,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);

-- Lexicon Blocklist (permanently banned correction pairs)
CREATE TABLE IF NOT EXISTS lexicon_blocklist (
    id              SERIAL PRIMARY KEY,
    wrong_phrase    TEXT    NOT NULL,
    correct_phrase  TEXT    NOT NULL,
    reason          TEXT,
    banned_by       TEXT    NOT NULL DEFAULT 'manual',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(wrong_phrase, correct_phrase)
);

-- Semantic Anchor Patterns (DB-backed, manageable via UI)
CREATE TABLE IF NOT EXISTS semantic_anchors (
    id          SERIAL PRIMARY KEY,
    mode        TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    pattern     TEXT    NOT NULL,
    weight      INTEGER NOT NULL DEFAULT 1 CHECK (weight BETWEEN 1 AND 5),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    source      TEXT    NOT NULL DEFAULT 'seed',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(mode, label)
);

-- Anchor Override Log (user or Gemini corrections for learning)
CREATE TABLE IF NOT EXISTS anchor_overrides (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER REFERENCES transcription_sessions(id) ON DELETE CASCADE,
    segment_index   INTEGER NOT NULL,
    segment_text    TEXT    NOT NULL,
    original_mode   TEXT    NOT NULL,
    corrected_mode  TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT 'manual',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domain_glossary (
    id              SERIAL PRIMARY KEY,
    anchor_mode     TEXT    NOT NULL,
    term            TEXT    NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(anchor_mode, term)
);

CREATE INDEX IF NOT EXISTS idx_ngram_words ON ngram_frequency(word1, word2, word3);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lexicon_wrong ON lexicon(wrong_phrase);
CREATE INDEX IF NOT EXISTS idx_correction_log_occ ON correction_log(occurrences);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON transcription_sessions(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_key ON transcription_sessions(session_key);
CREATE INDEX IF NOT EXISTS idx_anchor_patterns_mode ON semantic_anchors(mode);
CREATE INDEX IF NOT EXISTS idx_anchor_overrides_session ON anchor_overrides(session_id);
CREATE INDEX IF NOT EXISTS idx_domain_glossary_mode ON domain_glossary(anchor_mode);

-- Gemini API Call Logs (for accurate rate limit tracking)
CREATE TABLE IF NOT EXISTS gemini_api_logs (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER REFERENCES users(id),
    session_id        INTEGER REFERENCES transcription_sessions(id) ON DELETE SET NULL,
    call_type         TEXT    NOT NULL DEFAULT 'correction',  -- 'correction', 'audit', 'validation'
    model             TEXT    NOT NULL,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0,
    success           BOOLEAN NOT NULL DEFAULT TRUE,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gemini_logs_user ON gemini_api_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_gemini_logs_created ON gemini_api_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_gemini_logs_user_created ON gemini_api_logs(user_id, created_at);
"""


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.execute(_SCHEMA_SQL)
        # Migration: add status + error_message columns to existing installations
        conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'transcription_sessions' AND column_name = 'status'
                ) THEN
                    ALTER TABLE transcription_sessions
                        ADD COLUMN status TEXT NOT NULL DEFAULT 'completed',
                        ADD COLUMN error_message TEXT;
                END IF;
            END $$;
        """)
        # Migration: add processing_stage column
        conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'transcription_sessions' AND column_name = 'processing_stage'
                ) THEN
                    ALTER TABLE transcription_sessions
                        ADD COLUMN processing_stage TEXT DEFAULT 'whisper';
                END IF;
            END $$;
        """)
        # Migration: add completed_at column
        conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'transcription_sessions' AND column_name = 'completed_at'
                ) THEN
                    ALTER TABLE transcription_sessions
                        ADD COLUMN completed_at TIMESTAMPTZ;
                END IF;
            END $$;
        """)
        # Migration: add token tracking columns
        conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'transcription_sessions' AND column_name = 'tokens_used'
                ) THEN
                    ALTER TABLE transcription_sessions
                        ADD COLUMN tokens_used INTEGER NOT NULL DEFAULT 0,
                        ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0;
                END IF;
            END $$;
        """)
