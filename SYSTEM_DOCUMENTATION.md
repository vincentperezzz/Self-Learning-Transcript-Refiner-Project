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

Semantic Anchors detect the **topic/domain** of each segment using regex patterns:
- "credit card account", "past due", "minimum amount due" → **BANKING** mode
- "SP Madrid Law Firm", "accredited service provider" → **COLLECTIONS** mode
- "verification purposes", "dictate your birthdate" → **VERIFICATION** mode

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
Converts `P5,000` or `$5,000` to `₱5,000` (Philippine Peso). This handles Whisper sometimes transcribing peso amounts with `P` or `$` prefix.

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

**Threshold:** Words below **90% confidence** (`LOW_CONFIDENCE_THRESHOLD = 0.90`) are flagged and displayed as low-confidence words on the segment card.

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
Three view modes:
- **Transcript Only:** Clean text, no timestamps or annotations
- **With Timestamps:** Each segment prefixed with `[m:ss.d - m:ss.d]`
- **With Corrections:** Full detail view showing original vs. refined text, correction badges with source labels, anchor mode tags, and low-confidence word indicators

Three download formats:
- **Transcript** (green button): Plain text file
- **Timestamps** (blue button): Each line prefixed with time range
- **Full Results** (purple button): Timestamped text plus correction annotations showing what was changed, by which layer, and the original text

### Lexicon Page
View, add, edit, and delete permanent lexicon rules. Each rule has: wrong phrase, correct phrase, optional context hint, and optional anchor mode.

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
│  • Currency normalize (P/$→₱)           │
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

| Table | Purpose |
|---|---|
| `lexicon` | Permanent word/phrase correction rules (Table A) |
| `ngram_frequency` | Trigram frequency counts for statistical analysis (Table B) |
| `correction_log` | Every correction ever made, for self-learning |
| `users` | Authentication accounts |
| `transcription_sessions` | Saved refinement results with full JSON data |

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
