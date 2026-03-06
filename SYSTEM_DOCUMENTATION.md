# Phoenix 3.0 – Self-Learning Transcript Refiner

## System Overview

Phoenix 3.0 is a **deterministic-first transcript correction system** that refines Whisper-generated transcripts using a 3-layer correction hierarchy. Rather than relying on a single AI model, it applies targeted, explainable corrections where each fix has a clear source and rationale.

### How Refinement Works

When you upload an audio file, the system:

1. **Transcribes** the audio via the Groq API (Whisper `large-v3-turbo` model)
2. **Extracts** per-word confidence scores and segment timestamps
3. **Detects** the domain context (Banking, Collections, Verification) using Semantic Anchors
4. **Corrects** the transcript through 3 sequential layers
5. **Post-processes** (currency normalization, double-word dedup)
6. **Learns** from each correction to improve future results

---

## The 3-Layer Correction Hierarchy

Each transcript segment passes through **all three layers in sequence**. Corrections from earlier layers feed into later ones.

### Layer 1: Lexicon (Permanent Rules)

**Source badge on UI:** `lexicon` (green)

The lexicon is a database table of **known Whisper mistakes** and their correct forms. Think of it as a curated dictionary of errors.

**How it works:**
- Whisper consistently misrecognizes certain words and phrases (e.g., "birth date" → "birthdate", "SP Madrid" → correct casing)
- The lexicon stores these as `wrong_phrase → correct_phrase` pairs
- Rules can be scoped to a specific domain (e.g., only apply in BANKING contexts) or be universal
- Matching is done via case-insensitive regex against the segment text
- Rules are ordered by phrase length (longest first) to prevent partial matches from interfering

**Example lexicon rules:**
| Wrong Phrase | Correct Phrase | Anchor Mode |
|---|---|---|
| birth date | birthdate | VERIFICATION |
| recorded deadline | recorded line | COLLECTIONS |
| Future Bank | Future Bank | (any) |

**Self-learning:** When the correction log records the same fix 5+ times (the "Rule of 5"), the system flags it as a promotion candidate. After optional AI audit (Gemini 2.5 Flash), it can be promoted from a logged pattern to a permanent lexicon rule.

---

### Layer 2: N-Gram + Semantic Anchors (Contextual Rescoring)

**Source badge on UI:** `ngram_anchor` (blue)

This layer uses **trigram frequency analysis** — it looks at every 3-word sequence in the transcript and checks if it's a known, valid sequence or a likely Whisper error.

**How it works:**

1. **Trigram construction:** The segment text is broken into overlapping 3-word windows
   - Example: "over the recorded deadline" → `(over, the, recorded)`, `(the, recorded, deadline)`

2. **Frequency lookup:** Each trigram is checked against the `ngram_frequency` table (cached in Redis)
   - The table is seeded from golden reference transcripts and grows as the system processes more audio

3. **Alternative search:** If a trigram has **zero frequency** (never seen before), the system checks if replacing one word creates a well-known trigram
   - Example: `(the, recorded, deadline)` has freq=0, but `(the, recorded, line)` has freq=12 → suggests "deadline" → "line"

4. **Safety guards** (to prevent false positives):
   - **Zero-frequency only:** If the original trigram has any frequency at all, it won't be touched — it's already a valid sequence
   - **Minimum frequency:** The suggested alternative must have freq ≥ 5 (well-attested in the data)
   - **Phonetic similarity:** The differing word must be plausibly a Whisper mishearing, verified by Levenshtein edit distance:
     - Words ≤ 2 characters: never swapped (too risky)
     - Words 3-4 chars: edit distance ≤ 1
     - Longer words: edit distance ≤ 30% of word length
     - Length ratio must be ≥ 0.6 (prevents "ni" → "provider" type errors)
   - **Confidence threshold:** The ratio `suggested_freq / (suggested_freq + orig_freq)` must be ≥ 0.97

**What are Semantic Anchors?**

Semantic Anchors detect the **intent/topic** of each segment using ~40 regex patterns across **18 intent-based modes**:

| Mode | Example Triggers |
|---|---|
| Greeting | "good morning", "magandang umaga" |
| Verification | "verification purposes", "dictate your birthdate" |
| Account_Status | "current balance", "past due amount" |
| Probing:RFD | "reason for delay", "bakit hindi settle" |
| Probing:Dispute | "dispute", "hindi ako ang gumamit" |
| Probing:Hardship | "nawalan ng trabaho", "financial difficulty" |
| Probing:WTP | "willing to pay", "kailan kayo magbabayad" |
| Probing:Promise | "promise to pay", "commitment" |
| Negotiation | "minimum amount due", "restructure" |
| Payment_Details | "reference number", "payment channel" |
| Reminder | "payment reminder", "follow up" |
| Disclosure:Legal | "legal action", "file a case" |
| Disclosure:Credit | "credit standing", "credit bureau" |
| Hold | "please hold", "sandali lang" |
| Transfer | "transfer your call", "supervisor" |
| Closing | "thank you for calling", "anything else" |
| Callback | "call you back", "follow up call" |
| General | fallback for unmatched segments |

The detected mode is used to:
- Filter lexicon rules to only apply domain-relevant corrections
- Bias N-gram analysis toward domain-specific language patterns
- Display on the UI as context labels on each segment card

Anchors use a **context window** — they scan the previous segment, current segment, and next segment together, so a banking term mentioned in segment 5 can set the mode for segments 4-6.

---

### Layer 3: Gemini 2.5 Flash (AI Teacher & Corrector)

**Source badge on UI:** `gemini` (purple)

This layer replaces the previous DistilBERT approach. Instead of blindly predicting words from statistical patterns, Gemini understands Philippine call-center context, Tagalog code-switching, and domain-specific terminology.

**When it triggers:**
- Segments with **low-confidence words** (Whisper was uncertain) → always analyzed
- Segments where **L1 + L2 made no corrections** → analyzed for unknown patterns the lexicon doesn't cover yet

**How it works:**

1. After L1/L2 and post-processing, the full transcript (all segments) is sent to Gemini in a **single API call** (efficient — 1 call per session, not per segment)

2. Gemini receives:
   - All segments with timestamps and the text after L1/L2 corrections
   - A list of low-confidence words flagged by Whisper
   - Instructions specific to Philippine call-center context (Tagalog code-switching, politeness particles like "ho/po", company names, financial terms)

3. Gemini identifies remaining Whisper transcription errors and returns structured corrections

4. Each correction is:
   - **Applied** to the current transcript immediately
   - **Logged** in the correction log with `source=gemini` for tracking
   - **Auto-added to the lexicon** as a permanent rule so L1 catches it in future transcripts

**Self-Learning Effect:**

This is the key design principle — Gemini acts as a **teacher**:
- First transcription: Gemini corrects many errors and creates lexicon rules
- Second transcription: L1 catches the previously-learned patterns, Gemini handles only new ones
- Over time: The lexicon grows, Gemini is called less, and the system becomes increasingly self-sufficient

**Why not DistilBERT?**

DistilBERT was removed because it:
- Has no domain knowledge (Philippine call centers, Tagalog, financial terms)
- Replaces words with the most statistically probable English word, destroying Tagalog code-switching
- Cannot understand context (turned "feel free to reach out" into "are required to carry out")
- Made 112 wrong "corrections" per session vs. only 9 legitimate L1/L2 fixes

---

## Post-Processing

After the 3 layers, two additional cleanup steps run:

### Currency Normalizer
Converts spoken numbers and peso amounts into `₱` format:

1. **"X pesos and Y centavos"** → `₱X.YY` (e.g., "34,847 pesos and 72 centavos" → "₱34,847.72")
2. **"X pesos"** (without centavos) → `₱X.00` (e.g., "5,000 pesos" → "₱5,000.00")
3. **Redundant "centavos" removal** → `₱34,847.72 centavos` → `₱34,847.72` (the decimals already represent centavos)
4. **Symbol normalization** → `P5,000` or `$5,000` → `₱5,000`
5. **Bare amounts** → standalone comma-formatted amounts get `₱` prepended

