"""
Seed script – Populate Table A (Lexicon) and Table B (N-Gram) with
initial data derived from the reference transcripts and known Whisper errors.

Run:  python -m app.seed
"""

from app.database import init_db, get_db


def seed_lexicon() -> int:
    """Insert known Whisper→correct mappings (Golden Rules)."""
    rules = [
        # Whisper error -> Correct phrase, context_hint, anchor_mode
        ("over-the-recorded line", "over the recorded line", "hyphenation error", "collections"),
        ("Tamahuba", "tama ho ba", "greeting misheard", None),
        ("Asti Madrid", "SP Madrid", "law firm name misheard", "collections"),
        ("accredited service provided in", "accredited service provider ni", "role description", "collections"),
        ("Anna Dixman", "Anna De Guzman", "agent name misheard", None),
        ("Ana D. Guzman", "Ana de Guzman", "agent name variant", None),
        ("Ana Deguzman", "Ana de Guzman", "agent name variant", None),
        ("set up the minimum amount", "settle the minimum amount", "verb confusion", "banking"),
        ("magaroon", "magkaroon", "spelling error", None),
        ("may settle", "ma-settle", "word boundary", "banking"),
        ("Be encouraged", "We encourage you", "phrasing error", None),
        ("Ms. Marina", "Ms. Marie", "name misheard", None),
        ("record deadline", "recorded line", "phonetic confusion", "collections"),
        ("spm.spmadridlaw.com", "spm@spmadridlaw.com", "email @ misheard as dot", "collections"),
        ("1delacruz@spmadridlaw.com", "jdelacruz@spmadridlaw.com", "email initial misheard", None),
        ("wandelacruz@spmadridlaw.com", "jdelacruz@spmadridlaw.com", "email name misheard", None),
    ]

    count = 0
    with get_db() as conn:
        for wrong, correct, hint, mode in rules:
            conn.execute(
                """
                INSERT INTO lexicon
                (wrong_phrase, correct_phrase, context_hint, anchor_mode)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (wrong_phrase, correct_phrase) DO NOTHING
                """,
                (wrong, correct, hint, mode),
            )
            count += 1
    return count


def seed_ngrams() -> int:
    """
    Ingest correct reference sentences to build baseline trigram frequencies.
    These are the *golden* transcripts from QA_Parameters.md.
    """
    golden_sentences = [
        # Agent opening patterns
        "Hello good morning Miss Marie Santos tama ho ba",
        "Good morning Miss Marie This is Ana de Guzman from SP Madrid Law Firm",
        "over the recorded line and accredited service provider ni Future Bank",
        "over the recorded line and accredited service provider of Future Bank",
        "Before we proceed for verification purposes only please dictate your birthdate",
        "Okay thank you for verification",
        # Banking / account context
        "I'm calling on behalf of Future Bank with regards to your past due credit card account",
        "which is subject to suspension today",
        "subject for suspension today",
        "your total amount due is",
        "your minimum amount due for immediate settlement today",
        "kailangan nyo na masettle yung minimum amount due",
        "settling just a partial amount might not be enough to prevent the suspension",
        "the minimum amount due is designed to help keep your account in good standing",
        "baka magkaroon pa ng mas malaking impact sa credit score nyo",
        "please ensure na lang din magawan ito ng paraan today to keep your account active",
        "settlement under account number ending in",
        "at any branch of Future Bank or via online banking",
        # Collections patterns
        "Let me inform you that the line will be recorded for security purposes",
        "The line will be recorded for security purposes",
        "This is Jared De La Paz from SP Madrid and Associates Law Firm calling on behalf of Future Bank",
        "This is Anna Castro from SP Madrid and Associates Law Firm calling on behalf of Future Bank",
        "regarding your past due credit card account subject for suspension",
        "regarding your past credit card account subject for suspension",
        # Settlement / payment
        "Pakisend ng copy of receipt sa spm at spmadridlaw dot com",
        "Pakisend ho ng copy of receipt sa email address",
        "Pwede mag settle sa Future Bank branch or via online banking only para one day posting",
        "Once paid pakisend ng copy of receipt",
        # Probing / RFD / SOF
        "May I ask if there is a specific reason for the delay in payment",
        "Ano pala yung magiging source of funds nyo for settlement",
        "may we know the reason for the delay",
        "May I know your source of funds for settlement",
        # Empathy / negotiation
        "Naiintindihan ko po ang inyong sitwasyon",
        "Naintindihan ko po na mahirap",
        "I understand your situation",
        # Closing
        "If you need any assistance feel free to reach out",
        "Thank you and have a good day",
        "Thank you and have a nice day",
        "Walang anuman ingat po",
        # Client patterns
        "Pwede bang i hold muna yung suspension ng account ko",
        "Hindi ko pa kasi kayang bayaran yung minimum amount due ngayon",
        "Hindi pa kasi dumadating yung remittance galing sa anak ko",
        "Babayaran ko naman pero hindi pa ngayon",
        "Nagka problema lang talaga sa finances recently",
        "Sa remittance from my husband",
    ]

    from app.core.ngram_auditor import NGramAuditor

    total = 0
    # Ingest each sentence multiple times to simulate frequency weight
    for sentence in golden_sentences:
        for _ in range(10):  # baseline weight of 10
            total += NGramAuditor.ingest_text(sentence)
    return total


def main() -> None:
    print("Initialising database...")
    init_db()

    print("Seeding Lexicon (Table A)...")
    lex_count = seed_lexicon()
    print(f"  -> {lex_count} lexicon rules inserted.")

    print("Seeding N-Gram Frequencies (Table B)...")
    ngram_count = seed_ngrams()
    print(f"  -> {ngram_count} trigrams processed.")

    print("Done! Phoenix 3.0 database is ready.")


if __name__ == "__main__":
    main()
