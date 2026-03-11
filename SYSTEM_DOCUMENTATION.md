# Phoenix 3.0 – Self-Learning Transcript Refiner

## System Overview

Phoenix 3.0 is a **deterministic-first transcript correction system** that refines Whisper-generated transcripts using a 3-layer correction hierarchy. Rather than relying on a single AI model, it applies targeted, explainable corrections where each fix has a clear source and rationale.

### How Refinement Works

When you upload an audio file, the system:

1. **Transcribes** the audio via the Groq API (Whisper `large-v3-turbo` model)
2. **Extracts** per-word confidence scores and segment timestamps
3. **Detects** the domain context (Banking, Collections, Verification) using Semantic Anchors
4. **Corrects** the transcript through 3 sequential layers
5. **Post-processes** (currency normalization, K-shorthand expansion, email formatting, double-word dedup)
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

Semantic Anchors detect the **intent/topic** of each segment using a **3-tier context-aware classification system**. Anchor patterns are stored in the database (`semantic_anchors` table) and managed via the **Anchors** page in the UI.

**Architecture: Two-Pass Classification**

- **Pass 1 (L2 hint):** During correction (before Gemini), a quick regex scan of raw text provides a rough mode hint for N-gram scoring bias. No context engine — just vote counting.
- **Pass 2 (final):** After all corrections (L1 + L2 + Post + Gemini), the fully corrected text is classified with the full context engine:

  1. **Weighted regex vote counting** — Each DB pattern has a weight (1-5). Matches accumulate weighted votes per mode.
  2. **Conversation position zones** — Opening (first 10%): boosts GREETING/INTRODUCTION/VERIFICATION. Closing (last 12%): boosts CLOSING. This fixes "thanks you too" near end of call being misclassified.
  3. **Look-back window** — Checks previous 2 segment modes. If the same mode dominated, its weight is reduced (conversations move forward).
  4. **Question detection** — Filipino question particles (`ba`, `ano`, `bakit`, `paano`, `kailan`, `magkano`, `gaano`, `saan`, `sino`, `alin`) and `?` marks boost inquiry/probing modes and reduce PTP. This fixes "Okay, ano ba yan?" being misclassified as PTP.
  5. **Gemini escalation** — If top 2 modes are tied after steps 1-4, the segment + context is sent to Gemini to break the tie. Only ~5-15% of segments trigger this.

**19 intent-based modes:**

| Mode | Example Triggers |
|---|---|
| Greeting | "good morning", "kamusta" |
| Introduction | "SP Madrid Law Firm", "this is ... from" |
| Consent to Record | "over the recorded line", "call is being recorded" |
| Verification | "verification purposes", "birthdate", "March 19, 1988", "01/15/1990" |
| Account Status | "credit card account", "past due", "outstanding balance" |
| Probing: RFD | "reason for delay", "bakit hindi settle" |
| Probing: SOF | "source of funds", "salary", "employed" |
| Negotiation | "settle", "full payment", "partial payment", "discount" |
| Benefits | "good standing", "credit score" |
| Consequences | "suspension", "legal proceedings", "escalation" |
| PTP / Commitment | "commitment to pay", "sige po", "babayaran ko" |
| Payment Channel | "online banking", "GCash", "account number" |
| Contact Info | "email address", "contact number", "spm@spmadridlaw.com", "pen and paper" |
| Recap | "recap natin", "napag-usapan" |
| Empathy | "naiintindihan ko po", "sorry to hear" |
| Objection Handling | "hindi ko kaya", "can't afford", "hold muna" |
| Closing | "thank you", "ingat po kayo", "you too", "have a good day", "god bless" |
| 3rd Party Contact | "alternate number", "relation to borrower" |
| General | fallback for unmatched segments |

The detected mode is used to:
- Filter lexicon rules to only apply domain-relevant corrections
- Bias N-gram analysis toward domain-specific language patterns
- Display on the UI as context labels on each segment card

