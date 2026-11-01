"""Tests for audit logging and sensitive-data redaction."""

from unittest.mock import MagicMock

from backend.app.services.audit_service import (
    _redact_sensitive_data,
    log_action,
)


def test_redacts_sensitive_fields():
    """Sensitive values under sensitive keys should be masked."""
    details = {
        "email": "alisha@example.com",
        "phone": "+1 555 123 4567",
        "access_token": "secret-token-value",
        "action_note": "profile updated",
    }

    result = _redact_sensitive_data(details)

    assert result["email"] == "[REDACTED]"
    assert result["phone"] == "[REDACTED]"
    assert result["access_token"] == "[REDACTED]"
    assert result["action_note"] == "profile updated"


def test_redacts_sensitive_values_in_nested_data():
    """Sensitive values should also be masked inside nested structures."""
    details = {
        "user": {"contact": "alisha@example.com"},
        "items": [{"refresh_token": "refresh-secret"}],
    }

    result = _redact_sensitive_data(details)

    assert result["user"]["contact"] == "[REDACTED]"
    assert result["items"][0]["refresh_token"] == "[REDACTED]"


def test_log_action_inserts_redacted_details():
    """Audit insertion should pass redacted details to the connection."""
    conn = MagicMock()
    details = {
        "email": "alisha@example.com",
        "note": "profile updated",
    }

    log_action(
        conn=conn,
        actor="test-user",
        action="update",
        entity_type="contact",
        entity_id="123",
        details_dict=details,
    )

    conn.execute.assert_called_once()
    args = conn.execute.call_args.args

    assert "INSERT INTO audit_logs" in args[0]
    assert args[1][0] == "test-user"
    assert args[1][1] == "update"
    assert args[1][2] == "contact"
    assert args[1][3] == "123"
    assert args[1][4].obj["email"] == "[REDACTED]"
    assert args[1][4].obj["note"] == "profile updated"


def test_redacts_sensitive_values_with_extended_field_names():
    """Sensitive field names with prefixes should also be redacted."""
    details = {
        "user_email": "alisha@example.com",
        "phoneNumber": "+1 555 123 4567",
        "authorization": "Bearer secret-token",
        "password": "my-password",
        "api_key": "my-api-key",
        "client_secret": "my-client-secret",
    }

    result = _redact_sensitive_data(details)

    assert result["user_email"] == "[REDACTED]"
    assert result["phoneNumber"] == "[REDACTED]"
    assert result["authorization"] == "[REDACTED]"
    assert result["password"] == "[REDACTED]"
    assert result["api_key"] == "[REDACTED]"
    assert result["client_secret"] == "[REDACTED]"


def test_audit_action_uses_caller_transaction():
    """Audit logging should not commit or manage the caller's transaction."""
    conn = MagicMock()

    details = {
        "email": "alisha@example.com",
        "action": "updated contact",
    }

    log_action(
        conn=conn,
        actor="test-user",
        action="update",
        entity_type="contact",
        entity_id="123",
        details_dict=details,
    )

    conn.execute.assert_called_once()

    # log_action must not commit or rollback the caller's transaction.
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
