"""
Gemini 2.5 Flash Corrector – Layer 3.

After Lexicon (L1) and N-Gram (L2) have done their corrections, this module
sends the full transcript to Gemini for analysis of remaining errors.

Gemini acts as a "teacher":
1. Identifies Whisper transcription errors that L1/L2 couldn't catch
2. Suggests corrections in Philippine call-center + Tagalog context
3. Each correction is auto-added to the lexicon for future matching

Over time, the lexicon grows and Gemini is called less frequently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.config import GEMINI_API_KEY
from app.database import get_db

logger = logging.getLogger(__name__)

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

SYSTEM_PROMPT = """\
You are an expert QA auditor and transcript corrector for a Philippine COLLECTION \
AGENCY call center. Transcripts are produced by Whisper ASR (speech-to-text).

═══ SETTING ═══
These calls are DEBT COLLECTION calls between a Collection Agent and a Borrower/Client. \
The agency (SP Madrid Law Firm / SP Madrid and Associates) collects on behalf of \
Future Bank. Agents speak in a mix of English and Filipino/Tagalog (code-switching \
mid-sentence is NORMAL).

═══ TYPICAL CALL FLOW ═══
Collection calls follow a structured QA-graded flow. The agent is scored on each phase:

1. OPENING & GREETING (5%)
   - Must include "Kamusta" or polite greeting
   - Agent identifies self and agency: "This is [Name] from SP Madrid Law Firm"
   - Mentions "over the recorded line" / consent to record

2. ACCOUNT VERIFICATION (5%)
   - Verify borrower identity: birthdate, name confirmation
   - "tama ho ba?" / "please dictate your birthdate"

3. ACCOUNT STATUS / PURPOSE OF CALL
   - Inform about past due credit card, outstanding balance, minimum amount due
   - "subject to/for suspension today"
   - Total amount due, minimum amount due figures

4. EFFECTIVE PROBING (10%)
   - RFD (Reason for Delinquency/Delay): "bakit naging delayed ang settlement"
   - SOF (Source of Funds): "ano yung magiging source of funds niyo"
   - SOI (Source of Income): employment status, remittance, allotment

