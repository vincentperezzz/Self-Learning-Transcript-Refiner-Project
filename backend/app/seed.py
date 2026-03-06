"""
Seed script – Populate Table A (Lexicon) and Table B (N-Gram) with
initial data derived from the reference transcripts, known Whisper errors,
and common patterns extracted from the QA RegEx Patterns catalogue.

Run:  python -m app.seed
"""

import re

from app.database import init_db, get_db


def seed_lexicon() -> int:
    """Insert known Whisper→correct mappings (Golden Rules)."""
    rules = [
        # ── Original golden rules ──
        # Whisper error -> Correct phrase, context_hint, anchor_mode
        ("over-the-recorded line", "over the recorded line", "hyphenation error", "consent_to_record"),
        ("Tamahuba", "tama ho ba", "greeting misheard", "greeting"),
        ("Asti Madrid", "SP Madrid", "law firm name misheard", "introduction"),
        ("accredited service provided in", "accredited service provider ni", "role description", "introduction"),
        ("Anna Dixman", "Anna De Guzman", "agent name misheard", None),
        ("Ana D. Guzman", "Ana de Guzman", "agent name variant", None),
        ("Ana Deguzman", "Ana de Guzman", "agent name variant", None),
        ("set up the minimum amount", "settle the minimum amount", "verb confusion", "account_status"),
        ("magaroon", "magkaroon", "spelling error", None),
        ("may settle", "ma-settle", "word boundary", "negotiation"),
        ("Be encouraged", "We encourage you", "phrasing error", None),
        ("Ms. Marina", "Ms. Marie", "name misheard", None),
        ("record deadline", "recorded line", "phonetic confusion", "consent_to_record"),
        ("spm.spmadridlaw.com", "spm@spmadridlaw.com", "email @ misheard as dot", None),
        ("SPM at SPMadridLaw.com", "spm@spmadridlaw.com", "email dictation", None),
        ("SPM at SPMadridLaw dot com", "spm@spmadridlaw.com", "email dictation", None),
        ("1delacruz@spmadridlaw.com", "jdelacruz@spmadridlaw.com", "email initial misheard", None),
        ("wandelacruz@spmadridlaw.com", "jdelacruz@spmadridlaw.com", "email name misheard", None),
        # Double-word corrections (Whisper repetition artifacts)
        ("birth date", "birthdate", "Whisper word split", None),
        ("birthdate date", "birthdate", "Whisper repetition", None),
        ("subject is subject", "subject", "Whisper repetition", "account_status"),
        ("masettle settle", "masettle", "Whisper repetition", "negotiation"),
        # Number / currency prefix normalization
        ("P5,", "\u20b15,", "currency prefix", None),
        ("P10,", "\u20b110,", "currency prefix", None),
        ("P15,", "\u20b115,", "currency prefix", None),
        ("P20,", "\u20b120,", "currency prefix", None),
        ("P25,", "\u20b125,", "currency prefix", None),
        ("P30,", "\u20b130,", "currency prefix", None),
        ("P50,", "\u20b150,", "currency prefix", None),

        # ── From RegEx Patterns CSV – Whisper misrecognitions ──
        # "best time" variants
        ("best thyme", "best time", "Whisper error: best thyme → best time", None),
        ("best tie", "best time", "Whisper error: best tie → best time", None),
        ("bess time", "best time", "Whisper error: bess time → best time", None),
        ("bet time", "best time", "Whisper error: bet time → best time", None),
        ("best item", "best time", "Whisper error: best item → best time", None),
        ("beast time", "best time", "Whisper error: beast time → best time", None),
        ("best dime", "best time", "Whisper error: best dime → best time", None),
        ("bests time", "best time", "Whisper error: bests time → best time", None),
        # "good afternoon" greeting errors
        ("grap", "good afternoon", "Whisper greeting error", None),
        ("graff", "good afternoon", "Whisper greeting error", None),
        ("graphing", "good afternoon", "Whisper greeting error", None),
        ("garafter", "good afternoon", "Whisper greeting error", None),
        ("graphter", "good afternoon", "Whisper greeting error", None),
        ("grapher", "good afternoon", "Whisper greeting error", None),
        # Birthday/birthdate errors
        ("birth tape", "birthdate", "Whisper error: birth tape → birthdate", "verification"),
        # Department errors
        ("hire department", "higher department", "Whisper error: hire → higher", None),
        # Endorse/forward variants
        ("naendorse", "na-endorse", "Whisper error: missing hyphen", None),
        ("in-endorse", "na-endorse", "Whisper error: in-endorse → na-endorse", None),
        ("binarward", "na-forward", "Whisper error: binarward → na-forward", None),
        ("na-endure", "na-endorse", "Whisper error: na-endure → na-endorse", None),
        ("fully forwarded", "fully endorsed", "Whisper error: forwarded → endorsed", None),
        ("fully underscores", "fully endorsed", "Whisper error: underscores → endorsed", None),
        ("napuli unders", "na-fully endorse", "Whisper error: napuli unders", None),
        # "as of today" errors
        ("mass of today", "as of today", "Whisper error: mass of → as of", None),
        # Hold variants
        ("mapahod", "mapahold", "Whisper error: mapahod → mapahold", None),
        ("ipahold", "ipa-hold", "Whisper error variant", None),
        # "available" spelling variants
        ("avaiable", "available", "Whisper spelling error", None),
        ("aviable", "available", "Whisper spelling error", None),
        ("availble", "available", "Whisper spelling error", None),
        ("avalible", "available", "Whisper spelling error", None),
        ("avilable", "available", "Whisper spelling error", None),
        ("availaable", "available", "Whisper spelling error", None),
        ("avlable", "available", "Whisper spelling error", None),
        ("availabe", "available", "Whisper spelling error", None),
        ("aviablle", "available", "Whisper spelling error", None),
        # Receive variants
        ("nakareceive", "naka-receive", "Whisper error: missing hyphen", None),
        ("nareceive", "na-receive", "Whisper error: missing hyphen", None),
        # Amnesty errors
        ("amnesia promo", "amnesty promo", "Whisper error: amnesia → amnesty", None),
        ("amnesia program", "amnesty program", "Whisper error: amnesia → amnesty", None),
    ]

    count = 0
    with get_db() as conn:
        for wrong, correct, hint, mode in rules:
            conn.execute(
                """
                INSERT INTO lexicon
                (wrong_phrase, correct_phrase, context_hint, anchor_mode)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (wrong_phrase) DO NOTHING
                """,
                (wrong, correct, hint, mode),
            )
            count += 1
    return count


