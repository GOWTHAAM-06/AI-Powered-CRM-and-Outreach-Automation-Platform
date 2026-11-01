"""Offline draft-quality evaluation suite for AI-15."""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_FILE = ROOT / "ai" / "evals" / "cases" / "test_cases.json"
RESULTS_FILE = ROOT / "ai" / "evals" / "eval_results.csv"

UNPROFESSIONAL_WORDS = {
    "freaking",
    "idiot",
    "stupid",
    "damn",
}


def word_count(text):
    """Count words consistently for draft-length evaluation."""
    return len(re.findall(r"\b[\w'-]+\b", text))


def evaluate_case(case):
    """Evaluate one saved draft and return a transparent quality report."""
    body = str(case.get("body", ""))
    subject = str(case.get("subject", ""))
    summary = str(case.get("personalization_summary", ""))
    claims = case.get("claims_used", [])
    facts = case.get("facts", {})

    # DQ06 uses a helper to construct a reliably overlong test body.
    if case.get("repeat_body"):
        body = (body + " " + case["repeat_body"] * 25).strip()

    checks = {}

    checks["subject_present"] = bool(subject.strip())
    checks["subject_length_ok"] = len(subject) <= 80
    checks["body_present"] = bool(body.strip())
    checks["body_min_length_ok"] = word_count(body) >= 20
    checks["body_max_length_ok"] = word_count(body) <= 150

    checks["has_greeting"] = bool(
        re.search(r"\b(hi|hello|dear)\b", body, re.IGNORECASE)
    )
    checks["has_closing"] = bool(
        re.search(
            r"\b(best regards|kind regards|sincerely|thank you)\b",
            body,
            re.IGNORECASE,
        )
    )
    checks["personalization_summary_present"] = bool(summary.strip())

    checks["has_role_or_skill_context"] = bool(
        re.search(
            r"\b(developer|developer role|python|fastapi|docker|role|skills)\b",
            body,
            re.IGNORECASE,
        )
    )

    checks["professional_language"] = not any(
        re.search(rf"\b{re.escape(word)}\b", body, re.IGNORECASE)
        for word in UNPROFESSIONAL_WORDS
    )

    checks["claims_present"] = isinstance(claims, list) and bool(claims)
    forbidden_phrases = case.get("forbidden_phrases", [])

    checks["no_unsupported_phrases"] = not any(
        phrase.casefold() in body.casefold()
        for phrase in forbidden_phrases
    )

    checks["claim_fact_ids_valid"] = (
        isinstance(claims, list)
        and all(
            isinstance(claim, dict)
            and bool(claim.get("fact_id"))
            and claim["fact_id"] in facts
            and bool(str(claim.get("claim", "")).strip())
            for claim in claims
        )
    )

    # Basic compensation guard: flag amounts when no salary was supplied.
    currency_pattern = r"(?:₹|\$)\s*\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?\s*LPA\b"
    salary_supplied = bool(facts.get("salary_text"))

    checks["compensation_grounded"] = (
        salary_supplied
        or not re.search(currency_pattern, body, re.IGNORECASE)
    )

    passed = sum(checks.values())
    total = len(checks)
    score = round(100 * passed / total, 2)

    # A case is considered valid only when every quality check passes.
    actual_valid = all(checks.values())

    expected_valid = case.get("expected_valid")
    expectation_match = (
        actual_valid == expected_valid
        if isinstance(expected_valid, bool)
        else None
    )

    failed_checks = [
        name for name, result in checks.items() if not result
    ]

    return {
        "case_id": case.get("id", "unknown"),
        "category": case.get("category", "uncategorized"),
        "score": score,
        "passed_checks": passed,
        "total_checks": total,
        "actual_valid": actual_valid,
        "expected_valid": expected_valid,
        "expectation_match": expectation_match,
        "failed_checks": "; ".join(failed_checks),
    }


def run_eval():
    """Load cases, score drafts, and save a CSV report."""
    if not CASES_FILE.is_file():
        print(f"ERROR: Test cases not found: {CASES_FILE}", file=sys.stderr)
        return 1

    try:
        with CASES_FILE.open("r", encoding="utf-8") as file:
            cases = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Could not load test cases: {exc}", file=sys.stderr)
        return 1

    if not isinstance(cases, list) or not cases:
        print("ERROR: Expected a non-empty JSON array.", file=sys.stderr)
        return 1

    case_ids = [case.get("id") for case in cases]
    if any(not case_id for case_id in case_ids):
        print("ERROR: Every case must have an id.", file=sys.stderr)
        return 1

    if len(set(case_ids)) != len(case_ids):
        print("ERROR: Duplicate case IDs detected.", file=sys.stderr)
        return 1

    results = [evaluate_case(case) for case in cases]

    fieldnames = list(results[0].keys())
    try:
        with RESULTS_FILE.open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
    except OSError as exc:
        print(f"ERROR: Could not save CSV report: {exc}", file=sys.stderr)
        return 1

    print("\nAI-15 Draft Quality Evaluation")
    print("=" * 72)

    for result in results:
        print(
            f'{result["case_id"]} | {result["category"]} | '
            f'{result["score"]:.2f}% | '
            f'Valid: {result["actual_valid"]} | '
            f'Failed: {result["failed_checks"] or "None"}'
        )

    average_score = sum(r["score"] for r in results) / len(results)
    expectation_results = [
        r for r in results if r["expectation_match"] is not None
    ]
    expectation_matches = sum(
        r["expectation_match"] is True for r in expectation_results
    )

    print("=" * 72)
    print(f"Cases evaluated: {len(results)}")
    print(f"Average quality score: {average_score:.2f}%")
    print(
        "Expected outcomes matched: "
        f"{expectation_matches}/{len(expectation_results)}"
    )
    print(f"CSV report: {RESULTS_FILE}")

    # A mismatch means the evaluator did not behave as the dataset expected.
    if expectation_matches != len(expectation_results):
        print("RESULT: Some expected outcomes did not match.")
        return 1

    print("RESULT: All expected outcomes matched.")
    return 0


if __name__ == "__main__":
    sys.exit(run_eval())