### Double-Word Deduplication
Removes accidental repeated words like "settle settle" → "settle". Whisper occasionally stutters on word boundaries.

---

## Confidence Score (Shown on UI)

The **confidence score** displayed on low-confidence words comes directly from **Whisper's word-level probability output**.

When Whisper transcribes audio, it assigns a probability (0.0 to 1.0) to each word indicating how certain it is about that word:

| Confidence | Color on UI | Meaning |
|---|---|---|
| ≥ 90% | Green | Whisper is highly confident — word is likely correct |
| 70–89% | Yellow | Moderate confidence — word might be wrong |
| < 70% | Red | Low confidence — Whisper is uncertain, likely a mistake |

**Threshold:** Words below **80% confidence** (`LOW_CONFIDENCE_THRESHOLD = 0.85`) are flagged and displayed as low-confidence words on the segment card.

These flagged words are:
- Displayed in the UI with their confidence percentage
- Used as priority input for Layer 3 (Gemini) — segments with low-confidence words are always analyzed
- Useful for QA reviewers to know which parts of the transcript to double-check

**Important:** Confidence scores reflect Whisper's internal certainty, not whether the word is actually correct. A word can have high confidence but still be wrong (e.g., Whisper confidently transcribing "deadline" instead of the correct "line" because both sound similar).

---

## Self-Learning Loop

The system gets smarter over time through two feedback mechanisms:

### Mechanism 1: Gemini Auto-Learning (Primary)

Every time Gemini corrects a word/phrase:
1. The correction is **applied** to the current transcript
2. The correction is **logged** in `correction_log` with `source=gemini`
3. A **new lexicon rule** is auto-created: `wrong_phrase → correct_phrase` (permanent)
4. On the next transcription, **Layer 1 (Lexicon)** catches this pattern — no Gemini call needed

This means the system learns from each session. Over time, the lexicon grows and Gemini handles only genuinely new, unseen errors.

### Mechanism 2: Rule-of-5 Promotion (Supplementary)

For corrections from L1/L2 sources:
1. **Every correction is logged** in the `correction_log` table with: original text, corrected text, source, and timestamp
2. **Rule of 5:** When the same correction appears 5+ times, it becomes a "promotion candidate"
3. **Audit (optional):** Promotion candidates can be reviewed by Gemini 2.5 Flash to verify they're legitimate patterns
4. **Promotion:** Verified candidates are promoted to permanent lexicon rules

### Mechanism 3: N-Gram Growth

After every refinement, the corrected text is ingested back into the N-gram frequency table. This makes the system progressively better at recognizing valid 3-word sequences, reducing false N-gram replacements.

### Mechanism 4: Human-Guided Gemini Correction

Users can manually correct individual segments using the "Correct with Gemini" button on the Session Detail page:

1. User clicks the sparkle button on a segment and types a natural-language instruction
2. The instruction + segment text are sent to Gemini 2.5 Flash via a dedicated prompt template
3. Gemini returns the corrected text and a list of changes
4. The correction is:
   - **Applied** to the session result in the database
   - **Auto-added to the lexicon** with context hint `"human-guided via Gemini"`
   - **Logged** in `correction_log` with `source=gemini`
5. Future transcriptions will catch the same pattern via Layer 1 (Lexicon)

### Occurrence Tracking

All corrections (from any source) are logged with occurrence counts. This data helps assess:
- How often the same error appears across sessions
- Whether high-confidence words still need correction (indicating Whisper systematic errors)
- Whether the lexicon is growing effectively (fewer Gemini corrections over time)

---

## UI Guide

### Dashboard
Shows all past refinement sessions with filename, speaker role, segment count, correction count, and timestamp.

### Upload Page
Drag-and-drop or click to upload audio files. Select the speaker role (agent or client). The system transcribes via Groq, corrects via the 3-layer pipeline, and saves the session.

### Session Detail Page

**Processing Stage Indicator:**
While a session is processing, a visual indicator shows the current pipeline stage:
- **Whisper** → **Lexicon** → **N-Gram** → **Gemini**
- Past stages show as **green dots**, the active stage pulses as a **blue dot**, and future stages are dimmed
- A client-side elapsed timer ticks every second for smooth updates
- Stages only move forward (never jump backward), with 1-second polling intervals

