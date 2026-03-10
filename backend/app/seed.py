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
        ("minimum amount you", "minimum amount due", "Whisper mishearing: you → due", "account_status"),
        ("minimum amount, you", "minimum amount due", "Whisper mishearing: you → due (with comma)", "account_status"),
        ("magaroon", "magkaroon", "spelling error", None),
        ("may settle", "ma-settle", "word boundary", "negotiation"),
        ("Be encouraged", "We encourage you", "phrasing error", None),
        ("Ms. Marina", "Ms. Marie", "name misheard", None),
        ("record deadline", "recorded line", "phonetic confusion", "consent_to_record"),
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
        # Sino/Kino confusion
        ("kino", "sino", "Whisper error: kino → sino (Filipino question word)", None),
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


def seed_anchors() -> int:
    """Seed semantic anchor patterns into the database."""
    # (mode, label, pattern, weight)
    anchors = [
        # ── GREETING ──
        ("greeting", "greeting", r"(hello|good\s*(morning|afternoon|evening)|kamusta)", 1),
        # ── INTRODUCTION ──
        ("introduction", "law_firm_intro", r"(SP|Asti)\s*Madrid\s*(Law\s*Firm|and\s*Associates)", 1),
        ("introduction", "agent_intro", r"(this\s*is|ako\s*(si|po))\s*\w+.*from", 1),
        ("introduction", "on_behalf_bank", r"on\s*behalf\s*of\s*Future\s*Bank", 1),
        ("introduction", "accredited_provider", r"accredited\s*service\s*provider", 1),
        # ── CONSENT TO RECORD ──
        ("consent_to_record", "recorded_line", r"over\s*the\s*recorded\s*line", 1),
        ("consent_to_record", "consent_record", r"(line|call)\s*(will\s*be|is\s*being)\s*recorded", 1),
        # ── VERIFICATION ──
        ("verification", "identity_verification", r"(verification\s*purposes|verify\s*your\s*(birthday|identity)|dictate\s*your\s*birthdate)", 1),
        ("verification", "birthdate_check", r"(birthdate|birthday|tama\s*(ho|po)\s*ba)", 1),
        ("verification", "date_spoken", r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}[,.]?\s*\d{2,4}", 1),
        ("verification", "date_numeric", r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", 1),
        ("verification", "verification_confirmed", r"thank\s*you\s*for\s*(the\s*)?(verification|confirmation)", 1),
        # ── ACCOUNT STATUS ──
        ("account_status", "credit_card_account", r"credit\s*card\s*account", 1),
        ("account_status", "past_due", r"past\s*due", 1),
        ("account_status", "amount_due", r"(minimum|total)\s*amount\s*due", 1),
        ("account_status", "outstanding_balance", r"outstanding\s*balance", 1),
        ("account_status", "suspension_notice", r"subject\s*(for|to)\s*suspension", 1),
        ("account_status", "daily_interest", r"daily\s*interest", 1),
        # ── PROBING: RFD ──
        ("probing_rfd", "rfd_probing", r"(reason|dahilan|bakit).*(delay|hindi.*settle|past\s*due|delinquent|unsettled|napabayaan)", 1),
        ("probing_rfd", "rfd_inquiry", r"(ano|anong).*(nangyari|problem|issue).*(account|settle|delay|payment)", 1),
        ("probing_rfd", "rfd_english", r"reason\s*for\s*(the\s*)?(delay|non[- ]?payment|broken\s*promise)", 1),
        # ── PROBING: SOF ──
        ("probing_sof", "source_of_funds", r"source\s*of\s*(funds|income)", 1),
        ("probing_sof", "income_source", r"(remittance|allotment|salary|sweldo|sahod|trabaho|employed|negosyo|business)", 1),
        ("probing_sof", "capacity_to_pay", r"capacity\s*to\s*pay", 1),
        # ── NEGOTIATION ──
        ("negotiation", "settlement_request", r"(settle|settlement|mag-?settle|ma-?settle|i-?settle)\s*(of|the|your|ng|sa)?\s*(account|balance|amount)?", 1),
        ("negotiation", "pif_offer", r"(pay\s*in\s*full|full\s*payment|PIF)\s*(today|tomorrow|ngayon|bukas)?", 1),
        ("negotiation", "partial_payment", r"partial\s*(payment|amount|settle)", 1),
        ("negotiation", "find_solution", r"(magawan|gawan)\s*(ng|ito)\s*paraan", 1),
        ("negotiation", "can_you_settle", r"(makakapag-?settle|masettle|mababayaran|bayaran)", 1),
        ("negotiation", "special_offer", r"(discount|amnesty|waiver|promo|installment|restructure)", 1),
        # ── BENEFITS ──
        ("benefits", "account_benefit", r"(good\s*standing|maintain.*account|active.*account|keep.*account.*active)", 1),
        ("benefits", "credit_benefit", r"(credit\s*score|avoid.*impact|maiwasan.*impact)", 1),
        # ── CONSEQUENCES ──
        ("consequences", "suspension_warning", r"(suspension|ma-?suspend|tuloy.*suspension|i-?suspend)", 1),
        ("consequences", "escalation_warning", r"(legal\s*proceedings|case\s*filing|higher\s*department|further\s*collection|escalat)", 1),
        ("consequences", "avoidance_framing", r"(para\s*maiwasan|to\s*avoid|iwas)", 1),
        # ── PTP / COMMITMENT TO PAY ──
        ("ptp_commitment", "ptp_commitment", r"(commitment|promise)\s*to\s*pay", 1),
        ("ptp_commitment", "ptp_when", r"(kailan|when).*((mag-?bayad|settle|payment)|(babayaran|i-?settle))", 1),
        ("ptp_commitment", "borrower_agreement", r"(sige(\s*(po|ho))?|will\s*do|babayaran\s*ko|i.?ll\s*(pay|settle|see\s*what))", 1),
        # ── PAYMENT CHANNEL ──
        ("payment_channel", "payment_channel", r"(online\s*banking|mobile\s*banking|gcash|bayad\s*center|over\s*the\s*counter|branch)", 1),
        ("payment_channel", "account_number", r"account\s*number\s*(ending\s*in)?", 1),
        ("payment_channel", "proof_of_payment", r"(pakisend|send|email).*receipt", 1),
        # ── RECAP ──
        ("recap", "recap_arrangement", r"(recap|summarize|i-?summarize|recap\s*natin|napag-?usapan)", 1),
        # ── EMPATHY ──
        ("empathy", "empathy_statement", r"(naiintindihan|naintindihan|understand|i\s*understand)\s*(ko\s*po|po|your\s*situation)?", 1),
        ("empathy", "empathy_difficulty", r"(mahirap|hirap|sorry\s*to\s*hear|I.?m\s*sorry)", 1),
        # ── OBJECTION HANDLING ──
        ("objection_handling", "cant_afford", r"(hindi\s*(ko|pa)\s*(kaya|kayang)|can.?t\s*afford|wala.*pera|wala.*pambayad)", 1),
        ("objection_handling", "delay_request", r"(i-?hold\s*muna|hold\s*muna|hindi\s*pa\s*ngayon|later|mamaya|bukas)", 1),
        # ── THIRD PARTY CONTACT ──
        ("third_party", "alternative_number", r"(alternate|alternative|ibang)\s*(number|contact|phone)", 1),
        ("third_party", "relation_inquiry", r"(relation|relasyon|kamag-?anak).*borrower", 1),
        ("third_party", "best_time_to_call", r"best\s*time\s*(to\s*call|tawag)", 1),
        # ── CLOSING ──
        ("closing", "closing_greeting", r"(thank\s*you|salamat|maraming\s*salamat).*(good\s*day|nice\s*day|po)", 2),
        ("closing", "closing_simple_thanks", r"\b(salamat|thank\s*you|thanks)\b[.,!]?\s*$", 2),  # Standalone at end of segment
        ("closing", "closing_sige_salamat", r"sige.{0,10}(salamat|thank)", 2),  # "Sige, salamat"
        ("closing", "closing_courtesy", r"(walang\s*anuman|ingat\s*po|anything\s*else|assist\s*with)", 1),
        ("closing", "closing_client_thanks", r"(alright|okay)\s*(thank\s*you|salamat|po)", 1),
        ("closing", "closing_reciprocal", r"(you\s*too|ikaw\s*rin|kayo\s*rin|ingat\s*(din|rin))", 1),
        ("closing", "closing_farewell", r"(have\s*a\s*(good|nice|great)\s*day|magandang\s*araw)", 1),
        ("closing", "closing_blessing", r"(god\s*bless|ingat\s*po\s*kayo|take\s*care)", 1),
        ("closing", "closing_reach_out", r"for\s*any\s*(concern|question|inquiry).*reach\s*out", 1),
        # ── CONTACT INFO ──
        ("contact_info", "email_address", r"(email\s*address|email\s*namin|email\s*ko)", 1),
        ("contact_info", "phone_number", r"(contact\s*number|phone\s*number|cellphone\s*number|mobile\s*number)", 1),
        ("contact_info", "reference_number", r"(ticket\s*number|reference\s*number|confirmation\s*number)", 1),
        ("contact_info", "note_taking", r"(pen\s*and\s*paper|take\s*note|take\s*down|jot\s*down|i-?dedictate|dictate)", 1),
        ("contact_info", "email_detected", r"[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", 1),
    ]

    count = 0
    with get_db() as conn:
        for mode, label, pattern, weight in anchors:
            conn.execute(
                """
                INSERT INTO semantic_anchors (mode, label, pattern, weight, source)
                VALUES (%s, %s, %s, %s, 'seed')
                ON CONFLICT (mode, label) DO NOTHING
                """,
                (mode, label, pattern, weight),
            )
            count += 1
    return count


def seed_domain_glossary() -> int:
    """Seed domain-specific terms tied to anchor modes.

    These terms are fed to Gemini L3 and used for N-gram domain boost
    so the system knows the correct vocabulary for each call segment type.
    """
    terms = [
        # ── ACCOUNT_STATUS ──
        ("account_status", "minimum amount due"),
        ("account_status", "outstanding balance"),
        ("account_status", "total amount due"),
        ("account_status", "principal balance"),
        ("account_status", "past due amount"),
        ("account_status", "remaining balance"),
        ("account_status", "overdue balance"),
        ("account_status", "current balance"),
        ("account_status", "statement of account"),
        ("account_status", "credit limit"),
        ("account_status", "available credit"),
        ("account_status", "billing statement"),
        ("account_status", "account number"),
        ("account_status", "delinquent account"),
        ("account_status", "days past due"),
        ("account_status", "last payment date"),
        ("account_status", "last payment amount"),
        ("account_status", "finance charges"),
        ("account_status", "late payment charges"),
        ("account_status", "penalty charges"),
        ("account_status", "interest rate"),
        ("account_status", "annual fee"),
        # ── NEGOTIATION ──
        ("negotiation", "settlement amount"),
        ("negotiation", "payment arrangement"),
        ("negotiation", "payment plan"),
        ("negotiation", "restructure"),
        ("negotiation", "waive the charges"),
        ("negotiation", "installment plan"),
        ("negotiation", "one-time payment"),
        ("negotiation", "lump sum"),
        ("negotiation", "amnesty program"),
        ("negotiation", "amnesty promo"),
        ("negotiation", "discount offer"),
        ("negotiation", "settle the account"),
        ("negotiation", "settle the minimum amount"),
        # ── PTP_COMMITMENT ──
        ("ptp_commitment", "promise to pay"),
        ("ptp_commitment", "payment date"),
        ("ptp_commitment", "pay on or before"),
        ("ptp_commitment", "payment commitment"),
        ("ptp_commitment", "committed amount"),
        ("ptp_commitment", "due date"),
        # ── PAYMENT_CHANNEL ──
        ("payment_channel", "payment channel"),
        ("payment_channel", "online banking"),
        ("payment_channel", "over the counter"),
        ("payment_channel", "bills payment"),
        ("payment_channel", "GCash"),
        ("payment_channel", "Maya"),
        ("payment_channel", "bank transfer"),
        ("payment_channel", "payment center"),
        ("payment_channel", "convenience store"),
        ("payment_channel", "auto-debit"),
        # ── VERIFICATION ──
        ("verification", "date of birth"),
        ("verification", "birthdate"),
        ("verification", "birthday"),
        ("verification", "full name"),
        ("verification", "middle name"),
        ("verification", "billing address"),
        ("verification", "mailing address"),
        ("verification", "mother's maiden name"),
        ("verification", "verification purposes"),
        # ── GREETING ──
        ("greeting", "good morning"),
        ("greeting", "good afternoon"),
        ("greeting", "good evening"),
        # ── INTRODUCTION ──
        ("introduction", "accredited service provider"),
        ("introduction", "SP Madrid Law"),
        ("introduction", "law firm"),
        ("introduction", "calling on behalf of"),
        ("introduction", "Future Bank"),
        # ── CONSENT_TO_RECORD ──
        ("consent_to_record", "recorded line"),
        ("consent_to_record", "over the recorded line"),
        ("consent_to_record", "recording this call"),
        ("consent_to_record", "call recording"),
        # ── CONTACT_INFO ──
        ("contact_info", "contact number"),
        ("contact_info", "mobile number"),
        ("contact_info", "cellphone number"),
        ("contact_info", "email address"),
        ("contact_info", "landline number"),
        ("contact_info", "alternate number"),
        # ── CLOSING ──
        ("closing", "thank you for your time"),
        ("closing", "have a nice day"),
        ("closing", "have a good day"),
        ("closing", "goodbye"),
        ("closing", "thank you and goodbye"),
        ("closing", "anything else I can help"),
        # ── CONSEQUENCES ──
        ("consequences", "legal action"),
        ("consequences", "demand letter"),
        ("consequences", "court case"),
        ("consequences", "credit standing"),
        ("consequences", "credit report"),
        ("consequences", "endorsement to legal"),
        ("consequences", "higher department"),
        # ── BENEFITS ──
        ("benefits", "good credit standing"),
        ("benefits", "avoid additional charges"),
        ("benefits", "waiver of penalty"),
        ("benefits", "zero interest"),
        ("benefits", "clean record"),
        # ── EMPATHY ──
        ("empathy", "I understand"),
        ("empathy", "I appreciate"),
        ("empathy", "thank you for sharing"),
        ("empathy", "I hear you"),
        # ── RECAP ──
        ("recap", "to summarize"),
        ("recap", "just to recap"),
        ("recap", "so to confirm"),
        ("recap", "as discussed"),
        # ── OBJECTION_HANDLING ──
        ("objection_handling", "I understand your concern"),
        ("objection_handling", "financial difficulty"),
        ("objection_handling", "budget constraints"),
    ]

    count = 0
    with get_db() as conn:
        for mode, term in terms:
            conn.execute(
                """
                INSERT INTO domain_glossary (anchor_mode, term)
                VALUES (%s, %s)
                ON CONFLICT (anchor_mode, term) DO NOTHING
                """,
                (mode, term),
            )
            count += 1
    return count


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

    print("Seeding Semantic Anchors...")
    anchor_count = seed_anchors()
    print(f"  -> {anchor_count} anchor patterns inserted.")

    print("Seeding Domain Glossary...")
    glossary_count = seed_domain_glossary()
    print(f"  -> {glossary_count} domain terms inserted.")

    print("Done! Phoenix 3.0 database is ready.")


if __name__ == "__main__":
    main()
