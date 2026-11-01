"""
Tests for automation/scrapers/registry.py (BE-22: Approved Source Registry).

All database access is mocked; no real database connection is required.
"""

import sys
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: ensure the repo root is on sys.path so that
# 'from automation.scrapers.registry import ...' resolves correctly.
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
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_conn(rows: List[tuple]) -> MagicMock:
    """
    Returns a mock psycopg.Connection whose cursor yields the given rows.

    Each row must be a tuple of (id, name, base_url, is_enabled, status).
    """
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = rows

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn


def _make_scraper_class(name: str = "MockScraper") -> type:
    """Returns a minimal concrete BaseScraper subclass for testing."""

    class _MockScraper(BaseScraper):
        def fetch(self, url: str) -> str:
            return "<html></html>"

        def parse(self, content: str) -> list:
            return []

    _MockScraper.__name__ = name
    _MockScraper.__qualname__ = name
    return _MockScraper


# ---------------------------------------------------------------------------
# is_source_approved
# ---------------------------------------------------------------------------

class TestIsSourceApproved:
    def test_listed_source_is_approved(self):
        assert is_source_approved("internshala") is True

    def test_listed_source_case_insensitive(self):
        assert is_source_approved("INTERNSHALA") is True
        assert is_source_approved("Naukri") is True

    def test_unlisted_source_is_not_approved(self):
        assert is_source_approved("linkedin") is False

    def test_unknown_key_is_not_approved(self):
        assert is_source_approved("totally_unknown_source") is False

    def test_all_canonical_keys_are_approved(self):
        """All keys in the static map must satisfy is_source_approved."""
        for key in _SCRAPER_CLASS_MAP:
            assert is_source_approved(key) is True, f"Expected {key!r} to be approved"


# ---------------------------------------------------------------------------
# fetch_enabled_sources
# ---------------------------------------------------------------------------

class TestFetchEnabledSources:
    def test_returns_dict_keyed_by_source_id(self):
        rows = [
            ("internshala", "Internshala", "https://internshala.com", True, "healthy"),
        ]
        conn = _make_conn(rows)
        result = fetch_enabled_sources(conn)
        assert "internshala" in result

    def test_row_fields_are_mapped_correctly(self):
        rows = [
            ("naukri", "Naukri Freshers", "https://naukri.com/fresher-jobs", True, "healthy"),
        ]
        conn = _make_conn(rows)
        result = fetch_enabled_sources(conn)
        assert result["naukri"]["name"] == "Naukri Freshers"
        assert result["naukri"]["base_url"] == "https://naukri.com/fresher-jobs"
        assert result["naukri"]["is_enabled"] is True
        assert result["naukri"]["status"] == "healthy"

    def test_disabled_source_is_excluded(self):
        """
        fetch_enabled_sources filters at the SQL level (WHERE is_enabled = TRUE).
        The mock simulates a DB that returned no rows for a disabled source,
        verifying the function's contract that disabled sources are not present
        in the returned mapping.
        """
        # SQL WHERE is_enabled = TRUE means the DB returns nothing for a
        # disabled source; the mock reflects that by yielding zero rows.
        conn = _make_conn([])
        result = fetch_enabled_sources(conn)
        assert "apna" not in result

    def test_empty_table_returns_empty_dict(self):
        conn = _make_conn([])
        result = fetch_enabled_sources(conn)
        assert result == {}

    def test_multiple_rows_only_enabled_returned(self):
        """
        When the DB returns only enabled rows (WHERE is_enabled = TRUE applied),
        the result contains exactly those rows and no disabled ones.
        """
        # Simulate what the DB returns after the WHERE is_enabled = TRUE filter:
        # only the two enabled rows; the disabled 'naukri' row is absent.
        rows = [
            ("internshala", "Internshala", "https://internshala.com", True, "healthy"),
            ("shine", "Shine", "https://shine.com", True, "rate_limited"),
        ]
        conn = _make_conn(rows)
        result = fetch_enabled_sources(conn)
        assert len(result) == 2
        assert "internshala" in result
        assert "shine" in result
        assert "naukri" not in result


# ---------------------------------------------------------------------------
# get_scraper_class – registry (static) gate
# ---------------------------------------------------------------------------

class TestGetScraperClassRegistryGate:
    def test_unrecognised_source_raises_configuration_error(self):
        with pytest.raises(SourceConfigurationError, match="not in the approved scraper registry"):
            get_scraper_class("linkedin")

    def test_unknown_source_raises_configuration_error(self):
        with pytest.raises(SourceConfigurationError):
            get_scraper_class("totally_made_up_source")

    def test_error_message_includes_source_id(self):
        with pytest.raises(SourceConfigurationError, match="linkedin"):
            get_scraper_class("linkedin")