**Processing Duration Badge:**
Once processing completes, a sky-blue badge shows the total duration (e.g., "15s" or "1m 23s"), calculated from `created_at` to `completed_at`.

**Three view modes:**
- **Transcript Only:** Clean text, no timestamps or annotations
- **With Timestamps:** Each segment prefixed with `[m:ss.d - m:ss.d]`
- **With Corrections:** Full detail view showing original vs. refined text, correction badges with source labels, anchor mode tags, and low-confidence word indicators

**"Correct with Gemini" Button:**
Each segment in the corrections view has a gradient violet→indigo button with a sparkle icon. Clicking it opens a chat form where you can type a natural-language instruction (e.g., "The caller said 'ididikta' not 'ididictate'"). The instruction is sent to Gemini along with the segment text, and the correction is:
- Applied to the session immediately
- Auto-added to the lexicon for future transcriptions
- Logged in the correction log with `source=gemini`

**Three download formats:**
- **Transcript** (green button): Plain text file
- **Timestamps** (blue button): Each line prefixed with time range
- **Full Results** (purple button): Timestamped text plus correction annotations showing what was changed, by which layer, and the original text

### Lexicon Page
View, add, edit, and delete permanent lexicon rules. Each rule has: wrong phrase, correct phrase, optional context hint, and optional anchor mode. Search box filters rules in real-time.

### N-Gram Page
Browse the trigram frequency database with search, pagination, and frequency bar visualization. Shows all stored 3-word sequences sorted by frequency (highest first). Each row displays word1, word2, word3, frequency count, and a proportional bar chart.

### Self-Learning Page
Three tabs: **Candidates**, **Log**, and **Results**.

The **Log** tab includes source filter cards showing counts by correction source:
- **All** — total corrections
- **Lexicon** — corrections from permanent rules (blue badge)
- **N-Gram** — corrections from trigram analysis (purple badge)
- **Gemini** — corrections from AI teacher (violet badge)

Click a filter card to show only corrections from that source.

### Account Page
Change password and manage user accounts (admin only).

---

## Architecture Summary

```
Audio File
    │
    ▼
Groq Whisper API (whisper-large-v3-turbo)
    │
    ▼ segments + word-level timestamps + confidence scores
    │
    ▼
┌─────────────────────────────────────────┐
│         Semantic Anchor Scanner         │
│   (detects BANKING/COLLECTIONS/VERIFY)  │
└─────────────────────────────────────────┘
    │
    ▼ anchor_mode per segment
    │
┌─────────────────────────────────────────┐
│        Layer 1: Lexicon Lookup          │
│     (permanent rules from Table A)      │
│  (includes auto-learned Gemini rules)   │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│    Layer 2: N-Gram + Anchor Analysis    │
│  (trigram frequency from Table B +      │
│   phonetic similarity guard)            │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│         Post-Processing                 │
│  • "X pesos and Y centavos" → ₱X.YY    │
│  • "X pesos" → ₱X.00                   │
│  • Strip redundant "centavos" after ₱   │
│  • Currency symbol normalize (P/$→₱)    │
│  • Double-word dedup                    │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│   Layer 3: Gemini 2.5 Flash Teacher     │
│  • Analyzes full transcript (1 API call)│
│  • Corrects remaining Whisper errors    │
│  • Auto-adds corrections to lexicon     │
│  • Logs for self-learning tracking      │
└─────────────────────────────────────────┘
    │
    ▼
Refined Transcript + Correction Details
    │
    ├──▶ Saved to DB (transcription_sessions)
    ├──▶ Corrections logged (correction_log)
    ├──▶ New lexicon rules created (auto-learn)
    └──▶ N-grams ingested (self-learning)
```

