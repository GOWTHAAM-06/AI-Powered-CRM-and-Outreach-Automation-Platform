"""
Integration-style tests for automation/scrapers/registry.py (BE-22).

These tests exercise ``load_registry_from_db`` and ``run_scraper`` using
mock connections seeded with the **exact source rows from 001_demo.sql**.
No real database connection is required; all DB I/O is mocked.

Seed data reference (database/seeds/001_demo.sql):
    ('internshala', 'Internshala',              is_enabled=True,  status='healthy')
    ('naukri',      'Naukri Freshers',           is_enabled=True,  status='healthy')
    ('apna',        'Apna Jobs',                 is_enabled=True,  status='healthy')
    ('workindia',   'WorkIndia',                 is_enabled=True,  status='healthy')
    ('shine',       'Shine Freshers',            is_enabled=False, status='healthy')  <- disabled
    ('hackathons',  'Devpost & Unstop',          is_enabled=True,  status='healthy')
    ('college_tpo', 'TPO Public Directories',    is_enabled=True,  status='healthy')
    ('startups',    'YCombinator Workatastartup',is_enabled=True,  status='healthy')

Key contract being tested:
  - ``load_registry_from_db`` only returns sources that are approved, enabled,
    healthy, AND have a concrete (non-None) scraper class registered.
  - ``run_scraper`` enforces all gates in a single atomic DB read.
"""

import sys
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation.scrapers.base import BaseScraper
from automation.scrapers.registry import (
    SourceConfigurationError,
    _SCRAPER_CLASS_MAP,
    fetch_enabled_sources,
    get_scraper_class,
    is_source_approved,
    load_registry_from_db,
    register_scraper,
    run_scraper,
)


# ---------------------------------------------------------------------------
# Shared helpers / seed data mirrors
# ---------------------------------------------------------------------------

# Mirror of 001_demo.sql sources rows — only the enabled ones (WHERE is_enabled = TRUE).
# 'shine' is excluded because is_enabled=FALSE in the seed.
_SEED_ENABLED_ROWS: List[tuple] = [
    ("apna",        "Apna Jobs",                  "https://apna.co",                    True, "healthy"),
    ("college_tpo", "TPO Public Directories",      "https://colleges.example.edu",        True, "healthy"),
    ("hackathons",  "Devpost & Unstop",            "https://unstop.com",                  True, "healthy"),
    ("internshala", "Internshala",                 "https://internshala.com",             True, "healthy"),
    ("naukri",      "Naukri Freshers",             "https://www.naukri.com/fresher-jobs", True, "healthy"),
    ("startups",    "YCombinator Workatastartup",  "https://workatastartup.com",          True, "healthy"),
    ("workindia",   "WorkIndia",                   "https://www.workindia.in",             True, "healthy"),
]

# All source IDs present in the seed (enabled + disabled)
_ALL_SEED_SOURCE_IDS = {
    "internshala", "naukri", "apna", "workindia",
    "shine", "hackathons", "college_tpo", "startups",
}

# Source IDs that are enabled=TRUE in the seed
_ENABLED_SEED_SOURCE_IDS = {row[0] for row in _SEED_ENABLED_ROWS}

# Source IDs that are disabled in the seed
_DISABLED_SEED_SOURCE_IDS = _ALL_SEED_SOURCE_IDS - _ENABLED_SEED_SOURCE_IDS


