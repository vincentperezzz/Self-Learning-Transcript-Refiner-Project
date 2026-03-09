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
- Matching is done via case-insensitive regex with **word boundary anchors** (`\b`) to prevent substring matches (e.g., `"bala"` won't match inside `"balak"`)
- Rules are ordered by phrase length (longest first) to give specific phrases priority
- Rules are applied **sequentially** (chained) — each rule runs against the result of the previous, so multi-rule corrections work correctly

**Example lexicon rules:**
| Wrong Phrase | Correct Phrase | Anchor Mode |
|---|---|---|
| birth date | birthdate | VERIFICATION |
| recorded deadline | recorded line | COLLECTIONS |
| Future Bank | Future Bank | (any) |

**Self-learning:** Gemini corrections are auto-added to the lexicon as probationary rules and are immediately active (applied by L1). Rules earn permanent status through auto-promotion (≥3 occurrences) or manual promotion. N-Gram corrections stay in the N-gram domain — they are NOT promoted to the lexicon; instead, N-gram learns through frequency table growth when corrected text is ingested. Human "Correct with Gemini" overrides delete conflicting probationary rules and demote conflicting permanent rules (trust erosion). The correction log tracks all corrections across sources for transparency.

**Blocklist Protection:** Before any auto-learning or auto-promotion, the system checks the `lexicon_blocklist` table. If a correction pair (wrong_phrase, correct_phrase) is blocklisted, it is silently rejected — never applied, never learned, never promoted. See the Blocklist section for details.

**When to use Lexicon vs N-Gram:**

| Use Lexicon when... | Use N-Gram when... |
|---|---|
| The correction is **always** correct regardless of surrounding words | The correction depends on **what words come before/after** |
| Proper nouns: "Anna Dixman" → "Anna De Guzman" | Context-sensitive phrases: "minimum amount dew" → "minimum amount due" (but NOT "minimum amount lang") |
| Deterministic substitutions: "birth date" → "birthdate" | Whisper mishearings where the wrong word could be valid in other contexts |
| Company/brand names: "SP Madridlaw" → "SP Madrid Law" | Any correction where the same wrong word is correct in a different trigram context |

**Example — why "minimum amount due" belongs in N-gram, not lexicon:**
- `"kailangan niyo i-settle yung minimum amount dew"` → N-gram sees `(minimum, amount, dew)` freq=0, finds `(minimum, amount, due)` freq=2559 → corrects to "due" ✅
- `"diko kayang bayaran yung minimum amount lang"` → N-gram sees `(minimum, amount, lang)` freq>0 → **leaves it alone** ✅
- If this were a lexicon rule, it would blindly add "due" in both cases, corrupting the second sentence ❌

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

**Unknown Word Detection:**

After L2 corrections, each segment's refined text is checked against the full N-gram corpus. A word is "unknown" if it never appears in any trigram position (word1, word2, or word3) in the `ngram_frequency` table. Words ≤ 2 characters are skipped (Filipino particles like "na", "ng", "po").

Unknown words are **not corrected** by N-gram (since no alternative was found), but they are **flagged and forwarded to Gemini** as a hint. This bridges the gap between N-gram's statistical detection and Gemini's contextual understanding — N-gram spots the anomaly, Gemini provides the fix.

Example: "mag-buyid" tokenizes to ["mag", "buyid"]. "buyid" appears in zero trigrams → flagged as unknown → Gemini receives it as a priority correction hint.

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
- **Unknown words detected by N-gram corpus analysis** → words not found in any trigram are flagged as likely transcription errors

**How it works:**

1. After L1/L2 and post-processing, the full transcript (all segments) is sent to Gemini in a **single API call** (efficient — 1 call per session, not per segment)

2. Gemini receives:
   - All segments with timestamps and the text after L1/L2 corrections
   - A list of low-confidence words flagged by Whisper
   - A list of **unknown words** flagged by N-gram corpus analysis (words never seen in any trigram)
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

### Email Normalizer
Whisper often transcribes the `@` symbol as the word "at". The email normalizer pattern-matches `"word at domain.com"` → `"word@domain.com"` using a regex that requires a valid domain suffix (`.com`, `.ph`, etc.).

---

## Confidence Score (Shown on UI)

The **confidence score** displayed on low-confidence words comes directly from **Whisper's word-level probability output**.

When Whisper transcribes audio, it assigns a probability (0.0 to 1.0) to each word indicating how certain it is about that word:

| Confidence | Color on UI | Meaning |
|---|---|---|
| ≥ 90% | Green | Whisper is highly confident — word is likely correct |
| 70–89% | Yellow | Moderate confidence — word might be wrong |
| < 70% | Red | Low confidence — Whisper is uncertain, likely a mistake |

**Threshold:** Words below **80% confidence** (`LOW_CONFIDENCE_THRESHOLD = 0.80`) are flagged and displayed as low-confidence words on the segment card.

These flagged words are:
- Displayed in the UI with their confidence percentage
- Used as priority input for Layer 3 (Gemini) — segments with low-confidence words are always analyzed
- Useful for QA reviewers to know which parts of the transcript to double-check

**Important:** Confidence scores reflect Whisper's internal certainty, not whether the word is actually correct. A word can have high confidence but still be wrong (e.g., Whisper confidently transcribing "deadline" instead of the correct "line" because both sound similar).

---

## Self-Learning Loop

The system gets smarter over time through four feedback mechanisms:

### Mechanism 1: Gemini Auto-Learning (Primary)

Every time Gemini corrects a word/phrase:
1. The correction is **applied** to the current transcript
2. The correction is **logged** in `correction_log` with `source=gemini`
3. A **probationary lexicon rule** is auto-created: `wrong_phrase → correct_phrase` (`is_permanent=FALSE`)
4. Because both permanent and probationary rules are loaded by Layer 1, the rule is **immediately active** for future transcripts
5. After the rule has been applied in **≥3 distinct sessions** (correction_log occurrences ≥ 3), it is **auto-promoted to permanent**

This means the system still learns from each session — corrections are immediately effective — but they must prove their worth before becoming permanently trusted.

**Token Optimization:** Gemini receives only the rules that L1 actually applied to the current transcript (~50 tokens) instead of the entire lexicon. Duplicate corrections are filtered post-Gemini before applying.

### Mechanism 2: N-Gram Frequency Growth (Self-Improving Context)

N-gram corrections stay **entirely within the N-gram domain** — they are NOT promoted to the lexicon. This is by design:

- **Lexicon** = context-blind (always replaces a phrase regardless of surrounding words)
- **N-gram** = context-aware (checks 3-word windows, only corrects zero-frequency sequences)

When N-Gram (L2) makes a correction:
1. The correction is **applied** to the transcript and **logged** in `correction_log` with `source=ngram_anchor`
2. At the end of the pipeline, the **corrected text is ingested** back into the N-gram frequency table
3. This means corrected trigrams gain frequency over time, making N-gram increasingly confident
4. N-gram corrections are **not** added to the lexicon — the `ngram_frequency` table IS N-gram's persistent memory

**Why no lexicon crossover?** N-gram corrections are contextual — "minimum amount dew" → "minimum amount due" is correct because `(minimum, amount, due)` has freq=2559. But "minimum amount lang" should stay unchanged because `(minimum, amount, lang)` also has frequency. A lexicon rule would lose this context-awareness and blindly replace in all contexts.

**N-gram handles novel variants automatically:** If Whisper invents a new mishearing ("minimum amount joo"), N-gram catches it because `(minimum, amount, joo)` has zero frequency and `(minimum, amount, due)` is the dominant alternative. Lexicon would need a new rule for each variant.

**Why Gemini → Lexicon does NOT break N-gram's domain:**

Gemini corrections are added to the lexicon as probationary rules, and this is intentionally different from the removed N-gram → Lexicon crossover. The distinction is *semantic confidence*:

| Source | Where stored | Confidence type |
|---|---|---|
| **N-gram (L2)** | `ngram_frequency` only (via corrected text ingestion) | Statistical guess — context-dependent |
| **Gemini (L3)** | `lexicon` (probationary) + `ngram_frequency` (via ingestion) | Semantic judgment — understands meaning |
| **Human-guided Gemini** | `lexicon` (probationary) | Human-validated correction |

- **N-gram → Lexicon** was removed because statistical guesses promoted to context-blind rules are dangerous. N-gram doesn't understand meaning — it only knows `(minimum, amount, dew)` has zero frequency.
- **Gemini → Lexicon** is kept because semantic judgments promoted to rules are safe. When Gemini says `"minimum amount dew"` should be `"minimum amount due"`, it understands that "dew" makes no sense in a billing context. The exact phrase `"minimum amount dew"` IS always wrong — lexicon can safely catch it.

The two systems learn in parallel, not in conflict:
1. Gemini creates exact-phrase lexicon rules → catches **known** mishearings at L1 (fast, deterministic)
2. Corrected text is ingested into N-gram → catches **novel** variants that no lexicon rule exists for yet

N-gram's domain is preserved because it remains the early-warning system for new patterns. Lexicon only contains rules that have been semantically confirmed by Gemini or a human.

### Mechanism 3: Reverse Detection (Trust Erosion)

When a user corrects a segment via the "Correct with Gemini" button, the system applies a **trust erosion** model to conflicting lexicon rules:

| Old Rule Status | Action |
|---|---|
| **Probationary** | **Deleted** (no second chance — the rule was wrong) |
| **Permanent** | **Demoted to probationary** (trust eroded — must re-earn permanent status) |

The new correction from the human-guided Gemini call is always inserted as a **probationary** rule. It must earn permanent status through the same promotion criteria (≥3 occurrences).

**Example flow:**
- Gemini auto-learns: `"recorded deadline"` → `"recorded line"` (probationary)
- User clicks "Correct with Gemini" and says `"line"` should actually be `"deadline"` in this context
- System **deletes** the probationary rule `"recorded deadline" → "recorded line"`
- System adds a new **probationary** rule: `"recorded line"` → `"recorded deadline"`
- If a permanent rule had `"line"` as its `correct_phrase`, it would be **demoted** to probationary

**Demoted rules reset:** When a permanent rule is demoted, it must re-earn its 3 sessions from scratch for re-promotion.

### Mechanism 4: Human-Guided Gemini Correction

Users can manually correct individual segments using the "Correct with Gemini" button on the Session Detail page:

1. User clicks the sparkle button on a segment and types a natural-language instruction
2. The instruction + segment text are sent to Gemini 2.5 Flash via a dedicated prompt template
3. Gemini returns the corrected text and a list of changes
4. The correction is:
   - **Applied** to the session result in the database
   - **Auto-added to the lexicon** as a **probationary** rule with context hint `"human-guided Gemini correction (probationary)"`
   - Any conflicting probationary rules are **deleted**, and conflicting permanent rules are **demoted** (trust erosion)
   - **Logged** in `correction_log` with `source=gemini`
5. The new rule is immediately active for future transcriptions via Layer 1
6. It earns permanent status through the standard promotion criteria (≥3 occurrences)

### Mechanism 5: N-Gram Growth

After every refinement, the corrected text is ingested back into the N-gram frequency table. This makes the system progressively better at recognizing valid 3-word sequences, reducing false N-gram replacements.

### Mechanism 6: N-Gram Unknown Word Detection → Gemini Hints

After L1+L2 corrections, each segment is scanned against the N-gram corpus. Words that never appear in any trigram position are flagged as "unknown" and forwarded to Gemini as priority correction hints. This bridges the gap between N-gram's statistical detection and Gemini's contextual understanding:

- **N-gram** spots the anomaly (word never seen in any valid trigram)
- **Gemini** provides the semantic fix (understands what the word should be in context)

Guard: words ≤ 2 characters are skipped to avoid false-flagging Filipino particles.

Once Gemini corrects the unknown word, the correction flows through the standard Gemini self-learning loop (auto-added to lexicon as probationary, ingested into N-gram after correction).

### Mechanism 7: Blocklist (Permanent Bans)

The blocklist prevents the **self-poisoning feedback loop** where bad corrections get auto-learned, auto-promoted, and re-learned even after deletion.

**The Problem it Solves:**
```
Gemini suggests bad correction → auto-added to lexicon
  → applied in 3+ sessions → auto-promoted to PERMANENT
  → corrected text ingested into N-gram (contaminates corpus)
  → user deletes rule → Gemini suggests same correction again → cycle repeats
```

**How it Works:**

A `lexicon_blocklist` table stores permanently banned (wrong_phrase, correct_phrase) pairs. The system checks the blocklist at **three gates**:

| Gate | Location | What it blocks |
|------|----------|----------------|
| Gate 1 | Gemini correction application | Prevents the correction from being applied to the transcript AND from being auto-learned into the lexicon |
| Gate 2 | `_auto_add_lexicon_rule()` / `_auto_add_ngram_rule()` | Prevents both Gemini and N-gram corrections from being auto-added as probationary rules |
| Gate 3 | `_check_promotions()` | Prevents existing probationary rules from being auto-promoted to permanent |

**Key design:** The blocklist bans **specific pairs**, not just phrases. Banning `"suspension" → "suspensions"` does NOT block `"suspension" → "suspensyon"` — only the exact wrong correction is blocked.

**UI:** The Lexicon page's delete button now acts as a "Ban" button (🚫 icon) — it deletes the rule AND adds it to the blocklist with an optional reason. A dedicated Blocklist page allows viewing, searching, adding manual bans, and unbanning.

### Mechanism 8: Auto-Promotion (Probationary → Permanent)

After each transcription session, the system checks all probationary rules for auto-promotion eligibility:

| Criterion | Threshold |
|---|---|
| Applied in N distinct sessions (via correction_log occurrences) | ≥ 3 |
| NOT on the blocklist | Checked via `lexicon_blocklist` table |

When all criteria are met, the rule is automatically promoted to permanent (`is_permanent = TRUE`). Blocklisted pairs are excluded from the promotion query.

Users can also **manually promote** any probationary rule via the green arrow button on the Lexicon page (`PATCH /api/v1/lexicon/{id}/promote`).

### Lexicon Rule Types

| Type | `is_permanent` | Source | Badge Color | Behavior |
|---|---|---|---|---|
| **Permanent** | `TRUE` | Human-added, auto-promoted (earned ≥3 sessions), manually promoted | Green | Always applied, trusted |
| **Probationary** | `FALSE` | Gemini auto-learn, N-Gram auto-promote, human-guided Gemini | Amber | Applied by L1 (same as permanent), flagged for review, auto-removed/demoted on human override, eligible for auto-promotion |

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
View, add, edit, and delete lexicon rules. Each rule has: wrong phrase, correct phrase, optional context hint, and optional anchor mode. Search box filters rules in real-time.

**Status filter tabs** at the top allow filtering by:
- **All** — shows all rules with total count
- **Permanent** (green) — only rules with `is_permanent = TRUE`, with count
- **Probationary** (amber) — only rules with `is_permanent = FALSE`, with count

Rules show a **Status** badge:
- **Permanent** (green) — earned through auto-promotion (≥3 occurrences), manually promoted, or human-added
- **Probationary** (amber) — auto-learned from Gemini, auto-promoted from N-Gram analysis, or human-guided Gemini corrections; subject to review, auto-promotion, and reverse detection

**Actions per rule:**
- **Promote** (green up-arrow, probationary only) — manually promote to permanent
- **Demote** (amber down-arrow, permanent only) — manually demote to probationary
- **Edit** (pencil) — modify wrong/correct phrases, context hint, and anchor mode
- **Ban** (🚫 icon) — delete the rule AND add it to the blocklist so it can never be re-learned. Prompts for an optional reason.

### Blocklist Page
View and manage permanently banned correction pairs. Each entry shows: wrong phrase, banned correction (struck-through), reason, banned-by (manual/auto), and date. Actions:
- **Add Ban** — manually add a correction pair to the blocklist
- **Unban** (checkmark) — remove the ban, allowing the system to learn this correction again

### N-Gram Page
Browse the trigram frequency database with search, pagination, and frequency bar visualization. Shows all stored 3-word sequences sorted by frequency (highest first). Each row displays word1, word2, word3, frequency count, and a proportional bar chart.

### Self-Learning Page
Two tabs: **Candidates** and **Log**.

The **Candidates** tab shows corrections that have reached 5+ occurrences. These are tracked for visibility — Gemini corrections auto-add to the lexicon immediately, and N-Gram corrections auto-promote as probationary rules.

The **Log** tab includes source filter cards showing counts by correction source:
- **All** — total corrections
- **Lexicon** — corrections from permanent rules (blue badge)
- **N-Gram** — corrections from trigram analysis (purple badge)
- **Gemini** — corrections from AI teacher (violet badge)

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
│   (detects intent: 18 anchor modes)     │
└─────────────────────────────────────────┘
    │
    ▼ anchor_mode per segment
    │
┌─────────────────────────────────────────┐
│  Layer 1: Lexicon Lookup (ALL rules)    │  ◄─── new rules added here ──────┐
│  • Permanent + Probationary rules       │                                  │
│  • Filtered by anchor_mode              │                                  │
│  • Longest-match-first ordering         │                                  │
└─────────────────────────────────────────┘                                  │
    │                                                                        │
    ▼                                                                        │
┌─────────────────────────────────────────┐                                  │
│    Layer 2: N-Gram + Anchor Analysis    │                                  │
│  • Trigram frequency from Table B       │                                  │
│  • Phonetic similarity guard            │                                  │
│  • Zero-freq check + min-freq threshold │                                  │
│  • Unknown word detection (zero corpus) │                                  │
└─────────────────────────────────────────┘                                  │
    │                      │                                                 │
    │                      │                                                 │
    │                      ├──▶ Corrections logged (stays in N-gram domain)  │
    │                      │                                                 │
    │                      └──▶ Unknown words flagged ──┐                    │
    ▼                                                   │                    │
┌─────────────────────────────────────────┐                                  │
│         Post-Processing                 │                                  │
│  • "X pesos and Y centavos" → ₱X.YY    │                                  │
│  • Currency symbol normalize (P/$→₱)    │                                  │
│  • Double-word dedup                    │                                  │
└─────────────────────────────────────────┘                                  │
    │                                                                        │
    ▼                                                                        │
┌─────────────────────────────────────────┐                                  │
│   Layer 3: Gemini 2.5 Flash Teacher     │ ◄── unknown words as hints ──────┘
│  • Analyzes full transcript (1 API call)│                                  │
│  • Corrects remaining Whisper errors    │                                  │
│  • Receives applied L1 rules as context │                                  │
│  • Receives N-gram unknown word flags   │                                  │
└─────────────────────────────────────────┘                                  │
    │                      │                                                 │
    │                      └──▶ Auto-add as PROBATIONARY ─────────────────────┘
    ▼                           lexicon rule (is_permanent=FALSE)
    │
Refined Transcript + Correction Details
    │
    ├──▶ Saved to DB (transcription_sessions)
    ├──▶ Corrections logged (correction_log)
    │         │
    │         ▼
    │    ┌──────────────────────────────────────────┐
    │    │       Auto-Promotion Check               │
    │    │  For each probationary rule applied:      │
    │    │                                          │
    │    │  correction_log.occurrences >= 3 ?        │
    │    │     YES ──▶ Promote to PERMANENT          │
    │    │              (is_permanent = TRUE)         │
    │    │     NO  ──▶ Stay PROBATIONARY             │
    │    │              (wait for more sessions)      │
    │    └──────────────────────────────────────────┘
    │
    └──▶ N-grams ingested into Table B (self-learning)
```

### Human Override Flow (Trust Erosion)

```
User clicks "Correct with Gemini" on a segment
    │
    ▼
Gemini returns corrected text + list of changes
    │
    ▼ For each change (orig → corrected):
    │
    ├──▶ Conflicting PROBATIONARY rule found?
    │       (rule.correct_phrase matches orig)
    │         YES ──▶ DELETE the rule (no second chance)
    │
    ├──▶ Conflicting PERMANENT rule found?
    │       (rule.correct_phrase matches orig)
    │         YES ──▶ DEMOTE to PROBATIONARY (trust eroded)
    │
    └──▶ Insert new correction as PROBATIONARY rule
              (must earn ≥3 occurrences to become permanent)
```

## Database Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `lexicon` | Permanent word/phrase correction rules (Table A) | wrong_phrase, correct_phrase, context_hint, anchor_mode, is_permanent |
| `lexicon_blocklist` | Permanently banned correction pairs | wrong_phrase, correct_phrase, reason, banned_by, created_at |
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
| DELETE | `/api/v1/lexicon/{id}` | Ban a lexicon rule (delete + add to blocklist) |
| GET | `/api/v1/blocklist` | List all blocklisted correction pairs |
| POST | `/api/v1/blocklist` | Manually add a correction pair to the blocklist |
| DELETE | `/api/v1/blocklist/{id}` | Unban a blocklisted correction pair |
| PATCH | `/api/v1/lexicon/{id}/promote` | Promote probationary rule to permanent |
| PATCH | `/api/v1/lexicon/{id}/demote` | Demote permanent rule to probationary |
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
- `lexicon_blocklist` — permanently banned correction pairs (cannot be re-learned)
- `ngram_frequency` — trigram word sequences with their frequency counts
- `correction_log` — history of every correction the system has ever made
- `users` — authentication accounts
- `transcription_sessions` — saved refinement sessions with full JSON results
