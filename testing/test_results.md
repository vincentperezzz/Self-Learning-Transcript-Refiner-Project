# Learning Efficiency Test Results
Date: March 12, 2026

## Overview
Tests to validate that the self-learning system reduces Gemini API token consumption over time.

---

## Test 1: Basic Learning Test (test_learning.py)
A simple 11-segment transcript imported 3 times to test basic learning.

### Results
| Run | Tokens Used | Corrections | Notes |
|-----|-------------|-------------|-------|
| 1   | 3,577       | 20          | Baseline - full Gemini processing |
| 2   | 3,270       | 19          | -8.6% reduction |
| 3   | 0           | 18          | -100% reduction - all words known |

### Conclusion
After 2 passes, the N-gram corpus learned all words in the transcript.
Third pass required zero Gemini API calls.

---

## Bulk Training (train_ngram.py)
Ingested all 77 completed sessions into N-gram corpus to accelerate learning.

### Training Summary
- Sessions processed: 77
- Total segments: 2,539
- Total trigrams ingested: 31,537
- N-gram corpus size: 10,781 unique entries

---

## Test 2: Post-Training Complex Transcript (test_after_training.py)
A new 15-segment complex transcript tested AFTER bulk training.

### Results
| Run | Tokens Used | Corrections | Notes |
|-----|-------------|-------------|-------|
| 1   | 5,712       | 46          | First time processing new content |
| 2   | 3,140       | 41          | -45% reduction on second pass |

### Conclusion
Even for a brand new transcript:
- Bulk training pre-teaches common patterns
- Second pass shows 45% token reduction
- System continues learning new vocabulary

---

## Key Findings

1. **Learning is effective**: Token usage drops significantly with repeated content
2. **N-gram ingestion works**: `correction_engine.py` ingests corrected text after each run
3. **Bulk training helps**: Pre-training with past sessions reduces first-run costs for new content
4. **Zero-token runs possible**: When all words are "known", Gemini is skipped entirely

## Code References

### N-gram Learning Flow
1. `correction_engine.py:268` - Ingests corrected text after processing
2. `ngram_auditor.py:289` - `ingest_text()` adds trigrams to frequency table
3. `ngram_auditor.py:413` - `find_unknown_words()` checks if words exist in corpus
4. `correction_engine.py:178` - `needs_gemini = len(all_unknown_words) > 0`

### When Gemini is Called
```python
# correction_engine.py line 178-180
needs_gemini = len(all_unknown_words) > 0

if needs_gemini:
    # Call Gemini API for correction suggestions
```

Gemini is ONLY called when the N-gram auditor finds words not in its corpus.
Once all words are learned, `needs_gemini = False` and API costs drop to zero.
