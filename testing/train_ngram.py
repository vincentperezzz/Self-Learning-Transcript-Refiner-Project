#!/usr/bin/env python3
"""
Training script - Bulk ingest all past corrected transcripts into N-gram corpus.
This improves learning for future transcripts.
"""
import json
from app.database import get_db
from app.core.ngram_auditor import NGramAuditor

def train_from_past_sessions():
    """Extract corrected text from all completed sessions and ingest into N-gram."""
    print("=" * 60)
    print("Training N-gram Corpus from Past Sessions")
    print("=" * 60)
    
    with get_db() as conn:
        # Get all completed sessions with result_json
        cur = conn.execute(
            """
            SELECT id, filename, result_json 
            FROM transcription_sessions 
            WHERE status = 'completed' AND result_json IS NOT NULL
            ORDER BY id
            """
        )
        sessions = [dict(row) for row in cur.fetchall()]
    
    print(f"Found {len(sessions)} completed sessions")
    
    total_trigrams = 0
    total_segments = 0
    
    for session in sessions:
        result_json = session["result_json"]
        if isinstance(result_json, str):
            result_json = json.loads(result_json)
        
        segments = result_json.get("segments", [])
        if not segments:
            continue
        
        # Collect all refined text
        texts = []
        for seg in segments:
            refined = seg.get("refined_text", "")
            if refined:
                texts.append(refined)
        
        if not texts:
            continue
        
        # Ingest into N-gram
        full_text = " ".join(texts)
        trigrams = NGramAuditor.ingest_text(full_text)
        
        total_trigrams += trigrams
        total_segments += len(texts)
        
        print(f"  Session {session['id']} ({session['filename'][:30]}...): {len(texts)} segments, {trigrams} trigrams")
    
    print()
    print("=" * 60)
    print("Training Complete")
    print("=" * 60)
    print(f"Total sessions processed: {len(sessions)}")
    print(f"Total segments: {total_segments}")
    print(f"Total trigrams ingested: {total_trigrams}")
    
    # Check N-gram corpus size
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM ngram_frequency")
        count = cur.fetchone()["cnt"]
    print(f"N-gram corpus size: {count} entries")

if __name__ == "__main__":
    train_from_past_sessions()
