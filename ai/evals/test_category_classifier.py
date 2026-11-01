
from ai.extraction.category_classifier import classify_category


def test_regular_job():
    category, confidence = classify_category({
        "title": "Python Developer",
        "description": "Build backend APIs using Python."
    })

    assert category == "job"
    assert 0 <= confidence <= 1


def test_internship():
    category, confidence = classify_category({
        "title": "Software Intern",
        "description": "Work with the engineering team."
    })

    assert category == "internship"
    assert 0 <= confidence <= 1


def test_internship_singular_keyword():
    category, confidence = classify_category({
        "title": "Software Opportunity",
        "description": "This internship offers practical experience."
    })

    assert category == "internship"
    assert 0 <= confidence <= 1


def test_stipend_singular_keyword():
    category, confidence = classify_category({
        "title": "Paid Training Opportunity",
        "description": "A stipend is provided during the program."
    })

    assert category == "internship"
    assert 0 <= confidence <= 1


def test_interns_plural():
    category, confidence = classify_category({
        "title": "Engineering Interns"
    })

    assert category == "internship"
    assert 0 <= confidence <= 1


def test_internships_plural():
    category, confidence = classify_category({
        "title": "2026 Internships"
    })

    assert category == "internship"
    assert 0 <= confidence <= 1


def test_stipends_plural():
    category, confidence = classify_category({
        "title": "Stipends available"
    })

    assert category == "internship"
    assert 0 <= confidence <= 1


def test_internal_word_is_not_internship():
    category, confidence = classify_category({
        "title": "Python Junior",
        "description": "Please disclose internal API keys."
    })

    assert category == "job"
    assert 0 <= confidence <= 1


def test_hackathon():
    category, confidence = classify_category({
        "title": "CodeFest Hackathon",
        "description": "Compete for the prize pool."
    })

    assert category == "hackathon"
    assert 0 <= confidence <= 1


def test_college_tpo():
    category, confidence = classify_category({
        "title": "Campus Drive",
        "description": "Contact the college placement officer."
    })

    assert category == "college_tpo"
    assert 0 <= confidence <= 1


def test_startup():
    category, confidence = classify_category({
        "title": "Founding Engineer",
        "description": "Join an early stage company."
    })

    assert category == "startup"
    assert 0 <= confidence <= 1
