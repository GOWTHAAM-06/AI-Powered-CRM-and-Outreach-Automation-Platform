import pytest

from ai.extraction.experience_parser import parse_experience

# (text, expected_min, expected_max, expected_type)
CASES = [
    # --- ranges ---
    ("2-4 years of experience", 2, 4, "experienced"),
    ("2 to 4 years experience", 2, 4, "experienced"),
    ("2\u20134 yrs", 2, 4, "experienced"),
    ("Between 3 and 5 years of experience", 3, 5, "experienced"),
    ("0-2 years", 0, 2, "fresher"),
    ("0-1 year experience", 0, 1, "fresher"),
    ("1-3 years", 1, 3, "experienced"),
    # --- minimum / plus ---
    ("5+ years of experience", 5, None, "experienced"),
    ("minimum 3 years experience", 3, None, "experienced"),
    ("at least 2 years of relevant experience", 2, None, "experienced"),
    ("3 years or more experience", 3, None, "experienced"),
    # --- maximum ---
    ("up to 2 years of experience", 0, 2, "fresher"),
    ("less than 1 year experience", 0, 1, "fresher"),
    ("maximum 3 years experience", 0, 3, "experienced"),
    # --- keywords only ---
    ("Freshers welcome", 0, 0, "fresher"),
    ("Entry level position", 0, 0, "fresher"),
    ("Fresh graduates can apply", 0, 0, "fresher"),
    ("No experience required", 0, 0, "fresher"),
    ("Summer internship for students", 0, 0, "internship"),
    # --- months and mixed units ---
    ("6 months internship", 0, 0, "internship"),
    ("Intern - 0 to 6 months experience", 0, 0.5, "internship"),
    ("6 months to 1 year experience", 0.5, 1, "fresher"),
    ("Experience required: 0 - 6 months", 0, 0.5, "fresher"),
    # --- number words / decimals / formatting ---
    ("one to three years of experience", 1, 3, "experienced"),
    ("Two years experience in Python", 2, 2, "fresher"),
    ("3-5 yrs exp", 3, 5, "experienced"),
    ("8+ years' experience", 8, None, "experienced"),
    ("10 plus years of experience", 10, None, "experienced"),
    ("1.5 years experience", 1.5, 1.5, "fresher"),
    ("2.5-4 years", 2.5, 4, "experienced"),
    ("Experience: 4 - 6 years", 4, 6, "experienced"),
    # --- hard cases (numbers that are NOT experience) ---
    ("We are a 10 year old company hiring freshers", 0, 0, "fresher"),
    ("Founded 5 years ago, we need engineers", None, None, "unknown"),
    ("Salary 5-8 LPA, 2-4 years experience", 2, 4, "experienced"),
    ("Apply by 2026-03-15", None, None, "unknown"),
    ("Looking for a rockstar developer", None, None, "unknown"),
    ("Trainee position, 1 year experience preferred", 1, 1, "internship"),
    ("Senior role: 7 to 10 years of experience", 7, 10, "experienced"),
    ("Candidates with 3 years of experience", 3, 3, "experienced"),
    (
        "Must have 2-3 years of hands-on experience with FastAPI",
        2, 3, "experienced",
    ),
]


# Regression cases added after code review (not part of the 40 above)
EXTRA_CASES = [
    ("2 years to 4 experience", 2, 4, "experienced"),
    ("1 year - 3 experience", 1, 3, "experienced"),
    ("3 years minimum experience", 3, None, "experienced"),
    ("3 yrs min", 3, None, "experienced"),
    ("minimum 3 years", 3, None, "experienced"),
    ("5 years ago", None, None, "unknown"),
    ("bond of 2 years", None, None, "unknown"),
    ("Service bond of 2 years. Freshers welcome", 0, 0, "fresher"),
    ("3 months internship", 0, 0, "internship"),
    ("Internship duration: 3 months", 0, 0, "internship"),
    ("Notice period 3 months", None, None, "unknown"),
    ("Stipend 10000 for 6 months", None, None, "unknown"),
    ("Experience with 5 projects delivered", None, None, "unknown"),
]