# ---------------------------------------------------------------------------
# get_scraper_class – database gate (disabled / unhealthy / missing)
# ---------------------------------------------------------------------------

class TestGetScraperClassDatabaseGate:
    def test_disabled_source_is_rejected(self):
        """
        A disabled source must raise SourceConfigurationError.

        Because fetch_enabled_sources now filters with WHERE is_enabled = TRUE,
        a disabled source is absent from the loader's result entirely.  The mock
        reflects this by returning no rows, which causes get_scraper_class to
        raise SourceConfigurationError with the "no corresponding row" message
        (the source never reaches the enabled/healthy checks).
        """
        # Simulate SQL-level exclusion: no rows returned for a disabled source.
        conn = _make_conn([])
        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            get_scraper_class("internshala", conn=conn)

    def test_quarantined_source_is_rejected(self):
        conn = _make_conn([
            ("internshala", "Internshala", "https://internshala.com", True, "quarantined"),
        ])
        with pytest.raises(SourceConfigurationError, match="quarantined"):
            get_scraper_class("internshala", conn=conn)

    def test_rate_limited_source_is_rejected(self):
        conn = _make_conn([
            ("internshala", "Internshala", "https://internshala.com", True, "rate_limited"),
        ])
        with pytest.raises(SourceConfigurationError, match="rate_limited"):
            get_scraper_class("internshala", conn=conn)

    def test_disabled_status_field_source_is_rejected(self):
        conn = _make_conn([
            ("internshala", "Internshala", "https://internshala.com", True, "disabled"),
        ])
        with pytest.raises(SourceConfigurationError, match="disabled"):
            get_scraper_class("internshala", conn=conn)

    def test_source_missing_from_db_raises_configuration_error(self):
        """Approved in registry but absent from the database table."""
        conn = _make_conn([])  # empty database
        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            get_scraper_class("internshala", conn=conn)

    def test_source_not_in_db_error_message_includes_source_id(self):
        conn = _make_conn([])
        with pytest.raises(SourceConfigurationError, match="internshala"):
            get_scraper_class("internshala", conn=conn)

    def test_unlisted_source_rejected_before_db_query(self):
        """
        An unlisted source must fail at step 1 (registry gate), not step 2 (DB).
        This means the DB connection is never consulted.
        """
        conn = MagicMock()  # would fail if called
        conn.cursor.side_effect = AssertionError("DB should not be queried for unlisted source")
        with pytest.raises(SourceConfigurationError, match="not in the approved scraper registry"):
            get_scraper_class("linkedin", conn=conn)


# ---------------------------------------------------------------------------
# get_scraper_class – successful resolution
# ---------------------------------------------------------------------------

class TestGetScraperClassResolution:
    def _healthy_conn(self, source_id: str) -> MagicMock:
        return _make_conn([
            (source_id, "Test Source", "https://example.com", True, "healthy"),
        ])

    def test_enabled_source_resolves_to_registered_class(self):
        """
        After registering a scraper class, get_scraper_class returns it
        for a healthy enabled source.
        """
        MockScraperCls = _make_scraper_class("ResolutionTestScraper")
        # Temporarily register for this test
        original = _SCRAPER_CLASS_MAP.get("internshala")
        _SCRAPER_CLASS_MAP["internshala"] = MockScraperCls
        try:
            conn = self._healthy_conn("internshala")
            result = get_scraper_class("internshala", conn=conn)
            assert result is MockScraperCls
        finally:
            _SCRAPER_CLASS_MAP["internshala"] = original

    def test_returns_class_not_instance(self):
        """get_scraper_class must return the class itself, not an instantiated object."""
        MockScraperCls = _make_scraper_class("ClassNotInstanceScraper")
        original = _SCRAPER_CLASS_MAP.get("naukri")
        _SCRAPER_CLASS_MAP["naukri"] = MockScraperCls
        try:
            conn = self._healthy_conn("naukri")
            result = get_scraper_class("naukri", conn=conn)
            assert isinstance(result, type)
            assert issubclass(result, BaseScraper)
        finally:
            _SCRAPER_CLASS_MAP["naukri"] = original

    def test_source_id_is_case_insensitive(self):
        """Source IDs should be normalised to lowercase before registry lookup."""
        MockScraperCls = _make_scraper_class("CaseScraper")
        original = _SCRAPER_CLASS_MAP.get("apna")
        _SCRAPER_CLASS_MAP["apna"] = MockScraperCls
        try:
            conn = self._healthy_conn("apna")
            result = get_scraper_class("APNA", conn=conn)
            assert result is MockScraperCls
        finally:
            _SCRAPER_CLASS_MAP["apna"] = original

    def test_unimplemented_scraper_raises_not_implemented(self):
        """
        If a source is enabled and healthy but its class entry is still None,
        a NotImplementedError is raised (not SourceConfigurationError).
        """
        # All entries start as None; internshala is a good candidate
        assert _SCRAPER_CLASS_MAP["internshala"] is None
        conn = self._healthy_conn("internshala")
        with pytest.raises(NotImplementedError, match="not been implemented yet"):
            get_scraper_class("internshala", conn=conn)


