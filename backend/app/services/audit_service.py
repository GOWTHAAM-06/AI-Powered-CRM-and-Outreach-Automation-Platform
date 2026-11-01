"""
Audit logging service.

Provides reusable audit-log insertion with sensitive-data redaction.
"""

import re
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

SENSITIVE_KEYWORDS = {
    "email",
    "phone",
    "phone_number",
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "authentication_token",
    "authorization",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
    "credential",
    "credentials",
}

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{7,}[0-9]$")

BEARER_TOKEN_PATTERN = re.compile(
    r"^Bearer\s+\S+$",
    re.IGNORECASE,
)

JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def _is_sensitive_string(value: str) -> bool:
    """Return True when a string looks like sensitive authentication data."""
    return bool(
        EMAIL_PATTERN.fullmatch(value)
        or PHONE_PATTERN.fullmatch(value)
        or BEARER_TOKEN_PATTERN.fullmatch(value)
        or JWT_PATTERN.fullmatch(value)
    )


def _is_sensitive_key(key: str) -> bool:
    """Return True when a field name suggests sensitive information."""
    normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())

    sensitive_terms = (
        "email",
        "phone",
        "token",
        "authorization",
        "password",
        "passwd",
        "secret",
        "apikey",
        "credential",
    )

    return any(term in normalized_key for term in sensitive_terms)


def _redact_sensitive_data(value: Any, key: str | None = None) -> Any:
    """Recursively redact sensitive values from dictionaries and lists."""
    if isinstance(value, dict):
        redacted = {}

        for item_key, item_value in value.items():
            normalized_key = str(item_key).lower()

            if _is_sensitive_key(normalized_key):
                redacted[item_key] = "[REDACTED]"
            else:
                redacted[item_key] = _redact_sensitive_data(
                    item_value,
                    key=normalized_key,
                )

        return redacted

    if isinstance(value, list):
        return [_redact_sensitive_data(item, key=key) for item in value]

    if isinstance(value, tuple):
        return tuple(_redact_sensitive_data(item, key=key) for item in value)

    if isinstance(value, str) and (
        key in SENSITIVE_KEYWORDS or _is_sensitive_string(value)
    ):
        return "[REDACTED]"
    return value


def log_action(
    conn: Connection,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    details_dict: dict[str, Any],
) -> None:
    """
    Insert an audit log entry using the caller's active transaction.

    The audit entry is committed or rolled back together with the
    transaction owned by the caller.
    """
    redacted_details = _redact_sensitive_data(details_dict)

    query = """
        INSERT INTO audit_logs (
            actor,
            action,
            entity_type,
            entity_id,
            details
        )
        VALUES (%s, %s, %s, %s, %s)
    """

    conn.execute(
        query,
        (
            actor,
            action,
            entity_type,
            entity_id,
            Jsonb(redacted_details),
        ),
    )