Anchors use a **context window** — they scan the previous segment, current segment, and next segment together, so a banking term mentioned in segment 5 can set the mode for segments 4-6.

---

### Layer 3: Gemini 3.1 Flash Lite (AI Teacher & Corrector)

**Source badge on UI:** `gemini` (purple)

This layer replaces the previous DistilBERT approach. Instead of blindly predicting words from statistical patterns, Gemini understands Philippine call-center context, Tagalog code-switching, and domain-specific terminology.

**When it triggers:**
- **ONLY when unknown words are detected** by N-gram corpus analysis
- Words not found in any trigram are flagged as likely transcription errors
- If N-gram finds no unknown words → Gemini is **completely skipped** (saves ~80% of API costs)

**Optimized API Usage (v3.1):**

Instead of sending the entire transcript to Gemini, the system now:
1. Identifies segments with unknown words flagged by N-gram
2. Sends **only those segments** (plus 1 segment of context before/after)
3. Includes specific unknown words list to focus Gemini's attention
4. Skips Gemini entirely if no unknown words detected

**How it works:**

1. After L1/L2 and post-processing, only **segments with unknown words** are sent to Gemini (not the full transcript)

2. Gemini receives:
   - Only segments containing flagged unknown words (with neighboring context)
   - A list of **unknown words** flagged by N-gram corpus analysis
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
- Over time: The lexicon grows, **Gemini is called less frequently**, and the system becomes increasingly self-sufficient

**Token Optimization:**

| Scenario | Before v3.1 | After v3.1 |
|----------|-------------|------------|
| 50 segments, 5 unknowns | ~2000 tokens | ~500 tokens |
| 50 segments, 0 unknowns | ~2000 tokens | **0 tokens (skipped)** |
| Repeat content | Full cost | Free (learned in lexicon) |

**Configurable Model:**

The Gemini model can be changed via environment variable:
```
GEMINI_MODEL=gemini-3.1-flash-lite-preview (default)
GEMINI_MODEL=gemini-3.1-flash-lite-preview (lower cost)
GEMINI_MODEL=gemini-2.0-flash-lite (high volume)
```

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
6. **K-shorthand** → `2K` / `50k` / `2 K` → `₱2,000` / `₱50,000` (digit followed by K/k, word-boundary safe — "OK" is not affected)
7. **Comma formatting** → All `₱` amounts auto-formatted with comma separators (₱24500 → ₱24,500). Idempotent — already-formatted amounts are not affected.

### Double-Word Deduplication
Removes accidental repeated words like "settle settle" → "settle". Whisper occasionally stutters on word boundaries.

### Email Formatter
Assembles email addresses from common Whisper mishearing patterns. Unlike the currency normalizer (which handles known formats), the email formatter handles **any email** — even ones the system has never seen before.

**Pattern Detection (3 passes):**
1. **Known misheard domains** → `user at it mail dot com` → `user@gmail.com` (handles: gmail, yahoo, hotmail, outlook)
2. **Single-word domains** → `spm at spmadridlaw dot com` → `spm@spmadridlaw.com`
3. **"at" as word** → `user at domain.com` → `user@domain.com`
4. **Dot instead of @** → `spm.spmadridlaw.com` → `spm@spmadridlaw.com`

**Domain correction** (common Whisper phonetic confusions):
- `it mail` / `g mail` / `gemail` → `gmail`
- `ya who` / `ya hoo` → `yahoo`
- `hot mail` / `hotmale` → `hotmail`
- `out look` / `outluk` → `outlook`

**TLD normalization** (spoken → actual):
- `dot com` / `dotcom` / `dot calm` → `.com`
- `dot ph` → `.ph`  |  `dot net` → `.net`  |  `dot org` → `.org`

**Why not lexicon?** Lexicon only catches emails it has explicit rules for. A brand-new email like `john at gmail dot com` would pass through uncorrected. The formatter handles ALL email patterns generically. Semantic domain corrections (e.g., `spmadridlo` → `spmadridlaw`) are left to Gemini, which auto-learns them as probationary lexicon rules.

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
2. The instruction + segment text are sent to Gemini 3.1 Flash Lite via a dedicated prompt template
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

