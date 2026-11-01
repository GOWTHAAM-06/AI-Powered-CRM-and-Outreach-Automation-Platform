"""
Outreach Safety & Compliance Checker.

Validates generated outreach drafts against basic safety and compliance rules:
1. Subject length must be <= 80 characters.
2. Body length must be between 80 and 200 words.
3. Spam-trigger words/phrases are not allowed.
4. An unsubscribe/opt-out instruction must be present.
5. Links and phone numbers must exist in verified facts.
"""

import re
from typing import Dict, Any, List, Tuple


SPAM_TRIGGER_WORDS = [
    "guaranteed",
    "100% free",
    "urgent prize",
    "act now",
]

OPT_OUT_PATTERNS = [
    re.compile(r"\bunsubscribe\b", re.IGNORECASE),
    re.compile(r"\bopt[\s-]?out\b", re.IGNORECASE),
    re.compile(r"\bstop receiving\b", re.IGNORECASE),
    re.compile(r"\bdo not wish to receive\b", re.IGNORECASE),
]

URL_PATTERN = re.compile(
    r"https?://[^\s<>\"]+|www\.[^\s<>\"]+",
    re.IGNORECASE,
)

PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+\d{1,3}[\s.-]?)?(?:\d[\s.-]?){9,12}\d(?!\d)"
)


def _extract_urls(text: str) -> List[str]:
    """Extract URLs from text."""
    urls = URL_PATTERN.findall(text)
    return [url.rstrip(".,!?;:)") for url in urls]


def _normalize_phone(phone: str) -> str:
    """Normalize a phone number to its last 10 digits."""
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else digits


def _extract_phones(text: str) -> List[str]:
    """Extract phone numbers from text and normalize them."""
    return [_normalize_phone(phone) for phone in PHONE_PATTERN.findall(text)]


def _verified_fact_text(verified_facts: Dict[str, Any]) -> str:
    """Combine verified fact values into searchable text."""
    return " ".join(
        str(value)
        for value in verified_facts.values()
        if value is not None
    )


def safety_check_draft(
    draft: Dict[str, Any],
    verified_facts: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Runs all outreach safety and compliance checks.

    Returns:
        (is_safe, list_of_issues)
    """
    issues: List[str] = []

    subject = str(draft.get("subject", "") or "")
    body = str(draft.get("body", "") or "")

    # 1. Subject length
    if len(subject) > 80:
        issues.append("Subject exceeds the 80-character limit.")

    # 2. Body length
    word_count = len(body.split())
    if word_count < 80 or word_count > 200:
        issues.append(
            f"Body must contain between 80 and 200 words; found {word_count}."
        )

    # 3. Spam-trigger words/phrases
    body_lower = body.lower()
    for trigger in SPAM_TRIGGER_WORDS:
        if trigger.lower() in body_lower:
            issues.append(
                f"Spam-trigger phrase detected: '{trigger}'."
            )

    # 4. Mandatory unsubscribe / opt-out instruction
    if not any(pattern.search(body) for pattern in OPT_OUT_PATTERNS):
        issues.append(
            "Email body must contain an unsubscribe or opt-out instruction."
        )

    # 5. Links and phone numbers must be verified
    verified_text = _verified_fact_text(verified_facts)

    verified_urls = {
        url.lower().rstrip(".,!?;:)")
        for url in _extract_urls(verified_text)
    }

    verified_phones = {
        _normalize_phone(phone)
        for phone in _extract_phones(verified_text)
    }

    for url in _extract_urls(body):
        if url.lower() not in verified_urls:
            issues.append(f"Unverified link detected: '{url}'.")

    for phone in _extract_phones(body):
        if phone not in verified_phones:
            issues.append(f"Unverified phone number detected: '{phone}'.")

    return len(issues) == 0, issues