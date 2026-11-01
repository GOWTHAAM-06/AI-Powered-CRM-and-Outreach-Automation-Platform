
"""AI-05: Experience range parser (hard cases).

Extracts (min_experience, max_experience, opportunity_type, confidence) from
messy job-description text.

Flow:
  1. Regex rules run first (fast, free, predictable).
  2. If rule confidence < CONFIDENCE_THRESHOLD AND the caller explicitly turns
     AI on AND passes a client, we ask the LLM (Gemini Flash) as a fallback.
  3. AI fallback is OFF by default.

Only the standard library is used (requirements.txt is lead-only).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional, Protocol

CONFIDENCE_THRESHOLD = 0.6
VALID_TYPES = ("fresher", "internship", "experienced", "unknown")


# --------------------------------------------------------------------------
# Result object
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ExperienceResult:
    min_experience: Optional[float]  # in years
    max_experience: Optional[float]  # in years (None = no upper limit)
    opportunity_type: str            # fresher/internship/experienced/unknown
    confidence: float                # 0.0 - 1.0
    source: str = "rules"            # "rules" or "ai"


class LLMClient(Protocol):
    """Same shape as ai.gemini_client.GeminiClient:
    generate(prompt) -> (parsed_json_dict, token_usage_dict)."""

    def generate(self, prompt: str, *args, **kwargs): ...


# --------------------------------------------------------------------------
# Step 1: clean the text
# --------------------------------------------------------------------------
_WORD_NUMS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10",
}


def _normalize(text: str) -> str:
    t = text.lower()
    for dash in ("\u2013", "\u2014", "\u2212"):  # en dash, em dash, minus
        t = t.replace(dash, "-")
    for word, digit in _WORD_NUMS.items():
        t = re.sub(rf"\b{word}\b", digit, t)
    return t


# --------------------------------------------------------------------------
# Step 2: regex rules
# --------------------------------------------------------------------------
_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(years?|yrs?|months?|mos?)\b"

_RANGE = re.compile(
    rf"{_NUM}\s*(?:{_UNIT})?\s*(?:-|to)\s*{_NUM}\s*\+?\s*{_UNIT}"
)
_RANGE_SHARED = re.compile(
    rf"{_NUM}\s*{_UNIT}\s*(?:-|to)\s*{_NUM}"
    rf"(?=\s*\+?\s*(?:experience|exp\b))"
)
_BETWEEN = re.compile(
    rf"between\s+{_NUM}\s*(?:{_UNIT})?\s+and\s+{_NUM}\s*{_UNIT}"
)
_MAX = re.compile(
    rf"\b(?:up to|upto|maximum|max\.?|less than|under|below|"
    rf"not more than)\s*{_NUM}\s*{_UNIT}"
)
_MIN = re.compile(
    rf"\b(?:minimum of|minimum|min\.?|at least|atleast|more than|over)"
    rf"\s*{_NUM}\s*\+?\s*{_UNIT}"
)
_PLUS = re.compile(rf"{_NUM}\s*(?:\+|plus)\s*{_UNIT}")
_PLUS_AFTER = re.compile(
    rf"{_NUM}\s*{_UNIT}\s*"
    rf"(?:or more|and above|or above|and up|minimum|min\b)"
)
_EXACT = re.compile(rf"{_NUM}\s*{_UNIT}")

# (name, regex, base confidence). Order matters: specific patterns first.
_PATTERNS = [
    ("range", _RANGE, 0.90),
    ("range_shared", _RANGE_SHARED, 0.90),
    ("between", _BETWEEN, 0.90),
    ("max", _MAX, 0.80),
    ("min", _MIN, 0.85),
    ("plus", _PLUS, 0.85),
    ("plus", _PLUS_AFTER, 0.85),
    ("exact", _EXACT, 0.75),
]

# Numbers that are NOT experience requirements ("6 months internship",
# "10 year old company", "5 years ago", "bond of 2 years" ...)
_SKIP_AFTER = re.compile(
    r"\s*(?:internship|intern\b|duration|contract|training|old\b|ago\b|"
    r"in business|of operations)"
)
_SKIP_BEFORE = re.compile(
    r"(?:duration|stipend|bond|notice period)[^.\n]{0,20}$"
)

_EXPERIENCE_WORDS = re.compile(
    r"\b(?:experience|exp|relevant|hands-on)\b"
)
_NO_EXPERIENCE = re.compile(
    r"\bno (?:prior |previous |relevant )?experience\b"
)
_FRESHER_WORDS = re.compile(
    r"\b(?:freshers?|fresh graduates?|recent graduates?|new grads?|"
    r"entry[- ]level|campus hire)\b"
)
_INTERN_WORDS = re.compile(
    r"\b(?:intern|interns|internship|internships|trainee|apprentice)\b"
)

_NO_CONTEXT_PENALTY = 0.20


def _to_years(value: str, unit: str) -> float:
    v = float(value)
    return round(v / 12, 2) if unit.startswith("m") else v


def _is_skipped(text: str, start: int, end: int) -> bool:
    if _SKIP_AFTER.match(text[end:end + 25]):
        return True
    return bool(_SKIP_BEFORE.search(text[max(0, start - 30):start]))


def _has_experience_context(
    text: str, start: int, end: int, window: int = 40
) -> bool:
    chunk = text[max(0, start - window):end + window]
    return bool(_EXPERIENCE_WORDS.search(chunk))


def _find_numbers(text: str):
    """Return (min, max, confidence) or None if no experience number found."""
    for kind, pattern, base in _PATTERNS:
        for m in pattern.finditer(text):
            if _is_skipped(text, m.start(), m.end()):
                continue

            if kind in ("range", "between", "range_shared"):
                if kind == "range_shared":
                    n1, u1, n2 = m.groups()
                    u2 = u1
                else:
                    n1, u1, n2, u2 = m.groups()
                lo = _to_years(n1, u1 or u2)
                hi = _to_years(n2, u2)
                if lo > hi:
                    lo, hi = hi, lo
            else:
                n, u = m.groups()
                val = _to_years(n, u)
                if kind == "max":
                    lo, hi = 0.0, val
                elif kind in ("min", "plus"):
                    lo, hi = val, None
                else:  # exact
                    lo, hi = val, val

            conf = base
            if not _has_experience_context(text, m.start(), m.end()):
                conf -= _NO_CONTEXT_PENALTY
            return lo, hi, round(conf, 2)
    return None


def _classify(
    lo: Optional[float], hi: Optional[float], is_intern: bool
) -> str:
    if is_intern:
        return "internship"
    if lo is None and hi is None:
        return "unknown"
    if (hi is not None and hi <= 2) or (hi is None and lo == 0):
        return "fresher"
    return "experienced"


def _parse_with_rules(text: str) -> ExperienceResult:
    t = _normalize(text or "")
    is_intern = bool(_INTERN_WORDS.search(t))

    found = _find_numbers(t)
    if found:
        lo, hi, conf = found
    elif _NO_EXPERIENCE.search(t):
        lo, hi, conf = 0.0, 0.0, 0.85
    elif _FRESHER_WORDS.search(t) or is_intern:
        lo, hi, conf = 0.0, 0.0, 0.80
    else:
        return ExperienceResult(None, None, "unknown", 0.0)

    return ExperienceResult(lo, hi, _classify(lo, hi, is_intern), conf)


# --------------------------------------------------------------------------
# Step 3: optional AI fallback (disabled by default)
# --------------------------------------------------------------------------
_AI_PROMPT = (
    "Extract the work-experience requirement from this job text.\n"
    "Return ONLY JSON like: "
    '{{"min_experience": number|null, "max_experience": number|null, '
    '"opportunity_type": "fresher"|"internship"|"experienced"|"unknown", '
    '"confidence": number between 0 and 1}}\n'
    "Use years (convert months to years). Use null if not stated.\n"
    "Job text: {text}"
)


def _num_or_none(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    return float(value)


def _is_valid_ai_range(lo: Optional[float], hi: Optional[float]) -> bool:
    """Reject nan/inf, negative years, and min greater than max."""
    for v in (lo, hi):
        if v is not None and (not math.isfinite(v) or v < 0):
            return False
    return lo is None or hi is None or lo <= hi


def _parse_with_ai(
    text: str, client: LLMClient
) -> Optional[ExperienceResult]:
    try:
        data, _usage = client.generate(_AI_PROMPT.format(text=text))
        if not isinstance(data, dict):
            return None
        # e.g. GeminiClient mock mode returns an email draft, not our fields
        if "min_experience" not in data and "max_experience" not in data:
            return None
        lo = _num_or_none(data.get("min_experience"))
        hi = _num_or_none(data.get("max_experience"))
        if not _is_valid_ai_range(lo, hi):
            return None
        otype = data.get("opportunity_type")
        if otype not in VALID_TYPES:
            otype = "unknown"
        conf = float(data.get("confidence", 0.0))
        if not math.isfinite(conf):
            return None
        conf = max(0.0, min(1.0, conf))
        return ExperienceResult(lo, hi, otype, conf, source="ai")
    except Exception:  # network error, bad data, anything -> ignore AI
        return None


# --------------------------------------------------------------------------
# Public function
# --------------------------------------------------------------------------
def parse_experience(
    text: str,
    use_ai: bool = False,
    client: Optional[LLMClient] = None,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> ExperienceResult:
    """Parse experience range. Rules first; AI only if use_ai=True, a client
    is given, and rule confidence is below `threshold`."""
    rules = _parse_with_rules(text)
    if rules.confidence >= threshold or not use_ai or client is None:
        return rules

    ai = _parse_with_ai(text, client)
    if ai is not None and ai.confidence > rules.confidence:
        return ai
    return rules