## Defensive Mechanisms (3-Layer Defense)

The following safety mechanisms prevent catastrophic auto-learning failures (e.g., learning `you → po` which would corrupt every "you" in future transcripts).

### Defense 1: Stopword Guard (Gate 0 — Auto-Learning)

**Location:** `_auto_add_lexicon_rule()` in `correction_engine.py`

A hardcoded set of **common English/Filipino stopwords** that should NEVER be auto-learned as single-word replacements:

```python
_STOPWORDS = frozenset({
    # English pronouns, verbs, articles, conjunctions
    "i", "me", "you", "your", "he", "she", "it", "we", "they", "is", "am", "are",
    "was", "were", "be", "do", "did", "has", "had", "have", "will", "would", ...

    # Filipino particles / common words
    "po", "ho", "ko", "mo", "ka", "na", "ba", "pa", "naman", "lang", "nga", ...
})
```

**Logic:** If `wrong_phrase` is a single word AND in the stopword set → **reject and log** why:
```
Stopword guard prevented auto-learn: 'you' → 'po'
```

This alone would have prevented the "you → po" disaster.

### Defense 2: Anchor Mode Inheritance (Auto-Learned Rules)

**Location:** `_auto_add_lexicon_rule()` in `correction_engine.py`

When Gemini auto-learns a correction, the rule inherits the **segment's anchor_mode** (the detected call context at that position in the transcript).

**Before:** Rules were stored with `anchor_mode = NULL` (any context) — dangerous because a greeting-context correction could pollute billing segments.

**After:** Rules are stored with the segment's `anchor_mode` (e.g., `account_status`, `greeting`, `closing`), so they only apply in matching contexts.

**Example:**
- Segment detected as `account_status`: "minimum amount, you" in billing context
- Gemini corrects: `you → due`
- Rule stored: `minimum amount, you → minimum amount due` with `anchor_mode = account_status`
- Future segments classified as `greeting` won't have this rule applied

### Defense 3: Short-Word Lexicon Guard (L1 Application)

**Location:** `check()` and `apply()` methods in `lexicon.py`

When applying lexicon rules in L1, very short single-word rules (≤3 characters) get additional scrutiny:

| Rule Characteristics | Behavior |
|---------------------|----------|
| Single word ≤3 chars, `anchor_mode = NULL` | **SKIPPED** (too dangerous without context) |
| Single word ≤3 chars, has `anchor_mode` | **Applied only** when segment's anchor_mode matches |
| Multi-word OR >3 chars | Normal application |

This prevents rules like `you → po` from applying universally even if they escape the stopword guard.

### Defense 4: L1 Lexicon Regex Punctuation Fix

**Location:** `_build_lexicon_pattern()` helper in `lexicon.py`

**Problem:** Lexicon patterns used `\bWRONG_PHRASE\b` with word boundaries on both sides. This failed when phrases ended with punctuation (e.g., `minimum amount, you.`), because `\b` expects a word boundary after a non-word character.

**Fix:** Word boundaries are now intelligent:
- Leading `\b` only if phrase starts with a word character (letter/digit/underscore)
- Trailing `\b` only if phrase ends with a word character

```python
# Old (broken for punctuation):
pattern = r'\b' + re.escape(wrong) + r'\b'

# New (handles punctuation):
leading_boundary = r'\b' if wrong[0].isalnum() else ''
trailing_boundary = r'\b' if wrong[-1].isalnum() else ''
pattern = leading_boundary + re.escape(wrong) + trailing_boundary
```

### Defense 5: N-Gram Negative Ingestion (Corpus Cleaning)

**Location:** `apply_correction_feedback()` in `ngram_auditor.py`, called from `correct_segment` endpoint in `routes.py`

**Problem:** The N-gram corpus can be "polluted" when uncorrected Whisper errors pass through all layers and get ingested. Example: `(minimum, amount, you)` gets frequency > 0 from bad transcripts, then future corrections are blocked.