# ---------------------------------------------------------------------------
# get_scraper_class – DATABASE_URL environment variable
# ---------------------------------------------------------------------------

class TestGetScraperClassEnvVar:
    def test_missing_database_url_raises_configuration_error(self, monkeypatch):
        """When no conn is given and DATABASE_URL is absent, raise SourceConfigurationError."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SourceConfigurationError, match="DATABASE_URL"):
            get_scraper_class("internshala")


# ---------------------------------------------------------------------------
# register_scraper
# ---------------------------------------------------------------------------

class TestRegisterScraper:
    def test_register_valid_scraper_class(self):
        MockScraperCls = _make_scraper_class("RegTestScraper")
        original = _SCRAPER_CLASS_MAP.get("shine")
        try:
            register_scraper("shine", MockScraperCls)
            assert _SCRAPER_CLASS_MAP["shine"] is MockScraperCls
        finally:
            _SCRAPER_CLASS_MAP["shine"] = original

    def test_register_is_case_insensitive(self):
        MockScraperCls = _make_scraper_class("CaseRegScraper")
        original = _SCRAPER_CLASS_MAP.get("apna")
        try:
            register_scraper("APNA", MockScraperCls)
            assert _SCRAPER_CLASS_MAP["apna"] is MockScraperCls
        finally:
            _SCRAPER_CLASS_MAP["apna"] = original

    def test_register_unlisted_source_raises_error(self):
        MockScraperCls = _make_scraper_class("NotListedScraper")
        with pytest.raises(SourceConfigurationError, match="not in the approved registry"):
            register_scraper("linkedin", MockScraperCls)

    def test_register_non_scraper_class_raises_type_error(self):
        class NotAScraper:
            pass

        with pytest.raises(TypeError, match="subclass of BaseScraper"):
            register_scraper("internshala", NotAScraper)  # type: ignore[arg-type]

    def test_register_rejects_instance_instead_of_class(self):
        MockScraperCls = _make_scraper_class("InstanceScraper")
        instance = MockScraperCls("internshala", "https://internshala.com")
        with pytest.raises(TypeError):
            register_scraper("internshala", instance)  # type: ignore[arg-type]

    def test_after_register_get_scraper_class_resolves(self):
        """End-to-end: register then resolve via get_scraper_class."""
        MockScraperCls = _make_scraper_class("EndToEndScraper")
        original = _SCRAPER_CLASS_MAP.get("hackathons")
        try:
            register_scraper("hackathons", MockScraperCls)
            conn = _make_conn([
                ("hackathons", "Hackathons", "https://unstop.com", True, "healthy"),
            ])
            result = get_scraper_class("hackathons", conn=conn)
            assert result is MockScraperCls
        finally:
            _SCRAPER_CLASS_MAP["hackathons"] = original


# ---------------------------------------------------------------------------
# BaseScraper contract – existing functionality must not be broken
# ---------------------------------------------------------------------------

class TestBaseScraperContractIntact:
    def test_base_scraper_is_abstract(self):
        """BaseScraper must remain non-instantiable."""
        import inspect
        assert inspect.isabstract(BaseScraper)

    def test_concrete_scraper_can_be_instantiated(self):
        MockScraperCls = _make_scraper_class("ConcreteCheck")
        instance = MockScraperCls("internshala", "https://internshala.com")
        assert instance.source_id == "internshala"
        assert instance.base_url == "https://internshala.com"

    def test_concrete_scraper_run_calls_fetch_and_parse(self):
        MockScraperCls = _make_scraper_class("RunCheck")
        instance = MockScraperCls("internshala", "https://internshala.com")
        results = instance.run()
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# run_scraper – enforcement gates and execution
# ---------------------------------------------------------------------------

class TestRunScraper:
    """
    Verifies that run_scraper() — the single enforced execution entry-point —
    enforces all three validation gates (static approval, DB enabled/healthy,
    class registration) before ever invoking scraper logic, and that it uses
    a single atomic DB read (no TOCTOU).
    """

    def test_unlisted_source_rejected_before_db_is_queried(self):
        """
        An unlisted source must fail at the static gate.
        The DB connection must never be consulted.
        """
        conn = MagicMock()
        conn.cursor.side_effect = AssertionError("DB must not be queried for unlisted source")
        with pytest.raises(SourceConfigurationError, match="not in the approved scraper registry"):
            run_scraper("linkedin", conn=conn)

    def test_source_absent_from_db_is_rejected(self):
        """Source approved in registry but absent from DB (is_enabled=TRUE rows)."""
        conn = _make_conn([])  # DB returns no enabled rows
        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            run_scraper("internshala", conn=conn)

    def test_quarantined_source_is_rejected(self):
        conn = _make_conn([
            ("internshala", "Internshala", "https://internshala.com", True, "quarantined"),
        ])
        with pytest.raises(SourceConfigurationError, match="quarantined"):
            run_scraper("internshala", conn=conn)

    def test_rate_limited_source_is_rejected(self):
        conn = _make_conn([
            ("naukri", "Naukri Freshers", "https://naukri.com", True, "rate_limited"),
        ])
        with pytest.raises(SourceConfigurationError, match="rate_limited"):
            run_scraper("naukri", conn=conn)

    def test_disabled_source_excluded_by_sql_raises_configuration_error(self):
        """'shine' is disabled in the seed; SQL excludes it entirely."""
        conn = _make_conn([])  # no enabled rows returned
        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            run_scraper("shine", conn=conn)

    def test_unimplemented_scraper_raises_not_implemented(self):
        """
        A source that is enabled, healthy, and approved but whose scraper class
        is still None must raise NotImplementedError — not SourceConfigurationError.
        """
        assert _SCRAPER_CLASS_MAP["internshala"] is None
        conn = _make_conn([
            ("internshala", "Internshala", "https://internshala.com", True, "healthy"),
        ])
        with pytest.raises(NotImplementedError, match="not been implemented yet"):
            run_scraper("internshala", conn=conn)

    def test_registered_scraper_executes_and_returns_results(self):
        """
        End-to-end: after registering a concrete class, run_scraper instantiates
        it, calls run(), and returns the result list.
        """
        MockCls = _make_scraper_class("RunE2EScraper")
        original = _SCRAPER_CLASS_MAP.get("hackathons")
        try:
            register_scraper("hackathons", MockCls)
            conn = _make_conn([
                ("hackathons", "Devpost & Unstop", "https://unstop.com", True, "healthy"),
            ])
            results = run_scraper("hackathons", conn=conn)
            assert isinstance(results, list)
        finally:
            _SCRAPER_CLASS_MAP["hackathons"] = original

    def test_base_url_injected_from_same_db_read(self):
        """
        Confirms the scraper receives the base_url from the single atomic DB
        snapshot — not from a separate second query that could race.
        """
        captured = {}

        class CapturingScraper(BaseScraper):
            def fetch(self, url: str) -> str:
                captured["base_url"] = self.base_url
                return ""
            def parse(self, content: str) -> list:
                return []

        original = _SCRAPER_CLASS_MAP.get("apna")
        try:
            register_scraper("apna", CapturingScraper)
            conn = _make_conn([
                ("apna", "Apna Jobs", "https://apna.co", True, "healthy"),
            ])
            run_scraper("apna", conn=conn)
            assert captured["base_url"] == "https://apna.co"
        finally:
            _SCRAPER_CLASS_MAP["apna"] = original

    def test_source_id_normalised_to_lowercase(self):
        """run_scraper must normalise source_id to lowercase before all gates."""
        MockCls = _make_scraper_class("CaseScraper")
        original = _SCRAPER_CLASS_MAP.get("workindia")
        try:
            register_scraper("workindia", MockCls)
            conn = _make_conn([
                ("workindia", "WorkIndia", "https://www.workindia.in", True, "healthy"),
            ])
            results = run_scraper("WORKINDIA", conn=conn)
            assert isinstance(results, list)
        finally:
            _SCRAPER_CLASS_MAP["workindia"] = original

    def test_missing_database_url_raises_configuration_error(self, monkeypatch):
        """When no conn is given and DATABASE_URL is absent, raise SourceConfigurationError."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SourceConfigurationError, match="DATABASE_URL"):
            run_scraper("internshala")