def seed_ngrams() -> int:
    """
    Ingest correct reference sentences to build baseline trigram frequencies.
    These are the *golden* transcripts from QA_Parameters.md plus common
    call-center dialogue patterns extracted from RegEx Patterns.csv.
    """
    golden_sentences = [
        # ── Agent opening patterns ──
        "Hello good morning Miss Marie Santos tama ho ba",
        "Good morning Miss Marie This is Ana de Guzman from SP Madrid Law Firm",
        "over the recorded line and accredited service provider ni Future Bank",
        "over the recorded line and accredited service provider of Future Bank",
        "Before we proceed for verification purposes only please dictate your birthdate",
        "Okay thank you for verification",

        # ── Banking / account context ──
        "I'm calling on behalf of Future Bank with regards to your past due credit card account",
        "which is subject to suspension today",
        "subject for suspension today",
        "your total amount due is",
        "the total amount due on your account",
        "your minimum amount due for immediate settlement today",
        "the minimum amount due for this billing period",
        "kailangan niyo na masettle yung minimum amount due",
        "kailangan niyo na masettle yung total amount due",
        "settling just a partial amount might not be enough to prevent the suspension",
        "the minimum amount due is designed to help keep your account in good standing",
        "baka magkaroon pa ng mas malaking impact sa credit score niyo",
        "please ensure na lang din magawan ito ng paraan today to keep your account active",
        "to keep your account stays active",
        "settlement under account number ending in",
        "at any branch of Future Bank or via online banking",

        # ── Collections patterns ──
        "Let me inform you that the line will be recorded for security purposes",
        "I'd like to inform you that the call is being recorded",
        "I'd like to inform you about the status of your account",
        "The line will be recorded for security purposes",
        "This is Jared De La Paz from SP Madrid and Associates Law Firm calling on behalf of Future Bank",
        "This is Anna Castro from SP Madrid and Associates Law Firm calling on behalf of Future Bank",
        "regarding your past due credit card account subject for suspension",
        "regarding your past credit card account subject for suspension",

        # ── Settlement / payment ──
        "Pakisend ng copy of receipt sa spm at spmadridlaw dot com",
        "Pakisend ho ng copy of receipt sa email address",
        "Pwede mag settle sa Future Bank branch or via online banking only para one day posting",
        "Once paid pakisend ng copy of receipt",

        # ── Probing / RFD / SOF ──
        "May I ask if there is a specific reason for the delay in payment",
        "is there a specific reason for the delay",
        "Ano ho pala yung magiging source of funds niyo for settlement",
        "Ano pala yung magiging source of funds niyo for settlement",
        "may we know the reason for the delay",
        "May I know your source of funds for settlement",

        # ── Empathy / negotiation ──
        "Naiintindihan ko po ang inyong sitwasyon",
        "Naintindihan ko po na mahirap",
        "I understand your situation",
        "We're here to help",
        "here to help you with your account",

        # ── Closing ──
        "If you need any assistance with the payment process feel free to reach out",
        "If you need any assistance feel free to reach out",
        "Thank you and have a good day",
        "Thank you and have a nice day",
        "Walang anuman ingat po",

        # ── Client patterns ──
        "Pwede bang i hold muna yung suspension ng account ko",
        "Hindi ko pa kasi kayang bayaran yung minimum amount due ngayon",
        "Hindi pa kasi dumadating yung remittance galing sa anak ko",
        "Babayaran ko naman pero hindi pa ngayon",
        "Nagka problema lang talaga sa finances recently",
        "Nagkaproblema lang talaga sa finances ko",
        "Sa remittance from my husband",

        # ── Taglish patterns with "ho" politeness ──
        "Ano ho pala yung magiging plan niyo for the settlement",
        "Ganun ho ba yung sitwasyon niyo ngayon",
        "Pwede ho bang malaman yung reason for the delay",
        "Tama ho ba na kayo si Miss Marie Santos",

        # ── From RegEx Patterns CSV – common call center phrases ──
        "good morning po maam",
        "good afternoon po sir",
        "good evening po",
        "this is calling from",
        "for verification purposes only",
        "please dictate your birthdate",
        "verify your birthday",
        "email address po",
        "contact number po",
        "home address po",
        "past due credit card account",
        "subject to suspension",
        "total amount due",
        "minimum amount due",
        "outstanding balance",
        "as of today",
        "account number ending in",
        "fully endorsed na po",
        "na-endorse na po",
        "na-forward na po",
        "daily interest awareness",
        "settle your account",
        "settle the balance",
        "settlement of your account",
        "capacity to pay",
        "source of funds",
        "mode of payment",
        "full payment today",
        "partial payment today",
        "commitment to pay",
        "promise to pay",
        "broken promise follow up",
        "best time to call",
        "pay in full today",
        "discounted offer po",
        "amnesty program po",
        "waiver on interest",
        "remaining balance po",
        "downpayment po",
        "maintain good standing",
        "avoid further collection efforts",
        "legal proceedings",
        "case filing",
        "higher department",
        "late fees po",
        "additional fees po",
        "good standing with the bank",
        "guaranteed loan approval",
        "reduction on interest",
        "thank you for your time",
        "maraming salamat po",
        "have a good day",
        "is there anything else",
        "online banking po",
        "mobile banking po",
        "gcash po",
        "bayad center",
        "auto deduct",
        "branch of future bank",
        "future bank online banking",
        "follow up call po",
        "confirm payment amount",
        "confirm payment method",
        "reason for broken promise",
        "set pay today",
        "new payment schedule",
        "consent to record",
        "line is being recorded",
        "will be recorded",
        "this call is being recorded",
        "alternative contact number",
        "alternative number po",
        "message for the borrower",
        "relation to the borrower",
        "as soon as possible",
        "today or tomorrow",
        "within the day po",
        "naiintindihan ko po",
        "I understand your situation",
        "we appreciate your willingness",
    ]

    from app.core.ngram_auditor import NGramAuditor

    total = 0
    for sentence in golden_sentences:
        for _ in range(10):  # baseline weight of 10
            total += NGramAuditor.ingest_text(sentence)
    return total


def main() -> None:
    print("Initialising database...")
    init_db()

    print("Seeding default admin user...")
    from app.auth import seed_default_admin
    seed_default_admin()
    print("  -> Default admin ready (admin/admin).")

    print("Seeding Lexicon (Table A)...")
    lex_count = seed_lexicon()
    print(f"  -> {lex_count} lexicon rules inserted.")

    print("Seeding N-Gram Frequencies (Table B)...")
    ngram_count = seed_ngrams()
    print(f"  -> {ngram_count} trigrams processed.")

    print("Done! Phoenix 3.0 database is ready.")


if __name__ == "__main__":
    main()