**Solution:** When a human uses "Correct with Gemini" to fix text:
1. **Penalize** trigrams from the original (incorrect) text: frequency reduced by 5
2. **Reward** trigrams from the corrected text: frequency increased by 3

This actively "cleans" the corpus over time as humans correct errors.

**Example:**
- Original: "minimum amount, you"
- Corrected: "minimum amount due"
- Penalized trigram: `(minimum, amount, you)` → freq reduced by 5
- Rewarded trigram: `(minimum, amount, due)` → freq increased by 3

### Defense 6: Gemini API Error Handling

**Location:** `correct_segment_with_instruction()` in `gemini_corrector.py`, `correct_segment` endpoint in `routes.py`, frontend `api.ts`

**Problem:** When Gemini API fails (rate limit, timeout, etc.), the system silently returned unchanged text with no indication to the user.

**Fix:** 
- Backend returns HTTP 503 with descriptive error message
- Frontend parses JSON error response and displays the message to the user
- Specific handling for 429 (rate limit): "Gemini API rate limit exceeded. Please wait a few minutes and try again."

### Defense 7: Redaction Placeholder Handling

**Location:** `REDACTION_PATTERN` in `ngram_auditor.py`, system prompt in `gemini_corrector.py`

**Problem:** Transcripts imported from external systems may contain redacted/masked values like `[MONTH]`, `[VALUE]`, `[PERSON]`, `[ORGANIZATION]`, `[BANK NAME]`, `[PAYMENT MODE]`. These should NOT be flagged as unknown words or "corrected" by any layer.

**Fix:**
1. **N-gram tokenizer strips redaction placeholders** before analysis:
   - Pattern: `\[[A-Z][A-Z0-9\s]+\]` (uppercase text in brackets)
   - These tokens are simply removed before trigram building and unknown word detection
   - Example: `"Good morning [PERSON], your balance is [VALUE]"` → tokenizes to `["good", "morning", "your", "balance", "is"]`

2. **Gemini system prompt explicitly instructs** preservation:
   - "NEVER change redaction placeholders like [MONTH], [VALUE], [PERSON]..."
   - "Text in [UPPERCASE BRACKETS] are redacted/masked values — leave them unchanged"

### Defense 8: Position-Aware Closing Detection

**Location:** `classify_segment()` in `semantic_anchors.py`

**Problem:** Phrases like "thank you" and "salamat" can occur mid-conversation (e.g., "thank you for that information") but shouldn't trigger CLOSING anchor detection unless near the end of the call.

**Fix:** Enhanced position-based logic for CLOSING mode:

| Conversation Zone | Position | CLOSING Behavior |
|------------------|----------|------------------|
| Opening | 0-10% | **Suppressed entirely** (votes set to 0) |
| Middle | 10-80% | **Suppressed if standalone**, reduced weight if competing with other modes |
| Closing | 80-100% | **Boosted by +3**, classic closing phrases get additional +3 |

Classic closing phrases (boosted in final 20%): "good bye", "have a good day", "take care", "ingat po", "walang anuman"

This ensures "salamat" at segment 5 of 100 won't be classified as CLOSING, but "salamat po, have a good day" at segment 95 of 100 will be.

---

## UI Guide

### Dashboard
Shows all past refinement sessions with filename, speaker role, segment count, correction count, and timestamp.

### Upload Page

The Upload page supports two input modes:

**Audio Upload Mode (default):**
- Drag-and-drop or click to upload audio files (WAV, MP3, M4A, FLAC, OGG, WEBM)
- Select multiple files at once — they process sequentially
- Choose speaker role (agent or client) before submitting
- System transcribes via Groq, refines via Lexicon → N-Gram → Gemini pipeline

**Plain Text Import Mode:**
- Toggle to "Plain Text Import" mode via the button at the top
- Paste transcript text with speaker labels in the textarea
- Supports three prefixes:
  - `Agent:` — Lines spoken by the agent
  - `Client:` — Lines spoken by the client/borrower
  - `Mixed:` — Overlapping speech or both speakers
