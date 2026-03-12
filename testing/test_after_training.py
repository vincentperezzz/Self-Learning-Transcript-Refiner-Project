#!/usr/bin/env python3
"""
Test with a more challenging transcript after training.
"""
import httpx
import time

BASE_URL = "http://localhost:8000/api/v1"

# A transcript with more complex patterns and potential transcription errors
COMPLEX_TRANSCRIPT = """0:00.0 - 0:08.0
Agent: Good morning po, eto po si Juan from ABC Collection Services. Kinakausap ko po ba si Mr. or Ms. Customer? I'm calling regarding your outstanding balance po with XYZ Bank.

0:08.0 - 0:15.0
Client: Ah oo, ako po yun. Ano po ba yung balanse ko? Kase di ko po natatandaan kung magkano pa.

0:15.0 - 0:25.0
Agent: Noted po ma'am. So according sa aming records, your total outstanding balance po is 45,293 pesos and 50 centavos. Meron ka pong mga nag-aaccumulate na interest and penalty charges po.

0:25.0 - 0:35.0
Client: Grabe naman po yun. Ang laki na pala. Pwede po ba ako mag-settle nalang ng mas mababang amount? Kasi honestly po, medyo mahirap po ang financial situation ko ngayon.

0:35.0 - 0:45.0
Agent: Naintindihan ko po ma'am. Actually meron po kaming mga available payment options for you. Pwede po tayo mag-discuss ng installment plan or kung gusto nyo po, meron din po tayong one-time settlement offer.

0:45.0 - 0:55.0
Client: Ano po ba yung one-time settlement? Mas mababa po ba yun sa 45K?

0:55.0 - 1:05.0
Agent: Yes po ma'am. So kung mag-avail po kayo ng one-time settlement, pwede na po nating i-waive yung accumulated interest and we can settle for 35,000 pesos nalang po. Pero ito po ay one-time payment, kailangan po within the week.

1:05.0 - 1:15.0
Client: Mahirap po i-produce ng one-time yung ganyan kalaking amount. Ano po yung installment option nyo?

1:15.0 - 1:25.0
Agent: For installment po ma'am, we can offer 12-month payment plan po. So monthly payment nyo po would be 4,200 pesos. May konting interest pa rin po pero mas manageable na po sya.

1:25.0 - 1:35.0
Client: Hmm, 4,200 monthly. Pwede po ba mas mababang monthly? Kasi yung budget ko po, mga 3,000 lang po kayang i-allot for this.

1:35.0 - 1:45.0
Agent: Let me check po ma'am kung pwede natin i-extend to 18 months. Sa ganun, magiging around 2,800 to 3,000 nalang po ang monthly nyo. Would that work po for you?

1:45.0 - 1:55.0
Client: Oo, mas okay na po yun sa akin. Pwede po yun. Kailan po ang first payment?

1:55.0 - 2:05.0
Agent: Great po ma'am! First payment po would be on March 25, 2026. Then every 25th of the month po for the succeeding months. Pwede nyo po i-arrange through GCash, bank transfer, or any 7-Eleven store.

2:05.0 - 2:15.0
Client: Sige po, mag-GCash nalang po ako. Pwede po ba nyo i-text yung details sa number ko?

2:15.0 - 2:25.0
Agent: Yes po ma'am, i-seend ko po sa registered mobile number nyo lahat ng details including the payment instructions and reference number. Meron pa po kayong tanong ma'am?

2:25.0 - 2:35.0
Client: Wala na po. Salamat sa tulong nyo po ha. Sana po matulungan nyo pa rin ako kung may problem.

2:35.0 - 2:45.0
Agent: You're welcome po ma'am. If you need any assistance, you can always call our hotline 1-800-ABC-HELP. Thank you for choosing to settle your account po. Have a great day and God bless!
"""

def login():
    """Login and get access token."""
    data = {"username": "admin", "password": "admin"}
    r = httpx.post(f"{BASE_URL}/auth/login", data=data)
    return r.json().get("access_token")

def import_text(token: str, text: str) -> dict:
    """Import transcript and wait for processing."""
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.post(f"{BASE_URL}/import-text", json={"text": text}, headers=headers, timeout=30.0)
    session_key = r.json().get("session_key")
    
    for _ in range(60):
        r = httpx.get(f"{BASE_URL}/sessions/{session_key}", headers=headers)
        if r.status_code == 200:
            session = r.json()
            if session.get("status") == "completed":
                return session
            elif session.get("status") == "failed":
                return None
        time.sleep(1)
        print(".", end="", flush=True)
    return None

def get_token_stats(token: str) -> dict:
    """Get current token usage stats."""
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.get(f"{BASE_URL}/token-stats", headers=headers)
    return r.json() if r.status_code == 200 else {}

def main():
    print("=" * 60)
    print("Post-Training Learning Test")
    print("=" * 60)
    
    token = login()
    if not token:
        print("Login failed")
        return
    
    results = []
    
    for run in range(1, 3):  # Just 2 runs this time
        print(f"\n--- Run {run} (Complex Transcript) ---")
        
        stats_before = get_token_stats(token)
        tokens_before = stats_before.get("total_tokens", 0)
        
        session = import_text(token, COMPLEX_TRANSCRIPT)
        
        if session:
            stats_after = get_token_stats(token)
            tokens_used = stats_after.get("total_tokens", 0) - tokens_before
            
            results.append({
                "run": run,
                "tokens_used": tokens_used,
                "corrections": session.get("total_corrections", 0),
            })
            
            print(f"\nRun {run}: {tokens_used} tokens, {session.get('total_corrections', 0)} corrections")
        
        time.sleep(2)
    
    print("\n" + "=" * 60)
    print("Results after bulk N-gram training:")
    print("=" * 60)
    for r in results:
        print(f"Run {r['run']}: {r['tokens_used']} tokens, {r['corrections']} corrections")
    
    if len(results) >= 2:
        reduction = results[0]["tokens_used"] - results[1]["tokens_used"]
        pct = (reduction / results[0]["tokens_used"] * 100) if results[0]["tokens_used"] > 0 else 0
        print(f"\nToken reduction: {reduction} ({pct:.1f}%)")

if __name__ == "__main__":
    main()