def _make_conn(rows: List[tuple]) -> MagicMock:
    """Returns a mock psycopg.Connection that yields the given rows."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = rows

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn


def _seed_conn() -> MagicMock:
    """Returns a mock connection pre-loaded with the full 001_demo.sql enabled rows."""
    return _make_conn(_SEED_ENABLED_ROWS)


def _make_scraper_class(name: str = "MockScraper") -> type:
    """Returns a minimal concrete BaseScraper subclass for testing."""

    class _MockScraper(BaseScraper):
        def fetch(self, url: str) -> str:
            return "<html></html>"

        def parse(self, content: str) -> list:
            return [{"source": self.source_id, "url": self.base_url}]

    _MockScraper.__name__ = name
    _MockScraper.__qualname__ = name
    return _MockScraper


# ---------------------------------------------------------------------------
# Integration: load_registry_from_db — runnable-only invariant with seed data
# ---------------------------------------------------------------------------

class TestLoadRegistryFromDbWithSeedData:
    """
    Confirms load_registry_from_db enforces the runnable-only invariant:
    only approved + enabled + healthy + class-registered sources appear.

    Because no BE-25..32 scrapers are implemented yet, tests must register
    mock classes before calling load_registry_from_db.  This mirrors real
    usage — the function is only meaningful after register_scraper() is called.
    """

    def test_empty_when_all_scrapers_unimplemented(self):
        """
        Before any register_scraper call, load_registry_from_db must be empty —
        even when the DB returns all seed rows.
        """
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            conn = _seed_conn()
            result = load_registry_from_db(conn)
            assert result == {}
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_registered_enabled_healthy_source_appears_in_registry(self):
        """After registering internshala, it appears with correct seed field values."""
        MockCls = _make_scraper_class("IntershalaScraper")
        original = _SCRAPER_CLASS_MAP.get("internshala")
        try:
            register_scraper("internshala", MockCls)
            conn = _seed_conn()
            result = load_registry_from_db(conn)
            assert "internshala" in result
            entry = result["internshala"]
            assert entry["name"] == "Internshala"
            assert entry["base_url"] == "https://internshala.com"
            assert entry["status"] == "healthy"
            assert entry["scraper_cls"] is MockCls
        finally:
            _SCRAPER_CLASS_MAP["internshala"] = original

    def test_only_registered_sources_appear(self):
        """Registering two scrapers means exactly those two appear; others are absent."""
        MockA = _make_scraper_class("ApnaScraper")
        MockB = _make_scraper_class("NaukriScraper")
        orig_apna = _SCRAPER_CLASS_MAP.get("apna")
        orig_naukri = _SCRAPER_CLASS_MAP.get("naukri")
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            register_scraper("apna", MockA)
            register_scraper("naukri", MockB)
            conn = _seed_conn()
            result = load_registry_from_db(conn)
            assert set(result.keys()) == {"apna", "naukri"}
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_no_entry_has_none_scraper_cls(self):
        """Runnable invariant: every returned entry must have a concrete scraper class."""
        MockA = _make_scraper_class("WorkIndiaScraper")
        MockB = _make_scraper_class("StartupsScraper")
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            register_scraper("workindia", MockA)
            register_scraper("startups", MockB)
            conn = _seed_conn()
            result = load_registry_from_db(conn)
            for source_id, entry in result.items():
                assert entry["scraper_cls"] is not None, (
                    f"Entry '{source_id}' leaked scraper_cls=None — runnable invariant violated"
                )
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_disabled_seed_source_absent_even_when_class_registered(self):
        """
        'shine' is is_enabled=FALSE in the seed, so it cannot appear in the
        live registry even if its class is registered.
        """
        MockCls = _make_scraper_class("ShineScraper")
        original = _SCRAPER_CLASS_MAP.get("shine")
        try:
            register_scraper("shine", MockCls)
            conn = _seed_conn()  # shine absent from enabled rows
            result = load_registry_from_db(conn)
            assert "shine" not in result
        finally:
            _SCRAPER_CLASS_MAP["shine"] = original

    def test_quarantined_source_excluded_even_when_class_registered(self):
        MockCls = _make_scraper_class("QuarantinedScraper")
        original = _SCRAPER_CLASS_MAP.get("hackathons")
        try:
            register_scraper("hackathons", MockCls)
            rows = [
                row if row[0] != "hackathons"
                else ("hackathons", "Devpost & Unstop", "https://unstop.com", True, "quarantined")
                for row in _SEED_ENABLED_ROWS
            ]
            conn = _make_conn(rows)
            result = load_registry_from_db(conn)
            assert "hackathons" not in result
        finally:
            _SCRAPER_CLASS_MAP["hackathons"] = original

    def test_naukri_field_values_match_seed_exactly(self):
        MockCls = _make_scraper_class("NaukriCheck")
        original = _SCRAPER_CLASS_MAP.get("naukri")
        try:
            register_scraper("naukri", MockCls)
            conn = _seed_conn()
            result = load_registry_from_db(conn)
            entry = result["naukri"]
            assert entry["name"] == "Naukri Freshers"
            assert entry["base_url"] == "https://www.naukri.com/fresher-jobs"
        finally:
            _SCRAPER_CLASS_MAP["naukri"] = original

    def test_all_seven_enabled_seed_sources_can_appear_when_all_registered(self):
        """
        If every scraper is registered, all 7 enabled seed sources appear.
        """
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for source_id in _ENABLED_SEED_SOURCE_IDS:
                _SCRAPER_CLASS_MAP[source_id] = _make_scraper_class(f"{source_id}Scraper")
            conn = _seed_conn()
            result = load_registry_from_db(conn)
            assert set(result.keys()) == _ENABLED_SEED_SOURCE_IDS
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_unapproved_source_in_db_never_leaks_into_registry(self):
        """
        A source in the DB that is NOT in _SCRAPER_CLASS_MAP (e.g. linkedin)
        must never appear in the returned registry regardless of its DB status.
        """
        rows = list(_SEED_ENABLED_ROWS) + [
            ("linkedin", "LinkedIn", "https://linkedin.com", True, "healthy"),
        ]
        conn = _make_conn(rows)
        # Even with all approved scrapers registered
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = _make_scraper_class(f"{k}Scraper")
            result = load_registry_from_db(conn)
            assert "linkedin" not in result
        finally:
            _SCRAPER_CLASS_MAP.update(originals)


# ---------------------------------------------------------------------------
# Integration: get_scraper_class enforcement with seed data
# ---------------------------------------------------------------------------

class TestGetScraperClassWithSeedData:
    """
    Confirms get_scraper_class correctly enforces all guards when supplied
    with seed-realistic DB rows.
    """

    def test_all_enabled_healthy_seed_sources_reach_not_implemented_error(self):
        """
        All 7 enabled seed sources pass the DB gate and reach
        NotImplementedError (because no scraper class is registered yet).
        """
        for source_id in _ENABLED_SEED_SOURCE_IDS:
            conn = _seed_conn()
            with pytest.raises(NotImplementedError, match="not been implemented yet"):
                get_scraper_class(source_id, conn=conn)

    def test_disabled_seed_source_rejected_at_db_gate(self):
        """
        'shine' has is_enabled=FALSE in the seed; SQL excludes it,
        so get_scraper_class raises SourceConfigurationError.
        """
        for source_id in _DISABLED_SEED_SOURCE_IDS:
            conn = _seed_conn()
            with pytest.raises(SourceConfigurationError, match="no corresponding row"):
                get_scraper_class(source_id, conn=conn)

    def test_quarantined_source_rejected(self):
        rows = [
            row if row[0] != "internshala"
            else ("internshala", "Internshala", "https://internshala.com", True, "quarantined")
            for row in _SEED_ENABLED_ROWS
        ]
        conn = _make_conn(rows)
        with pytest.raises(SourceConfigurationError, match="quarantined"):
            get_scraper_class("internshala", conn=conn)

    def test_unrecognised_source_rejected_before_db_is_queried(self):
        """linkedin is not in _SCRAPER_CLASS_MAP; DB must never be consulted."""
        conn = MagicMock()
        conn.cursor.side_effect = AssertionError("DB must not be queried for unlisted source")
        with pytest.raises(SourceConfigurationError, match="not in the approved scraper registry"):
            get_scraper_class("linkedin", conn=conn)

    def test_registered_class_resolves_with_seed_conn(self):
        """After register_scraper, get_scraper_class resolves correctly."""
        MockCls = _make_scraper_class("SeedResolveScraper")
        original = _SCRAPER_CLASS_MAP.get("workindia")
        try:
            register_scraper("workindia", MockCls)
            conn = _seed_conn()
            result = get_scraper_class("workindia", conn=conn)
            assert result is MockCls
        finally:
            _SCRAPER_CLASS_MAP["workindia"] = original


# ---------------------------------------------------------------------------
# Integration: run_scraper — atomic enforcement with seed data
# ---------------------------------------------------------------------------

class TestRunScraperWithSeedData:
    """
    Confirms run_scraper is the single enforced entry-point and uses
    a single atomic DB read (all gates + base_url in one snapshot).
    """

    def test_run_scraper_rejects_unlisted_source(self):
        conn = _seed_conn()
        with pytest.raises(SourceConfigurationError, match="not in the approved scraper registry"):
            run_scraper("linkedin", conn=conn)

    def test_run_scraper_rejects_disabled_seed_source(self):
        """'shine' is disabled in the seed — run_scraper must refuse it."""
        conn = _seed_conn()
        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            run_scraper("shine", conn=conn)

    def test_run_scraper_rejects_unimplemented_scraper(self):
        """An enabled healthy approved source with scraper_cls=None raises NotImplementedError."""
        conn = _seed_conn()
        with pytest.raises(NotImplementedError, match="not been implemented yet"):
            run_scraper("internshala", conn=conn)

    def test_run_scraper_rejects_quarantined_source(self):
        rows = [
            row if row[0] != "hackathons"
            else ("hackathons", "Devpost & Unstop", "https://unstop.com", True, "quarantined")
            for row in _SEED_ENABLED_ROWS
        ]
        original = _SCRAPER_CLASS_MAP.get("hackathons")
        try:
            register_scraper("hackathons", _make_scraper_class("QuarantineCheck"))
            conn = _make_conn(rows)
            with pytest.raises(SourceConfigurationError, match="quarantined"):
                run_scraper("hackathons", conn=conn)
        finally:
            _SCRAPER_CLASS_MAP["hackathons"] = original

    def test_run_scraper_executes_registered_class_and_returns_results(self):
        """
        End-to-end with seed data: register a scraper for college_tpo,
        run it, verify results include the correct source_id and base_url.
        """
        MockCls = _make_scraper_class("E2ESeedScraper")
        original = _SCRAPER_CLASS_MAP.get("college_tpo")
        try:
            register_scraper("college_tpo", MockCls)
            conn = _seed_conn()
            results = run_scraper("college_tpo", conn=conn)
            assert isinstance(results, list)
            assert len(results) == 1
            assert results[0]["source"] == "college_tpo"
            assert results[0]["url"] == "https://colleges.example.edu"
        finally:
            _SCRAPER_CLASS_MAP["college_tpo"] = original

    def test_run_scraper_injects_base_url_from_single_atomic_db_read(self):
        """
        Verifies that the base_url comes from the same DB snapshot as validation
        — not a separate second query — by checking the injected value exactly
        matches the seed row.
        """
        captured = {}

        class CapturingScraper(BaseScraper):
            def fetch(self, url: str) -> str:
                captured["base_url"] = self.base_url
                return ""

            def parse(self, content: str) -> list:
                return []

        original = _SCRAPER_CLASS_MAP.get("startups")
        try:
            register_scraper("startups", CapturingScraper)
            conn = _seed_conn()
            run_scraper("startups", conn=conn)
            assert captured["base_url"] == "https://workatastartup.com"
        finally:
            _SCRAPER_CLASS_MAP["startups"] = original

    def test_run_scraper_source_id_passed_to_constructor(self):
        """Verifies the normalised source_id is passed to the scraper constructor."""
        captured = {}

        class CapturingIdScraper(BaseScraper):
            def fetch(self, url: str) -> str:
                captured["source_id"] = self.source_id
                return ""

            def parse(self, content: str) -> list:
                return []

        original = _SCRAPER_CLASS_MAP.get("apna")
        try:
            register_scraper("apna", CapturingIdScraper)
            conn = _seed_conn()
            run_scraper("APNA", conn=conn)  # uppercase input
            assert captured["source_id"] == "apna"  # normalised lowercase
        finally:
            _SCRAPER_CLASS_MAP["apna"] = original


# ---------------------------------------------------------------------------
# Integration: cross-check static registry vs seed data (parity tests)
# ---------------------------------------------------------------------------

class TestStaticRegistryVsSeedData:
    """
    Bidirectional parity: every seed source ID has a registry entry and
    vice-versa, so neither list drifts from the other silently.
    """

    def test_every_seed_source_is_in_static_registry(self):
        for source_id in _ALL_SEED_SOURCE_IDS:
            assert source_id in _SCRAPER_CLASS_MAP, (
                f"Seed source '{source_id}' is missing from _SCRAPER_CLASS_MAP."
            )

    def test_every_static_registry_entry_is_in_seed(self):
        for source_id in _SCRAPER_CLASS_MAP:
            assert source_id in _ALL_SEED_SOURCE_IDS, (
                f"Registry entry '{source_id}' has no seed record in 001_demo.sql."
            )

    def test_all_seed_sources_are_approved(self):
        for source_id in _ALL_SEED_SOURCE_IDS:
            assert is_source_approved(source_id), (
                f"Seed source '{source_id}' is not approved in the static registry."
            )

    def test_disabled_seed_source_still_approved_in_registry(self):
        """
        'shine' is disabled in the DB but still approved in the static map —
        approval and enablement are separate concerns.
        """
        for source_id in _DISABLED_SEED_SOURCE_IDS:
            assert is_source_approved(source_id), (
                f"Disabled seed source '{source_id}' should remain in static registry."
            )
