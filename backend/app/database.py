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
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ngram_words ON ngram_frequency(word1, word2, word3);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lexicon_wrong ON lexicon(wrong_phrase);
CREATE INDEX IF NOT EXISTS idx_correction_log_occ ON correction_log(occurrences);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON transcription_sessions(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_key ON transcription_sessions(session_key);
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
