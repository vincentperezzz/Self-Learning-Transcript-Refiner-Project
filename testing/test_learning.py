#!/usr/bin/env python3
"""
Test script to verify that API costs reduce over time as the system learns.
We'll import the same transcript multiple times and compare token usage.
"""
import httpx
import json
import time

BASE_URL = "http://localhost:8000/api/v1"

# Sample transcript (short, for testing)
SAMPLE_TRANSCRIPT = """0:00.0 - 0:05.0
Agent: Good morning po, this is John from ABC Collections. Sino po ang kausap ko?

0:05.0 - 0:10.0
Client: Ah, eto po si Maria. Ano po yun?

0:10.0 - 0:15.0
Agent: Ma'am Maria, kinakausap ko po kayo regarding your outstanding balance sa XYZ Bank.

0:15.0 - 0:20.0
Client: Ah yung balanse ko po ba? Magkano na po ba yun?

0:20.0 - 0:25.0
Agent: Yes po, your total outstanding balance is 15,000 pesos po.

0:25.0 - 0:30.0
Client: Ay ang laki naman nun. Pwede po ba mag-installment?

0:30.0 - 0:35.0
Agent: Yes po ma'am, meron po tayong installment plan. Would you like to avail po?

0:35.0 - 0:40.0
Client: Oo nga po. Paano po ang process?

0:40.0 - 0:45.0
Agent: I-explain ko po ma'am. Kailangan po natin ng down payment of 3,000 pesos.

0:45.0 - 0:50.0
Client: Sige po, pwede po yun. Kelan po ang due date?
"""

def login():
    """Login and get access token."""
    print("Logging in as admin...")
    data = {"username": "admin", "password": "admin"}
    r = httpx.post(f"{BASE_URL}/auth/login", data=data)
    if r.status_code != 200:
        print(f"Login failed: {r.status_code} - {r.text}")
        return None
    token = r.json().get("access_token")
    print(f"Got token: {token[:20]}...")
    return token

def import_text(token: str, text: str) -> dict:
    """Import a plain text transcript and wait for processing."""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"text": text}
    
    print("Importing transcript...")
    r = httpx.post(f"{BASE_URL}/import-text", json=payload, headers=headers, timeout=30.0)
    if r.status_code != 200:
        print(f"Import failed: {r.status_code} - {r.text}")
        return None
    result = r.json()
    session_key = result.get("session_key")
    print(f"Created session: {session_key}")
    
    # Wait for processing to complete
    for _ in range(30):  # Max 30 seconds
        r = httpx.get(f"{BASE_URL}/sessions/{session_key}", headers=headers)
        if r.status_code == 200:
            session = r.json()
            if session.get("status") == "completed":
                return session
            elif session.get("status") == "failed":
                print(f"Processing failed: {session.get('error_message')}")
                return None
        time.sleep(1)
        print(".", end="", flush=True)
    
    print("\nTimeout waiting for processing")
    return None

def get_token_stats(token: str) -> dict:
    """Get current token usage stats."""
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.get(f"{BASE_URL}/token-stats", headers=headers)
    if r.status_code == 200:
        return r.json()
    return {}

def main():
    print("=" * 60)
    print("Learning Efficiency Test")
    print("=" * 60)
    
    token = login()
    if not token:
        return
    
    results = []
    
    # Run 3 imports of the same transcript
    for run in range(1, 4):
        print(f"\n--- Run {run} ---")
        
        # Get token stats before
        stats_before = get_token_stats(token)
        tokens_before = stats_before.get("total_tokens", 0)
        
        # Import transcript
        session = import_text(token, SAMPLE_TRANSCRIPT)
        
        if session:
            # Get token stats after
            stats_after = get_token_stats(token)
            tokens_after = stats_after.get("total_tokens", 0)
            
            tokens_used = tokens_after - tokens_before
            corrections = session.get("total_corrections", 0)
            
            results.append({
                "run": run,
                "tokens_used": tokens_used,
                "corrections": corrections,
                "session_tokens": session.get("tokens_used", 0),
            })
            
            print(f"\nRun {run} results:")
            print(f"  Tokens used: {tokens_used}")
            print(f"  Corrections: {corrections}")
            print(f"  Session tokens: {session.get('tokens_used', 0)}")
        
        # Small delay between runs
        time.sleep(2)
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for r in results:
        print(f"Run {r['run']}: {r['tokens_used']} tokens, {r['corrections']} corrections")
    
    if len(results) >= 2:
        reduction = results[0]["tokens_used"] - results[-1]["tokens_used"]
        print(f"\nToken reduction from Run 1 to Run {len(results)}: {reduction}")

if __name__ == "__main__":
    main()