5. NEGOTIATION & HIERARCHY (10%)
   - Stick twice on Outstanding Balance (OB) before alternatives
   - Hierarchy: H1 PIF Today → H2 Partial Today → H3 PIF Tomorrow → H4 Partial arrangement
   - WIIFM (What's In It For Me) reoffer
   - Benefits: good standing, avoid further collection, credit score
   - Consequences: suspension, legal proceedings, case filing, higher department

6. COMMITMENT TO PAY / PTP (Promise To Pay)
   - Secure amount, date, and payment method
   - "commitment to pay" / "kailan at magkano"

7. SOLIDIFYING / RECAP (5%)
   - Recap arrangement: When, Amount, Payment method
   - Benefits & consequences reiteration
   - Payment channels: Future Bank branch, online banking, GCash, Bayad Center

8. CLOSING (5%)
   - Polite closing, "Thank you and have a good day" / "Walang anuman, ingat po"

═══ KEY INTENT CATEGORIES (from QA Regex Grading) ═══
These are the categories agents are graded on. Understanding them helps you \
recognize what the agent/borrower is trying to say:

OPENING: greeting_intent, introductory_intent, identified_self_and_agency_intent, \
consent_to_record_intent, line_is_recorded_intent, properly_identified_self_intent

VERIFICATION: customer_verification_intent, pid_name_intent, pid_birthday_intent, \
pid_address_intent, pid_email_intent, pid_dob_intent

ACCOUNT STATUS: account_status_intent, account_information_intent, \
explained_account_status_intent, outstanding_balance_intent, ob_intent, \
minimum_amount_intent, daily_interest_intent, inform_ob_intent, inform_due_date_intent

PROBING: rfd_intent (Reason for Delay), sof_intent (Source of Funds), \
soi_intent (Source of Income), capacity_to_pay_intent, reason_for_non_payment_today_intent, \
check_for_source_of_funds_intent, asked_if_ch_received_demand_or_notification_letter_intent

NEGOTIATION: hierarchy_pay_intent, h1_pif_today_intent, h2_wiifm_reoffer_today_intent, \
h3_pif_tomorrow_intent, h4_partial_payment_today_tomorrow_intent, \
negotiation_heirarchy_intent, stick_twice_ob_intent, closing_attempts_intent, \
four_closing_attempts_per_call_intent, buying_question_intent, objection_handling_intent

BENEFITS & CONSEQUENCES: benefits_intent, consequences_intent, \
benefits_and_consequences_discussion_intent, soft_consequences_intent

PAYMENT ARRANGEMENT: commitment_to_pay_intent, ptp_arrangement_intent, \
payment_arrangement_intent, payment_channel_intent, mode_of_payment_intent, \
amount_intent, date_intent, when_intent, secured_payment_intent

SETTLEMENT TYPES: full_payment_intent, partial_payment_intent, discounted_intent, \
installment_intent, split_intent, downpayment_intent, temporary_payment_arrangement_intent

RECAP: recap_intent, recap_amount_intent, recap_mop_intent, recap_when_intent, \
summarized_arrangement_intent

FOLLOW-UP: ffup_reason_for_broken_promise_intent, ffup_confirm_payment_amount_intent, \
ffup_confirm_payment_method_intent, ffup_ask_new_ptp_sched_intent, \
broken_promise_test_intent, follow_up_calls_intent

3RD PARTY CALLS: 3pc_alternative_number_intent, 3pc_best_time_to_call_intent, \
3pc_relation_to_borrower_intent, 3pc_borrower_address_intent, \
3pc_callback_request_intent, 3pc_message_contact_intent

EMPATHY: empathy_intent, active_listening_intent, acknowledgement_intent, \
showed_empathy_and_compassion_intent

CLOSING: closing_intent, closing_test_roni, leave_a_rope_intent, \
expect_call_back_intent, return_call_intent

═══ DOMAIN VOCABULARY ═══
Common terms in this collection context:
- OB = Outstanding Balance
- PIF = Pay In Full
- PTP = Promise To Pay
- RFD = Reason for Delinquency/Delay
- SOF = Source of Funds
- SOI = Source of Income
- WIIFM = What's In It For Me (agent reoffer technique)
- BTC = Best Time to Call
- Ben/Con = Benefits and Consequences
- MOP = Mode of Payment
- 3PC = Third Party Contact (calling someone other than the borrower)
- Past Due = Overdue amount
- Curing Amount = Amount needed to bring account current
- Amnesty = Special discount/forgiveness program
- Demand Letter / Notification Letter = formal collection notice

═══ YOUR TASK ═══
1. Identify words/phrases that are clearly Whisper transcription ERRORS.
2. Provide the correct word/phrase replacement.
3. Focus on: proper nouns, company names, Filipino/Tagalog words that Whisper \
mangled, financial terms, call-center script phrases, collection-specific terminology.

═══ RULES — DO NOT CHANGE ═══
- Correctly transcribed Tagalog/Filipino words (even if unusual to English speakers)
- Normal code-switching patterns (mixing English and Tagalog is expected)
- Words already correct even if informal
- Grammar or style (only fix ASR transcription errors, not language quality)
- Already-correct currency symbols like ₱
- Words/phrases that appear correct in context — our system handles deduplication
- NEVER change English pronouns "you", "your", "you're", "yours" to Filipino \
"po" or "por" — these are VALID English words in code-switched sentences

═══ IMPORTANT CONTEXT ═══
- "ho/po" are Filipino politeness particles — do NOT change them
- "na/ng/nyo/niyo/yung/kailangan/pasuyo/pakisend" etc. are common Tagalog words
- Company names, email addresses, and proper nouns should be preserved exactly
- Agent often says compliance phrases like "over the recorded line"
- Borrower often mentions remittance, allotment, salary as source of funds
- Common negotiation phrases: "magawan ng paraan", "i-settle", "masettle", "makakapag-settle"

Respond with EXACTLY a JSON array of correction objects. Each object must have:
- "segment_index": the 0-based index of the segment
- "original": the exact wrong word/phrase as it appears in the transcript
- "corrected": the correct replacement

If a segment needs NO corrections, omit it entirely.
If the ENTIRE transcript needs no corrections, respond with: []

RESPOND WITH ONLY THE JSON ARRAY. No explanation, no markdown fencing."""


@dataclass
class GeminiCorrection:
    """A single correction suggested by Gemini."""
    segment_index: int
    original: str
    corrected: str


def _fetch_lexicon_rules() -> list[dict]:
    """Load current lexicon rules from DB for inclusion in the Gemini prompt."""
    try:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT wrong_phrase, correct_phrase FROM lexicon "
                "ORDER BY wrong_phrase LIMIT 500"
            )
            return [{"wrong": r["wrong_phrase"], "correct": r["correct_phrase"]} for r in cur.fetchall()]
    except Exception as e:
        logger.warning("Could not load lexicon for Gemini prompt: %s", e)
        return []


def _fetch_domain_glossary() -> dict[str, list[str]]:
    """Load domain glossary terms from DB, grouped by anchor_mode."""
    try:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT anchor_mode, term FROM domain_glossary ORDER BY anchor_mode, term"
            )
            grouped: dict[str, list[str]] = {}
            for row in cur.fetchall():
                grouped.setdefault(row["anchor_mode"], []).append(row["term"])
            return grouped
    except Exception as e:
        logger.warning("Could not load domain glossary: %s", e)
        return {}


def correct_transcript_sync(
    segments: list[dict],
    low_confidence_words: list[dict] | None = None,
    applied_rules: list[tuple[str, str]] | None = None,
    unknown_words: list[dict] | None = None,
) -> list[GeminiCorrection]:
    """
    Send the full transcript to Gemini for correction analysis.

    Args:
        segments: List of dicts with keys: index, text, start, end
        low_confidence_words: Optional list of {segment_index, word, probability}
        applied_rules: Optional list of (original, corrected) tuples for rules already applied by L1
        unknown_words: Optional list of {segment_index, word} for words not found in the N-gram corpus

    Returns:
        List of GeminiCorrection objects
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — skipping Gemini correction layer")
        return []

    # Build transcript text for the prompt (include anchor mode if available)
    transcript_lines = []
    for seg in segments:
        mode_tag = f" ({seg['anchor_mode']})" if seg.get("anchor_mode") else ""
        transcript_lines.append(
            f"[{seg['index']}] [{seg['start']:.1f}s-{seg['end']:.1f}s]{mode_tag} {seg['text']}"
        )
    transcript_text = "\n".join(transcript_lines)

    # Build domain glossary section from DB
    glossary = _fetch_domain_glossary()
    glossary_text = ""
    if glossary:
        glossary_lines = []
        for mode, terms in glossary.items():
            glossary_lines.append(f"  {mode}: {', '.join(terms)}")
        glossary_text = (
            "\n\nDOMAIN GLOSSARY — Use these terms when correcting segments of each type. "
            "If a Whisper transcription sounds phonetically similar to one of these terms, "
            "prefer the domain term:\n" + "\n".join(glossary_lines)
        )

    # Build low-confidence section
    low_conf_text = ""
    if low_confidence_words:
        low_conf_lines = []
        for w in low_confidence_words:
            low_conf_lines.append(
                f"  Segment {w['segment_index']}: \"{w['word']}\" "
                f"(confidence: {w['probability']:.0%})"
            )
        low_conf_text = (
            "\n\nLOW-CONFIDENCE WORDS (Whisper was uncertain about these):\n"
            + "\n".join(low_conf_lines)
        )

    user_message = f"TRANSCRIPT:\n{transcript_text}{glossary_text}{low_conf_text}"

    # Include unknown words detected by N-gram corpus analysis
    if unknown_words:
        unk_lines = []
        for w in unknown_words:
            unk_lines.append(f"  Segment {w['segment_index']}: \"{w['word']}\"")
        user_message += (
            "\n\nUNKNOWN WORDS (not found in our N-gram corpus — likely transcription errors, pay extra attention):\n"
            + "\n".join(unk_lines)
        )

    # Include only rules already applied by L1 (not the full lexicon)
    if applied_rules:
        unique_rules = list(dict.fromkeys(applied_rules))  # deduplicate, preserve order
        rules_lines = [f"  \"{orig}\" → \"{corr}\"" for orig, corr in unique_rules]
        user_message += (
            "\n\nALREADY CORRECTED BY OUR SYSTEM (do not re-suggest these):\n"
            + "\n".join(rules_lines)
        )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT + "\n\n" + user_message}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract response text
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "[]")
            .strip()
        )

        # Clean markdown fencing if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()

        corrections_raw = json.loads(text)
        if not isinstance(corrections_raw, list):
            logger.warning("Gemini returned non-list: %s", type(corrections_raw))
            return []

        corrections = []
        for item in corrections_raw:
            if not isinstance(item, dict):
                continue
            seg_idx = item.get("segment_index")
            orig = item.get("original", "").strip()
            corr = item.get("corrected", "").strip()
            if seg_idx is not None and orig and corr and orig != corr:
                corrections.append(
                    GeminiCorrection(
                        segment_index=int(seg_idx),
                        original=orig,
                        corrected=corr,
                    )
                )

        logger.info("Gemini suggested %d corrections", len(corrections))
        return corrections

    except httpx.HTTPStatusError as e:
        logger.error("Gemini API error %d: %s", e.response.status_code, e.response.text[:300])
        return []
    except json.JSONDecodeError as e:
        logger.error("Gemini returned invalid JSON: %s", e)
        return []
    except Exception as e:
        logger.error("Gemini corrector error: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Human-guided segment correction via Gemini
# ---------------------------------------------------------------------------

_HUMAN_CORRECT_PROMPT = """\
You are a transcript corrector for a Philippine collection agency call center.

The user spotted an error in the following transcript segment and is telling you \
what needs to be fixed. Apply ONLY the correction the user describes. \
Do NOT change anything else.

SEGMENT TEXT:
{segment_text}

USER INSTRUCTION:
{user_instruction}

Respond with EXACTLY a JSON object:
{{
  "corrected_text": "<the full corrected segment text>",
  "changes": [
    {{"original": "<wrong phrase>", "corrected": "<correct phrase>"}}
  ]
}}

If the user instruction is unclear or no change is needed, return:
{{"corrected_text": "<original text unchanged>", "changes": []}}

RESPOND WITH ONLY THE JSON OBJECT. No explanation, no markdown fencing."""


def correct_segment_with_instruction(
    segment_text: str,
    user_instruction: str,
) -> dict:
    """
    Send a single segment + human instruction to Gemini for targeted correction.

    Returns dict with keys: corrected_text, changes (list of {original, corrected})
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set")
        return {"corrected_text": segment_text, "changes": []}

    prompt = _HUMAN_CORRECT_PROMPT.format(
        segment_text=segment_text,
        user_instruction=user_instruction,
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "{}")
            .strip()
        )

        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()

        result = json.loads(text)
        if not isinstance(result, dict) or "corrected_text" not in result:
            logger.warning("Gemini human-correct returned unexpected format")
            return {"corrected_text": segment_text, "changes": []}

        return result

    except Exception as e:
        logger.error("Gemini human-correct error: %s", e, exc_info=True)
        return {"corrected_text": segment_text, "changes": []}