# ---------------------------------------------------------------------------
# load_registry_from_db – runnable-only invariant
# ---------------------------------------------------------------------------

class TestLoadRegistryFromDb:
    """
    Verifies that load_registry_from_db() never includes sources with
    scraper_cls=None; every entry in the returned mapping must be immediately
    executable (no late NotImplementedError surprises for callers).
    """

    def _healthy_rows(self, *source_ids) -> list:
        urls = {
            "internshala": "https://internshala.com",
            "naukri": "https://naukri.com",
            "apna": "https://apna.co",
            "hackathons": "https://unstop.com",
            "college_tpo": "https://colleges.example.edu",
            "startups": "https://workatastartup.com",
            "workindia": "https://www.workindia.in",
            "shine": "https://shine.com",
        }
        return [(sid, sid.title(), urls.get(sid, "https://example.com"), True, "healthy")
                for sid in source_ids]

    def test_empty_when_no_scrapers_registered(self):
        """
        Before any scraper class is registered, load_registry_from_db must
        return an empty dict — no None entries leak through.
        """
        # Ensure all entries are None for the duration of this test
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            conn = _make_conn(self._healthy_rows("internshala", "naukri"))
            result = load_registry_from_db(conn)
            assert result == {}
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_only_registered_class_appears_in_result(self):
        """
        After registering exactly one scraper, only that source appears.
        Other approved-but-unimplemented sources must be absent.
        """
        MockCls = _make_scraper_class("OnlyOneScraper")
        original_int = _SCRAPER_CLASS_MAP.get("internshala")
        original_naukri = _SCRAPER_CLASS_MAP.get("naukri")
        try:
            _SCRAPER_CLASS_MAP["internshala"] = MockCls
            _SCRAPER_CLASS_MAP["naukri"] = None
            conn = _make_conn(self._healthy_rows("internshala", "naukri"))
            result = load_registry_from_db(conn)
            assert "internshala" in result
            assert "naukri" not in result
        finally:
            _SCRAPER_CLASS_MAP["internshala"] = original_int
            _SCRAPER_CLASS_MAP["naukri"] = original_naukri

    def test_every_returned_entry_has_non_none_scraper_cls(self):
        """
        The runnable-only invariant: no returned entry may have scraper_cls=None.
        """
        MockA = _make_scraper_class("RunA")
        MockB = _make_scraper_class("RunB")
        originals = {k: _SCRAPER_CLASS_MAP[k] for k in _SCRAPER_CLASS_MAP}
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            _SCRAPER_CLASS_MAP["apna"] = MockA
            _SCRAPER_CLASS_MAP["hackathons"] = MockB
            conn = _make_conn(self._healthy_rows("apna", "hackathons", "internshala"))
            result = load_registry_from_db(conn)
            for sid, entry in result.items():
                assert entry["scraper_cls"] is not None, (
                    f"Entry '{sid}' has scraper_cls=None — runnable invariant violated"
                )
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_non_healthy_source_excluded(self):
        MockCls = _make_scraper_class("HealthCheckScraper")
        original = _SCRAPER_CLASS_MAP.get("internshala")
        try:
            _SCRAPER_CLASS_MAP["internshala"] = MockCls
            conn = _make_conn([
                ("internshala", "Internshala", "https://internshala.com", True, "quarantined"),
            ])
            result = load_registry_from_db(conn)
            assert "internshala" not in result
        finally:
            _SCRAPER_CLASS_MAP["internshala"] = original

    def test_source_absent_from_db_excluded(self):
        MockCls = _make_scraper_class("AbsentScraper")
        original = _SCRAPER_CLASS_MAP.get("naukri")
        try:
            _SCRAPER_CLASS_MAP["naukri"] = MockCls
            conn = _make_conn([])  # nothing in DB
            result = load_registry_from_db(conn)
            assert "naukri" not in result
        finally:
            _SCRAPER_CLASS_MAP["naukri"] = original

    def test_fields_present_for_runnable_entry(self):
        MockCls = _make_scraper_class("FieldScraper")
        original = _SCRAPER_CLASS_MAP.get("college_tpo")
        try:
            _SCRAPER_CLASS_MAP["college_tpo"] = MockCls
            conn = _make_conn([
                ("college_tpo", "TPO Directories", "https://colleges.example.edu", True, "healthy"),
            ])
            result = load_registry_from_db(conn)
            entry = result["college_tpo"]
            assert entry["name"] == "TPO Directories"
            assert entry["base_url"] == "https://colleges.example.edu"
            assert entry["status"] == "healthy"
            assert entry["scraper_cls"] is MockCls
        finally:
            _SCRAPER_CLASS_MAP["college_tpo"] = original

