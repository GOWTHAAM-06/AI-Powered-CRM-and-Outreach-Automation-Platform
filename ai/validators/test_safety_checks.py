"""
Tests for AI-13 Outreach Safety & Compliance Checks.
"""

from ai.validators.safety_checks import safety_check_draft


def make_body(extra_text=""):
    """Create a valid 80+ word outreach body."""
    return (
        "Hi, I came across your profile and wanted to share an opportunity "
        "that may be relevant to your experience. The role focuses on Python "
        "development, FastAPI, and Docker, and we would be happy to discuss "
        "the position and answer any questions you may have. Please review "
        "the opportunity at your convenience and let us know if you would "
        "like to continue the conversation. We can provide additional "
        "details about the role, interview process, and next steps if "
        "you are interested. If you would prefer not to receive these "
        "messages, please unsubscribe. "
        + extra_text
    )


# ---------------------------------------------------------------------------
# 1. Subject length
# ---------------------------------------------------------------------------

def test_subject_length_passes():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": make_body(),
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert is_safe
    assert issues == []


def test_subject_length_fails():
    draft = {
        "subject": "A" * 81,
        "body": make_body(),
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert not is_safe
    assert any("80-character" in issue for issue in issues)


# ---------------------------------------------------------------------------
# 2. Body length
# ---------------------------------------------------------------------------

def test_body_length_passes():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": make_body(),
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert is_safe
    assert issues == []


def test_body_length_fails():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": "Hi there. Please consider this opportunity. Unsubscribe anytime.",
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert not is_safe
    assert any("between 80 and 200 words" in issue for issue in issues)


# ---------------------------------------------------------------------------
# 3. Spam-trigger words
# ---------------------------------------------------------------------------

def test_spam_trigger_check_passes():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": make_body(),
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert is_safe
    assert issues == []


def test_spam_trigger_check_fails():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": make_body("This is a guaranteed opportunity, so act now."),
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert not is_safe
    assert any("guaranteed" in issue.lower() for issue in issues)


# ---------------------------------------------------------------------------
# 4. Mandatory unsubscribe / opt-out
# ---------------------------------------------------------------------------

def test_opt_out_check_passes():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": make_body(),
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert is_safe
    assert issues == []


def test_opt_out_check_fails():
    body = (
        "Hi, I came across your profile and wanted to share an opportunity "
        "that may be relevant to your experience. The role focuses on Python "
        "development, FastAPI, and Docker, and we would be happy to discuss "
        "the position and answer any questions you may have. Please review "
        "the opportunity at your convenience and let us know if you would "
        "like to continue the conversation with our team."
    )

    draft = {
        "subject": "Python Developer Opportunity",
        "body": body,
    }

    is_safe, issues = safety_check_draft(draft, {})

    assert not is_safe
    assert any("unsubscribe or opt-out" in issue for issue in issues)


# ---------------------------------------------------------------------------
# 5. Unverified links / phone numbers
# ---------------------------------------------------------------------------

def test_verified_contact_details_pass():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": make_body(
            "You can learn more at https://example.com or call +91 9876543210."
        ),
    }

    verified_facts = {
        "website": "https://example.com",
        "phone": "+91 9876543210",
    }

    is_safe, issues = safety_check_draft(draft, verified_facts)

    assert is_safe
    assert issues == []


def test_unverified_contact_details_fail():
    draft = {
        "subject": "Python Developer Opportunity",
        "body": make_body(
            "You can learn more at https://unverified.com or call +91 9999999999."
        ),
    }

    verified_facts = {
        "website": "https://example.com",
        "phone": "+91 9876543210",
    }

    is_safe, issues = safety_check_draft(draft, verified_facts)

    assert not is_safe
    assert any("Unverified link" in issue for issue in issues)
    assert any("Unverified phone number" in issue for issue in issues)