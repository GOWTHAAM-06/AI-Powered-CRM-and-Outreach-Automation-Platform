
import pytest

from backend.app.services.dedup_service import (
    normalize_company_name,
    normalize_job_title,
    check_for_duplicates,
)


def test_company_name_lowercase():
    assert normalize_company_name("ACME TECHNOLOGIES") == "acme technologies"


def test_company_name_extra_spaces():
    assert normalize_company_name("  Acme   Technologies  ") == "acme technologies"


def test_company_name_removes_pvt_ltd():
    assert normalize_company_name("Acme Technologies Pvt. Ltd.") == "acme technologies"


def test_company_name_removes_limited():
    assert normalize_company_name("Acme Limited") == "acme"


def test_company_name_removes_punctuation():
    assert normalize_company_name("Acme, Technologies!") == "acme technologies"


def test_empty_company_name():
    assert normalize_company_name("") == ""


def test_job_title_lowercase():
    assert normalize_job_title("SOFTWARE ENGINEER") == "software engineer"


def test_job_title_extra_spaces():
    assert normalize_job_title("  Software   Engineer  ") == "software engineer"


def test_job_title_removes_punctuation():
    assert normalize_job_title("Software-Engineer!") == "software engineer"


def test_empty_job_title():
    assert normalize_job_title("") == ""


def test_no_existing_records():
    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-101",
        source_url="https://example.com/job-101",
        company_name="Acme Technologies",
        title="Software Engineer",
        existing_records=[],
    )

    assert result["is_exact_source_match"] is False
    assert result["existing_match_id"] is None
    assert result["potential_duplicates"] == []


def test_exact_source_match():
    records = [
        {
            "id": 1,
            "source_id": "linkedin",
            "source_identifier": "job-101",
            "source_url": "https://example.com/job-101",
            "company_name": "Acme Technologies",
            "title": "Software Engineer",
        }
    ]

    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-101",
        source_url="https://example.com/new-url",
        company_name="Acme Technologies",
        title="Software Engineer",
        existing_records=records,
    )

    assert result["is_exact_source_match"] is True
    assert result["existing_match_id"] == 1
    assert result["match_reason"] == "source_id_and_identifier"


def test_exact_url_match():
    records = [
        {
            "id": 2,
            "source_id": "indeed",
            "source_identifier": "job-202",
            "source_url": "https://example.com/job-202",
            "company_name": "Other Company",
            "title": "Developer",
        }
    ]

    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-999",
        source_url="https://example.com/job-202",
        company_name="New Company",
        title="New Role",
        existing_records=records,
    )

    assert result["is_exact_source_match"] is True
    assert result["existing_match_id"] == 2
    assert result["match_reason"] == "source_url"


def test_different_records_are_not_exact_matches():
    records = [
        {
            "id": 3,
            "source_id": "linkedin",
            "source_identifier": "job-old",
            "source_url": "https://example.com/old",
            "company_name": "Sunrise Foods",
            "title": "Accountant",
        }
    ]

    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-new",
        source_url="https://example.com/new",
        company_name="Oceanic Software",
        title="Developer",
        existing_records=records,
    )

    assert result["is_exact_source_match"] is False
    assert result["existing_match_id"] is None
    assert result["potential_duplicates"] == []


def test_same_company_and_title_suggest_duplicate():
    records = [
        {
            "id": 4,
            "source_id": "indeed",
            "source_identifier": "job-404",
            "source_url": "https://example.com/job-404",
            "company_name": "Acme Technologies Pvt. Ltd.",
            "title": "Software Engineer",
        }
    ]

    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-505",
        source_url="https://example.com/job-505",
        company_name="Acme Technologies",
        title="Software Engineer",
        existing_records=records,
    )

    assert len(result["potential_duplicates"]) == 1
    assert result["potential_duplicates"][0]["id"] == 4
    assert result["potential_duplicates"][0]["review_required"] is True


def test_similar_company_and_title_suggest_duplicate():
    records = [
        {
            "id": 5,
            "source_id": "indeed",
            "source_identifier": "job-606",
            "source_url": "https://example.com/job-606",
            "company_name": "Acme Technology",
            "title": "Software Engineer",
        }
    ]

    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-607",
        source_url="https://example.com/job-607",
        company_name="Acme Technologies",
        title="Software Engineer",
        existing_records=records,
        similarity_threshold=0.85,
    )

    assert len(result["potential_duplicates"]) == 1


def test_different_company_does_not_suggest_duplicate():
    records = [
        {
            "id": 6,
            "source_id": "indeed",
            "source_identifier": "job-707",
            "source_url": "https://example.com/job-707",
            "company_name": "Sunrise Foods",
            "title": "Accountant",
        }
    ]

    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-708",
        source_url="https://example.com/job-708",
        company_name="Oceanic Software",
        title="Machine Learning Engineer",
        existing_records=records,
    )

    assert result["potential_duplicates"] == []


def test_invalid_similarity_threshold_raises_error():
    with pytest.raises(ValueError):
        check_for_duplicates(
            source_id="linkedin",
            source_identifier="job-801",
            source_url="https://example.com/job-801",
            company_name="Acme Technologies",
            title="Software Engineer",
            existing_records=[],
            similarity_threshold=1.5,
        )


def test_result_contains_normalized_names():
    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-901",
        source_url="https://example.com/job-901",
        company_name="ACME TECHNOLOGIES",
        title="SOFTWARE ENGINEER",
        existing_records=[],
    )

    assert result["normalized_company"] == "acme technologies"
    assert result["normalized_title"] == "software engineer"


def test_original_records_are_not_modified():
    records = [
        {
            "id": 7,
            "source_id": "indeed",
            "source_identifier": "job-1001",
            "source_url": "https://example.com/job-1001",
            "company_name": "Acme Technologies",
            "title": "Software Engineer",
        }
    ]
    original_records = [record.copy() for record in records]

    check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-1002",
        source_url="https://example.com/job-1002",
        company_name="Acme Technologies",
        title="Software Engineer",
        existing_records=records,
    )

    assert records == original_records


def test_missing_identifiers_do_not_match():
    records = [
        {
            "id": 8,
            "source_id": None,
            "source_identifier": None,
            "source_url": None,
            "company_name": "Different Company",
            "title": "Developer",
        }
    ]

    result = check_for_duplicates(
        source_id="",
        source_identifier="",
        source_url="",
        company_name="Another Company",
        title="Designer",
        existing_records=records,
    )

    assert result["is_exact_source_match"] is False


def test_potential_duplicates_are_sorted_by_similarity():
    records = [
        {
            "id": 9,
            "source_id": "indeed",
            "source_identifier": "job-1101",
            "source_url": "https://example.com/job-1101",
            "company_name": "Acme Technologies",
            "title": "Software Engineer",
        },
        {
            "id": 10,
            "source_id": "indeed",
            "source_identifier": "job-1102",
            "source_url": "https://example.com/job-1102",
            "company_name": "Acme Technologies",
            "title": "Software Engineer",
        },
    ]

    result = check_for_duplicates(
        source_id="linkedin",
        source_identifier="job-1103",
        source_url="https://example.com/job-1103",
        company_name="Acme Technologies",
        title="Software Engineer",
        existing_records=records,
    )

    duplicates = result["potential_duplicates"]
    assert len(duplicates) == 2
    assert duplicates[0]["company_similarity"] >= duplicates[1]["company_similarity"]