## Database Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `lexicon` | Permanent word/phrase correction rules (Table A) | wrong_phrase, correct_phrase, context_hint, anchor_mode, is_permanent |
| `ngram_frequency` | Trigram frequency counts for statistical analysis (Table B) | word1, word2, word3, frequency |
| `correction_log` | Every correction ever made, for self-learning | original_phrase, corrected_phrase, source, occurrences, promoted |
| `users` | Authentication accounts | username, password_hash, role |
| `transcription_sessions` | Saved refinement results with full JSON data | session_key, status, processing_stage, result_json, completed_at |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/login` | Login with username/password, returns JWT |
| GET | `/api/v1/auth/me` | Get current user info |
| PUT | `/api/v1/auth/password` | Change password |
| GET | `/api/v1/auth/users` | List all users (admin) |
| POST | `/api/v1/auth/users` | Create user (admin) |
| DELETE | `/api/v1/auth/users/{id}` | Delete user (admin) |
| GET | `/api/v1/health` | Health check |
| POST | `/api/v1/transcribe` | Upload audio, transcribe + refine |
| POST | `/api/v1/refine` | Refine raw segments (manual) |
| GET | `/api/v1/sessions` | List all sessions |
| GET | `/api/v1/sessions/{key}` | Get session detail (includes processing_stage) |
| DELETE | `/api/v1/sessions/{key}` | Delete session |
| GET | `/api/v1/sessions/{key}/download` | Download session (transcript/timestamped/results) |
| POST | `/api/v1/sessions/{key}/correct-segment` | Human-guided Gemini correction for a segment |
| GET | `/api/v1/lexicon` | List all lexicon rules |
| POST | `/api/v1/lexicon` | Add a lexicon rule |
| PUT | `/api/v1/lexicon/{id}` | Update a lexicon rule |
| DELETE | `/api/v1/lexicon/{id}` | Delete a lexicon rule |
| GET | `/api/v1/ngram` | List N-grams (search, pagination) |
| POST | `/api/v1/ngram/ingest` | Ingest trigrams from texts |
| GET | `/api/v1/ngram/lookup` | Lookup single trigram frequency |
| GET | `/api/v1/corrections/candidates` | Get Rule-of-5 promotion candidates |
| POST | `/api/v1/corrections/promote` | Trigger auto-promotion with Gemini audit |
| GET | `/api/v1/corrections/log` | Get full correction log |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LOW_CONFIDENCE_THRESHOLD` | `0.80` | Whisper words below this probability are flagged as low-confidence |
| `CORRECTION_THRESHOLD` | `5` | Number of occurrences needed for Rule-of-5 promotion |
| `GEMINI_API_KEY` | — | Google Gemini 2.5 Flash API key |
| `GROQ_API_KEY` | — | Groq API key for Whisper transcription |
| `DATABASE_URL` | `postgresql://phoenix:phoenix@localhost:5432/phoenix` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis cache connection |

## Tech Stack

- **Backend:** FastAPI (Python 3.12), uvicorn
- **Database:** PostgreSQL 16, Redis 7 (caching)
- **Whisper:** Groq API (whisper-large-v3-turbo)
- **AI Corrector:** Gemini 2.5 Flash (transcript correction + auto-learning)
- **Frontend:** React 18, TypeScript, Tailwind CSS, Vite
- **Auth:** JWT (HS256) + bcrypt
- **Deployment:** Docker Compose (5 containers: postgres, redis, backend, frontend, pgadmin)

---

## Database Viewer (pgAdmin)

pgAdmin is included in the Docker setup for browsing the PostgreSQL database directly.

**Access:** Open **http://localhost:5050/browser/** in your browser

**Login credentials:**
- Email: `admin@phoenix.com`
- Password: `admin`

**Connecting to the database:**
1. The **Phoenix DB** server is pre-configured in the sidebar
2. Click on **Phoenix DB** — when prompted for the database password, enter: `phoenix`
3. Navigate: **Phoenix DB → Databases → phoenix → Schemas → public → Tables**
4. Right-click any table → **View/Edit Data → All Rows** to browse data

**Tables you'll find:**
- `lexicon` — all permanent correction rules (wrong phrase → correct phrase)
- `ngram_frequency` — trigram word sequences with their frequency counts
- `correction_log` — history of every correction the system has ever made
- `users` — authentication accounts
- `transcription_sessions` — saved refinement sessions with full JSON results