- Each line starting with a speaker prefix becomes a separate segment
- Lines without a prefix are appended to the previous segment

**Example plain text format:**
```
Agent: Good morning, thank you for calling SP Madrid and Associates.
Client: Yes po, I received the letter.
Agent: OK po, regarding your outstanding balance of [VALUE] pesos...
Client: Opo, kailan po yung due date?
```

Imported text skips the Whisper transcription step and goes directly through the refinement pipeline (Lexicon → N-Gram → Gemini). Timestamps are synthetic (sequential integers).

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

### Anchors Page
Manage the database-backed semantic anchor patterns that drive intent classification. Three tabs:

**Patterns tab:**
- View all anchor patterns grouped by mode with color-coded badges
- Search by label or regex pattern
- Filter by mode
- Add new patterns (mode, label, regex pattern, weight 1-5)
- Edit existing patterns
- Toggle patterns active/inactive (ON/OFF switch)
- Delete patterns
- Source badges show origin: seed (blue), manual (green), learned (purple)

**Override Log tab:**
- Table of all manual anchor mode overrides made by users in Session Detail
- Shows segment text, original mode → corrected mode, source, filename
- Used for analytics and future self-learning (identifying systematic misclassifications)

**Domain Glossary tab:**
- Manage domain-specific terms tied to each anchor mode (e.g., "minimum amount due" for ACCOUNT_STATUS)
- Terms are **fed to Gemini L3** — the AI corrector uses them as context to prefer domain vocabulary when correcting phonetically similar mishearings
- Terms also enable **N-gram domain boost** — when a segment's anchor mode has glossary terms, the N-gram auditor will bypass phonetic similarity checks for glossary words, allowing corrections like "you" → "due" that would normally fail edit-distance checks
- Add/edit/delete terms with anchor mode + term fields
- Grouped by mode with color-coded badges, same layout as Patterns tab
- Seed data includes 100+ terms across financial, legal, and customer service domains

**How Domain Glossary improves accuracy (example):**
1. Whisper transcribes "due" as "you" → text: "minimum amount, you"
2. N-gram sees `(minimum, amount, you)` with freq=0 and `(minimum, amount, due)` with freq=2559
3. Normally, "you"→"due" fails phonetic similarity (edit distance 3 > threshold 1)
4. BUT "due" is a glossary word for ACCOUNT_STATUS mode → phonetic check bypassed
5. N-gram corrects to "minimum amount, due" ✅
6. Even if N-gram doesn't catch it, Gemini L3 receives the glossary terms and knows to prefer "minimum amount due" over "minimum amount, po"

**Anchor Override in Session Detail:**
- Each segment's anchor badge is now clickable
- Clicking opens a dropdown of all 19 modes
- Selecting a mode immediately updates the segment and logs the override to the anchor_overrides table

### N-Gram Page
Browse the trigram frequency database with search, pagination, and frequency bar visualization. Shows all stored 3-word sequences sorted by frequency (highest first). Each row displays word1, word2, word3, frequency count, and a proportional bar chart.

### Self-Learning Page
Displays the full correction log with source filter cards and a corrections table with pagination.

**Source filter cards** show counts by correction source:
- **All** — total corrections
- **Lexicon (Known)** — corrections from existing permanent rules (blue badge)
- **N-Gram (Auto)** — corrections from trigram analysis (purple badge)
- **Gemini (Auto)** — corrections from AI teacher (violet badge)

**Lexicon Status column** shows the actual promotion state of each correction:
- **Known Rule** — correction matched an existing permanent lexicon rule
- **Probationary (X/3)** — auto-learned rule, not yet promoted. X = current occurrences, 3 = promotion threshold
- **Promoted → Permanent** — auto-learned rule that has been promoted after reaching the threshold

