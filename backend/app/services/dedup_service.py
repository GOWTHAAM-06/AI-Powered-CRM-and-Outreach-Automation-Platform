
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional


# Remove common legal suffixes from company names.
COMPANY_SUFFIX_REGEX = re.compile(
    r"\b(?:private\s+limited|pvt\.?\s*ltd\.?|limited|ltd\.?|"
    r"incorporated|inc\.?|corporation|corp\.?|llc|llp|plc)\b",
    re.IGNORECASE,
)

# Replace punctuation with spaces.
PUNCTUATION_REGEX = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_company_name(name: str) -> str:
    """Normalize a company name for comparison."""
    if not name:
        return ""

    cleaned = name.casefold()
    cleaned = COMPANY_SUFFIX_REGEX.sub(" ", cleaned)
    cleaned = PUNCTUATION_REGEX.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_job_title(title: str) -> str:
    """Normalize a job title for comparison."""
    if not title:
        return ""

    cleaned = title.casefold()
    cleaned = PUNCTUATION_REGEX.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _get_value(record: Any, key: str) -> Any:
    """Read a value from a dictionary or an object."""
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def _same_nonempty_value(first: Any, second: Any) -> bool:
    """Compare identifiers only when both values are present."""
    if first is None or second is None:
        return False

    first_text = str(first).strip()
    second_text = str(second).strip()
    return bool(first_text and second_text and first_text == second_text)


def _similarity(first: str, second: str) -> float:
    """Return a similarity score between 0.0 and 1.0."""
    if not first or not second:
        return 0.0

    return SequenceMatcher(None, first, second).ratio()


def check_for_duplicates(
    source_id: str,
    source_identifier: str,
    source_url: str,
    company_name: str,
    title: str,
    location: Optional[str] = None,
    existing_records: Optional[List[Any]] = None,
    similarity_threshold: float = 0.85,
) -> Dict[str, Any]:
    """Find exact matches and suggest potential duplicates for review."""
    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError(
            "similarity_threshold must be between 0.0 and 1.0"
        )

    normalized_company = normalize_company_name(company_name)
    normalized_title = normalize_job_title(title)
    records = existing_records if existing_records is not None else []

    # Find exact source matches first.
    for record in records:
        record_source_id = _get_value(record, "source_id")
        record_identifier = _get_value(record, "source_identifier")
        record_url = _get_value(record, "source_url")

        same_source = (
            _same_nonempty_value(source_id, record_source_id)
            and _same_nonempty_value(
                source_identifier, record_identifier
            )
        )
        same_url = _same_nonempty_value(source_url, record_url)

        if same_source or same_url:
            return {
                "normalized_company": normalized_company,
                "normalized_title": normalized_title,
                "is_exact_source_match": True,
                "existing_match_id": _get_value(record, "id"),
                "match_reason": (
                    "source_id_and_identifier"
                    if same_source
                    else "source_url"
                ),
                "potential_duplicates": [],
            }

    # No exact match: find possible duplicates.
    potential_duplicates = []

    for record in records:
        record_company = normalize_company_name(
            _get_value(record, "company_name")
            or _get_value(record, "company")
            or ""
        )
        record_title = normalize_job_title(
            _get_value(record, "title") or ""
        )

        company_score = _similarity(
            normalized_company, record_company
        )
        title_score = _similarity(normalized_title, record_title)

        same_company = (
            bool(normalized_company)
            and normalized_company == record_company
        )
        similar_company_and_title = (
            bool(normalized_company)
            and bool(normalized_title)
            and bool(record_company)
            and bool(record_title)
            and company_score >= similarity_threshold
            and title_score >= similarity_threshold
        )

        if not (same_company or similar_company_and_title):
            continue

        record_location = _get_value(record, "location")
        location_matches = (
            not location
            or not record_location
            or str(location).strip().casefold()
            == str(record_location).strip().casefold()
        )

        potential_duplicates.append(
            {
                "id": _get_value(record, "id"),
                "company_name": (
                    _get_value(record, "company_name")
                    or _get_value(record, "company")
                ),
                "title": _get_value(record, "title"),
                "company_similarity": round(company_score, 3),
                "title_similarity": round(title_score, 3),
                "location_matches": location_matches,
                "review_required": True,
            }
        )

    potential_duplicates.sort(
        key=lambda item: (
            item["company_similarity"],
            item["title_similarity"],
        ),
        reverse=True,
    )

    return {
        "normalized_company": normalized_company,
        "normalized_title": normalized_title,
        "is_exact_source_match": False,
        "existing_match_id": None,
        "match_reason": None,
        "potential_duplicates": potential_duplicates,
    }