def test_has_40_cases():
    assert len(CASES) == 40


@pytest.mark.parametrize("text,lo,hi,otype", CASES)
def test_rules_only(text, lo, hi, otype):
    r = parse_experience(text)  # AI is off by default
    assert r.min_experience == lo
    assert r.max_experience == hi
    assert r.opportunity_type == otype
    assert 0.0 <= r.confidence <= 1.0
    assert r.source == "rules"


@pytest.mark.parametrize("text,lo,hi,otype", EXTRA_CASES)
def test_rules_regression(text, lo, hi, otype):
    r = parse_experience(text)
    assert (r.min_experience, r.max_experience) == (lo, hi)
    assert r.opportunity_type == otype
    assert r.source == "rules"


# ---------------- AI fallback tests (mock client, no real network) ----------
class MockClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def generate(self, prompt, *args, **kwargs):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, {"total_tokens": 0}  # same shape as GeminiClient


AI_REPLY = {
    "min_experience": 3,
    "max_experience": 5,
    "opportunity_type": "experienced",
    "confidence": 0.9,
}
# rules confidence for this text is below 0.6
LOW_CONF_TEXT = "Company running for 7 years, join us"


def test_ai_disabled_by_default():
    client = MockClient(AI_REPLY)
    r = parse_experience(LOW_CONF_TEXT, client=client)  # use_ai not set
    assert client.calls == 0
    assert r.source == "rules"


def test_ai_not_called_when_rules_confident():
    client = MockClient(AI_REPLY)
    r = parse_experience("2-4 years of experience", use_ai=True, client=client)
    assert client.calls == 0
    assert r.source == "rules"


def test_ai_called_when_rules_low_confidence():
    client = MockClient(AI_REPLY)
    r = parse_experience(LOW_CONF_TEXT, use_ai=True, client=client)
    assert client.calls == 1
    assert r.source == "ai"
    assert (r.min_experience, r.max_experience) == (3, 5)


def test_ai_wrong_shape_falls_back_to_rules():
    client = MockClient({"subject": "email draft, not experience fields"})
    r = parse_experience(LOW_CONF_TEXT, use_ai=True, client=client)
    assert client.calls == 1
    assert r.source == "rules"


def test_ai_enabled_but_no_client_is_safe():
    r = parse_experience(LOW_CONF_TEXT, use_ai=True, client=None)
    assert r.source == "rules"


def test_ai_error_falls_back_to_rules():
    client = MockClient(RuntimeError("network down"))
    r = parse_experience(LOW_CONF_TEXT, use_ai=True, client=client)
    assert client.calls == 1
    assert r.source == "rules"


def _ai_reply(lo, hi, conf=0.9):
    return {
        "min_experience": lo,
        "max_experience": hi,
        "opportunity_type": "experienced",
        "confidence": conf,
    }


@pytest.mark.parametrize(
    "reply",
    [
        _ai_reply(5, 2),                     # min greater than max
        _ai_reply(-3, -1),                   # negative years
        _ai_reply(float("nan"), 2),          # not a number
        _ai_reply(1, float("inf")),          # infinite
        _ai_reply(3, 5, float("nan")),       # bad confidence
    ],
)
def test_ai_invalid_values_fall_back_to_rules(reply):
    client = MockClient(reply)
    r = parse_experience(LOW_CONF_TEXT, use_ai=True, client=client)
    assert client.calls == 1
    assert r.source == "rules"


def test_ambiguous_number_gets_low_confidence():
    # "5 years" here is not a requirement; rules cannot be sure, so the
    # confidence stays below 0.6 and the optional AI fallback can step in.
    r = parse_experience("Worked 5 years at Google before founding us")
    assert r.confidence < 0.6