Both Gemini and N-gram corrections start as **probationary** lexicon rules (`is_permanent = FALSE`). After a correction has been applied in 3+ distinct sessions (tracked via `correction_log.occurrences`), it is auto-promoted to permanent. The promotion threshold is returned by the API and displayed dynamically.

### Account Page
Change password and manage user accounts (admin only).

### Pagination
All list pages include client-side pagination via a shared `Pagination` component:
- **Default page size:** 25 items (configurable per-page: 25 / 50 / 100)
- **Pages with pagination:** Dashboard, Lexicon, Blocklist, Self-Learning, Anchors (all 3 tabs), N-Gram
- Search/filter changes automatically reset to page 1
- Controls: first/prev/page numbers/next/last with ellipsis for large ranges
- Shows "X–Y of Z" item count

---

## Architecture Summary

```mermaid
flowchart TD
    subgraph Input
        A[🎵 AUDIO INPUT<br/>caller/callee .wav]
        T[📝 TEXT INPUT<br/>Plain text transcript]
    end
    
    A --> B[🎤 GROQ WHISPER API<br/>whisper-large-v3-turbo<br/>Output: segments + timestamps + confidence]
    T --> P1
    B --> P1
    
    subgraph Pass1[Pass 1: Anchor Classification]
        P1[🎯 SEMANTIC ANCHOR SCANNER<br/>Regex patterns from DB • Redis cached 5m<br/>Output: anchor_mode per segment]
    end
    
    P1 --> L1
    
    subgraph Tables[Reference Tables]
        LEX[(📚 LEXICON TABLE<br/>Permanent + Probationary rules)]
        GLOSS[(📖 DOMAIN GLOSSARY<br/>Terms per anchor_mode)]
        NGRAM[(📊 N-GRAM FREQUENCY<br/>Trigram statistics)]
        CLOG[(📋 CORRECTION LOG<br/>All corrections tracked)]
    end
    
    subgraph L1Layer[Layer 1: Lexicon]
        L1[🔤 LEXICON LOOKUP<br/>• Scoped by anchor_mode<br/>• Longest-match-first<br/>• Word-boundary regex]
    end
    
    LEX --> L1
    L1 --> L2
    
    subgraph L2Layer[Layer 2: N-Gram Analysis]
        L2[📈 N-GRAM + ANCHOR ANALYSIS<br/>• Trigram frequency lookup<br/>• Phonetic similarity guard<br/>• Domain glossary bypass<br/>• Unknown word flagging]
    end
    
    NGRAM --> L2
    GLOSS --> L2
    L2 --> POST
    L2 -.->|Log corrections| CLOG
    
    subgraph PostProc[Post-Processing]
        POST[⚙️ POST-PROCESSING<br/>• Pesos/centavos → ₱X.YY<br/>• Currency normalize P/$→₱<br/>• Email formatter<br/>• Double-word dedup]
    end
    
    POST --> L3
    
    subgraph L3Layer[Layer 3: Gemini Teacher]
        L3[🤖 Gemini 3.1 Flash Lite<br/>• Single API call<br/>• Receives: unknown words, glossary<br/>• Corrects remaining errors]
        L3 --> LEARN[📝 AUTO-ADD LEXICON<br/>Gate 1: Blocklist? → Skip<br/>Gate 2: Exists? → Skip<br/>Pass: INSERT as probationary]
    end
    
    GLOSS -.->|Glossary in prompt| L3
    L3 -.->|Log corrections| CLOG
    LEARN -.->|Self-Learning Loop| LEX
    L3 --> FIN
    
    subgraph FinalPass[Pass 2: Final Classification]
        FIN[🏁 FINAL ANCHOR CLASSIFICATION<br/>• Weighted regex votes<br/>• Position zone bias<br/>• Look-back context<br/>• Tie-breaker logic]
    end
    
    FIN --> OUT
    
    subgraph Output
        OUT[💾 OUTPUT: REFINED TRANSCRIPT<br/>• Saved to DB<br/>• Corrections logged<br/>• N-grams ingested]
    end
    
    OUT --> PROMO
    
    subgraph SelfLearn[Self-Learning Promotion]
        PROMO[⬆️ AUTO-PROMOTION CHECK<br/>occurrences ≥ 75 + not blocklisted?<br/>YES → Gemini Audit → PERMANENT<br/>NO → Stay probationary]
    end
    
    CLOG --> PROMO
    PROMO -.->|Promote to permanent| LEX
```

### Human Override Flow (Trust Erosion)

```mermaid
flowchart TD
    A[👤 User clicks 'Correct with Gemini'] --> B[🤖 Gemini returns corrected text + changes]
    B --> C{For each change<br/>orig → corrected}
    
    C --> D{Conflicting<br/>PROBATIONARY rule?}
    D -->|Yes| E[🗑️ DELETE rule<br/>no second chance]
    D -->|No| F{Conflicting<br/>PERMANENT rule?}
    
    F -->|Yes| G[⬇️ DEMOTE to probationary<br/>trust eroded]
    F -->|No| H[➕ INSERT as PROBATIONARY<br/>must earn ≥3 to promote]
    
    E --> I[✅ Done]
    G --> I
    H --> I
```

## Database Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `lexicon` | Permanent word/phrase correction rules (Table A) | wrong_phrase, correct_phrase, context_hint, anchor_mode, is_permanent |
| `lexicon_blocklist` | Permanently banned correction pairs | wrong_phrase, correct_phrase, reason, banned_by, created_at |
| `ngram_frequency` | Trigram frequency counts for statistical analysis (Table B) | word1, word2, word3, frequency |
| `correction_log` | Every correction ever made, for self-learning | original_phrase, corrected_phrase, source, occurrences, promoted |
| `semantic_anchors` | DB-backed anchor patterns (replaces hardcoded list) | mode, label, pattern (regex), weight (1-5), is_active, source (seed/manual/learned) |
| `anchor_overrides` | Logs every manual anchor mode override | session_id (FK), segment_index, segment_text, original_mode, corrected_mode, source |
| `domain_glossary` | Domain-specific terms per anchor mode (fed to Gemini + N-gram) | anchor_mode, term, UNIQUE(anchor_mode, term) |
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
| GET | `/api/v1/anchors` | List anchor patterns (search, mode filter) |
| POST | `/api/v1/anchors` | Add a new anchor pattern |
| PUT | `/api/v1/anchors/{id}` | Update an anchor pattern |
| DELETE | `/api/v1/anchors/{id}` | Delete an anchor pattern |
| PATCH | `/api/v1/anchors/{id}/toggle` | Toggle anchor pattern active/inactive |
| POST | `/api/v1/sessions/{key}/override-anchor` | Override a segment's anchor mode |
| GET | `/api/v1/anchor-overrides` | List all anchor override history |
| GET | `/api/v1/glossary` | List domain glossary terms (search, mode filter) |
| POST | `/api/v1/glossary` | Add a domain glossary term |
| PUT | `/api/v1/glossary/{id}` | Update a glossary term |
| DELETE | `/api/v1/glossary/{id}` | Delete a glossary term |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LOW_CONFIDENCE_THRESHOLD` | `0.80` | Whisper words below this probability are flagged as low-confidence |
| `CORRECTION_THRESHOLD` | `5` | Number of occurrences needed for Rule-of-5 promotion |
| `GEMINI_API_KEY` | — | Google Gemini 3.1 Flash Lite API key |
| `GROQ_API_KEY` | — | Groq API key for Whisper transcription |
| `DATABASE_URL` | `postgresql://phoenix:phoenix@localhost:5432/phoenix` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis cache connection |

## Tech Stack

- **Backend:** FastAPI (Python 3.12), uvicorn
- **Database:** PostgreSQL 16, Redis 7 (caching)
- **Whisper:** Groq API (whisper-large-v3-turbo)
- **AI Corrector:** Gemini 3.1 Flash Lite (transcript correction + auto-learning)
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
