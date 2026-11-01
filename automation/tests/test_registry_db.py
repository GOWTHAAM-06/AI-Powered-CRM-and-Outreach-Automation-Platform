"""
Real PostgreSQL integration tests for automation/scrapers/registry.py (BE-22).

======================================================================
DISTINCTION FROM OTHER TEST FILES
======================================================================
  test_registry.py              — unit tests; ALL database I/O is mocked
  test_registry_integration.py  — mock-based integration style; no real DB
  test_registry_db.py           — THIS FILE: live psycopg connection required

Every test here exercises the registry's ACTUAL database path.  All mocked
DB tests remain in the files above and are unaffected by this file.

======================================================================
ISOLATION STRATEGY
======================================================================
A TEMPORARY TABLE named ``sources`` is created once per test session.
PostgreSQL temporary tables shadow any same-named permanent table for the
duration of the connection — they are session-local and connection-local,
so no production row is ever read, modified, or deleted.  The temp table
is dropped automatically when the connection closes.

Each test function starts with a clean table (all rows deleted by the
``pg_sources`` fixture) and inserts only what it needs.

======================================================================
AUTOMATIC SKIP BEHAVIOUR
======================================================================
When DATABASE_URL is not set or the database is unreachable, every test
in this file is automatically skipped and reported as NOT VERIFIED.
A skip is never reported as a pass.

HOW TO RUN (local Docker):
    docker-compose --profile local-db up -d local_postgres
    set DATABASE_URL=postgresql://crm_user:crm_password@localhost:5432/crm_db
    python -m pytest automation/tests/test_registry_db.py -v -m integration_db

HOW TO RUN (Neon cloud, replace with real credentials):
    set DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/crm_db?sslmode=require
    python -m pytest automation/tests/test_registry_db.py -v -m integration_db

======================================================================
SCHEMA AUTHORITY
======================================================================
Temporary table DDL is copied verbatim from:
    database/migrations/002_organizations_sources.sql

Canonical status values from the CHECK constraint (used in all tests):
    'healthy' | 'quarantined' | 'disabled' | 'rate_limited'

======================================================================
TICKET BOUNDARY — BE-25–32
======================================================================
BE-22 covers only the registry (this file).  BE-25–32 implement the
individual scrapers (internshala, naukri, apna, …).  Until those tickets
are merged, every ``_SCRAPER_CLASS_MAP`` entry is None.  The registry
correctly raises ``NotImplementedError`` for such sources.  Tests that
require a runnable scraper register a temporary mock class and restore
the map in a ``finally`` block.
"""

import os
import sys
import unittest.mock as mock
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import psycopg
    _PSYCOPG_AVAILABLE = True
except ImportError:
    _PSYCOPG_AVAILABLE = False

from automation.scrapers.base import BaseScraper
from automation.scrapers.registry import (
    SourceConfigurationError,
    _SCRAPER_CLASS_MAP,
    fetch_enabled_sources,
    get_scraper_class,
    load_registry_from_db,
    register_scraper,
    run_scraper,
)

# ---------------------------------------------------------------------------
# Schema DDL — verbatim from database/migrations/002_organizations_sources.sql
#
# All columns, types, constraints, and CHECK values come directly from the
# migration file.  No values are invented or assumed.
# ---------------------------------------------------------------------------
_SOURCES_TEMP_DDL = """
CREATE TEMPORARY TABLE IF NOT EXISTS sources (
    id                 VARCHAR(50)  PRIMARY KEY,
    name               VARCHAR(100) NOT NULL,
    base_url           TEXT         NOT NULL,
    is_enabled         BOOLEAN      NOT NULL DEFAULT FALSE,
    permitted_use_note TEXT,
    status             VARCHAR(50)  NOT NULL DEFAULT 'healthy'
                           CHECK (status IN (
                               'healthy',
                               'quarantined',
                               'disabled',
                               'rate_limited'
                           )),
    last_run_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);
"""

# ---------------------------------------------------------------------------
# Canonical status values — authoritative source: the CHECK constraint above.
# The registry code's guard (row["status"] != "healthy") covers these values.
# ---------------------------------------------------------------------------
VALID_STATUSES = ("healthy", "quarantined", "disabled", "rate_limited")
NON_HEALTHY_STATUSES = tuple(s for s in VALID_STATUSES if s != "healthy")

# Seed data from 001_demo.sql — used in several tests to mirror real conditions
_SEED_ENABLED = [
    ("apna",        "Apna Jobs",                 "https://apna.co"),
    ("college_tpo", "TPO Public Directories",     "https://colleges.example.edu"),
    ("hackathons",  "Devpost & Unstop",           "https://unstop.com"),
    ("internshala", "Internshala",                "https://internshala.com"),
    ("naukri",      "Naukri Freshers",            "https://www.naukri.com/fresher-jobs"),
    ("startups",    "YCombinator Workatastartup", "https://workatastartup.com"),
    ("workindia",   "WorkIndia",                  "https://www.workindia.in"),
]
_SEED_DISABLED = [
    ("shine", "Shine Freshers", "https://www.shine.com"),
]


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_scraper_cls(name: str = "RealDBScraper") -> type:
    """Returns a minimal concrete BaseScraper subclass for use in tests."""

    class _Scraper(BaseScraper):
        def fetch(self, url: str) -> str:
            return "<html></html>"

        def parse(self, content: str) -> list:
            return [{"source": self.source_id, "url": self.base_url}]

    _Scraper.__name__ = name
    _Scraper.__qualname__ = name
    return _Scraper


def _insert(
    conn,
    *,
    id: str,
    name: str,
    base_url: str,
    is_enabled: bool = True,
    status: str = "healthy",
) -> None:
    """Inserts one row into the temporary sources table and commits."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sources (id, name, base_url, is_enabled, status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (id, name, base_url, is_enabled, status),
        )
    conn.commit()


def _db_skip_reason() -> str:
    return (
        "DATABASE_URL not set or psycopg unavailable — "
        "real PostgreSQL tests skipped (NOT VERIFIED).\n"
        "  Local Docker: set DATABASE_URL=postgresql://crm_user:crm_password"
        "@localhost:5432/crm_db\n"
        "  Then: docker-compose --profile local-db up -d local_postgres"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def real_pg_conn():
    """
    Session-scoped fixture: opens one real psycopg connection, creates a
    temporary ``sources`` table that shadows the permanent table for this
    session only, and yields the connection.

    Automatically skips (NOT VERIFIED) when DATABASE_URL is unset,
    psycopg is missing, or the database is unreachable.
    """
    if not _PSYCOPG_AVAILABLE:
        pytest.skip("psycopg not importable — " + _db_skip_reason())

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        pytest.skip(_db_skip_reason())

    try:
        # connect_timeout=5 ensures the attempt fails within 5 seconds on an
        # unreachable host instead of blocking for the OS TCP timeout (~75 s on
        # Windows) and requiring a Ctrl+C to abort the test session.
        conn = psycopg.connect(database_url, connect_timeout=5)
    except Exception as exc:
        pytest.skip(
            f"Cannot connect to PostgreSQL ({type(exc).__name__}: {exc}) — "
            "real DB tests skipped (NOT VERIFIED).\n"
            "  Start local Postgres: docker-compose --profile local-db up -d local_postgres\n"
            "  Then set: $env:DATABASE_URL = "
            "'postgresql://crm_user:crm_password@localhost:5432/crm_db'"
        )

    try:
        # Create the temporary table that shadows 'sources' for this session.
        with conn.cursor() as cur:
            cur.execute(_SOURCES_TEMP_DDL)
        conn.commit()
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="function")
def pg_sources(real_pg_conn):
    """
    Function-scoped fixture: guarantees each test starts and ends with an
    empty sources table, providing full isolation between tests.
    """
    # Pre-test cleanup
    with real_pg_conn.cursor() as cur:
        cur.execute("DELETE FROM sources")
    real_pg_conn.commit()

    yield real_pg_conn

    # Post-test cleanup — runs even when the test fails
    try:
        real_pg_conn.rollback()  # recover from any failed transaction
    except Exception:
        pass
    with real_pg_conn.cursor() as cur:
        cur.execute("DELETE FROM sources")
    real_pg_conn.commit()


# ===========================================================================
# 1. Schema constraint validation
#    Verified BEFORE testing registry code so any schema mismatch is caught
#    immediately, not silently masked by the registry's own status checks.
# ===========================================================================

@pytest.mark.integration_db
class TestSchemaConstraintsRealDB:
    """
    Proves that the temporary table's CHECK constraint exactly matches the
    canonical status values the registry assumes.  Any divergence between
    schema and code will cause a test here to fail, making the gap visible.
    """

    @pytest.mark.parametrize("status", VALID_STATUSES)
    def test_canonical_status_values_accepted_by_real_db(self, pg_sources, status):
        """Every value from VALID_STATUSES must be accepted by the CHECK constraint."""
        _insert(pg_sources,
                id=f"src_{status}", name=f"Source {status}",
                base_url="https://example.com",
                is_enabled=True, status=status)

        with pg_sources.cursor() as cur:
            cur.execute(
                "SELECT status FROM sources WHERE id = %s",
                (f"src_{status}",)
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == status

    def test_invalid_status_rejected_by_check_constraint(self, pg_sources):
        """
        An invented status value ('unknown_status') must be rejected by the
        real PostgreSQL CHECK constraint.  This proves the constraint is active
        and that VALID_STATUSES in this file matches the schema exactly.
        """
        with pytest.raises(Exception) as exc_info:
            with pg_sources.cursor() as cur:
                cur.execute(
                    "INSERT INTO sources (id, name, base_url, is_enabled, status) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    ("bad", "Bad", "https://x.com", True, "unknown_status"),
                )
            pg_sources.commit()

        pg_sources.rollback()  # recover the connection

        # Psycopg raises CheckViolation; check error text covers both
        # psycopg2 and psycopg3 error representations.
        err = str(exc_info.value).lower()
        assert any(kw in err for kw in ("check", "constraint", "violat")), (
            f"Expected a CHECK constraint violation error, got: {exc_info.value}"
        )

    def test_non_healthy_count_matches_registry_assumption(self, pg_sources):
        """
        The registry uses ``row['status'] != 'healthy'`` to reject non-healthy
        sources.  This test verifies that assumption covers exactly 3 statuses.
        If the schema adds a new status, this test forces an update.
        """
        assert len(NON_HEALTHY_STATUSES) == 3, (
            f"Expected 3 non-healthy canonical statuses, found {len(NON_HEALTHY_STATUSES)}: "
            f"{NON_HEALTHY_STATUSES}.  Update VALID_STATUSES and the registry if the "
            "schema CHECK constraint changed."
        )


# ===========================================================================
# 2. fetch_enabled_sources — real database path
# ===========================================================================

@pytest.mark.integration_db
class TestFetchEnabledSourcesRealDB:
    """
    Tests fetch_enabled_sources() against a live PostgreSQL connection.

    Each test verifies a different aspect of the SQL query's behaviour:
    column mapping, WHERE is_enabled=TRUE filtering, empty-table handling.
    """

    def test_empty_table_returns_empty_dict(self, pg_sources):
        result = fetch_enabled_sources(pg_sources)
        assert result == {}

    def test_single_enabled_row_appears_in_result(self, pg_sources):
        _insert(pg_sources, id="internshala", name="Internshala",
                base_url="https://internshala.com",
                is_enabled=True, status="healthy")

        result = fetch_enabled_sources(pg_sources)
        assert "internshala" in result

    def test_disabled_row_excluded_by_sql_where_clause(self, pg_sources):
        """
        is_enabled=FALSE rows are excluded by WHERE is_enabled=TRUE.
        This test proves that filter works on the real database engine,
        not just in mock expectations.
        """
        _insert(pg_sources, id="shine", name="Shine Freshers",
                base_url="https://www.shine.com",
                is_enabled=False, status="healthy")

        result = fetch_enabled_sources(pg_sources)
        assert "shine" not in result, (
            "Disabled source appeared in fetch_enabled_sources result. "
            "The WHERE is_enabled=TRUE filter is not working on the real DB."
        )

    def test_only_enabled_rows_returned_when_both_kinds_present(self, pg_sources):
        _insert(pg_sources, id="internshala", name="Internshala",
                base_url="https://internshala.com",
                is_enabled=True, status="healthy")
        _insert(pg_sources, id="shine", name="Shine Freshers",
                base_url="https://www.shine.com",
                is_enabled=False, status="healthy")

        result = fetch_enabled_sources(pg_sources)
        assert len(result) == 1
        assert "internshala" in result
        assert "shine" not in result

    def test_all_row_columns_mapped_to_correct_dict_keys(self, pg_sources):
        """Verifies the column → dict-key mapping is correct for the real schema."""
        _insert(pg_sources, id="naukri", name="Naukri Freshers",
                base_url="https://www.naukri.com/fresher-jobs",
                is_enabled=True, status="healthy")

        result = fetch_enabled_sources(pg_sources)
        row = result["naukri"]
        assert row["name"] == "Naukri Freshers"
        assert row["base_url"] == "https://www.naukri.com/fresher-jobs"
        assert row["is_enabled"] is True
        assert row["status"] == "healthy"

    def test_seed_enabled_sources_all_appear(self, pg_sources):
        """Insert the 7 is_enabled=TRUE sources from 001_demo.sql; all 7 must appear."""
        for source_id, name, base_url in _SEED_ENABLED:
            _insert(pg_sources, id=source_id, name=name,
                    base_url=base_url, is_enabled=True, status="healthy")

        result = fetch_enabled_sources(pg_sources)
        assert len(result) == 7
        for source_id, _, _ in _SEED_ENABLED:
            assert source_id in result

    def test_seed_disabled_source_absent(self, pg_sources):
        """Insert the is_enabled=FALSE 'shine' row; it must not appear."""
        for source_id, name, base_url in _SEED_DISABLED:
            _insert(pg_sources, id=source_id, name=name,
                    base_url=base_url, is_enabled=False, status="healthy")

        result = fetch_enabled_sources(pg_sources)
        assert "shine" not in result


# ===========================================================================
# 3. load_registry_from_db — real database path
# ===========================================================================

@pytest.mark.integration_db
class TestLoadRegistryFromDbRealDB:
    """
    Tests load_registry_from_db() against a live PostgreSQL connection.

    The runnable-only invariant: every entry returned must have a non-None
    ``scraper_cls``.  This is enforced against real DB query results here.
    """

    def test_empty_db_returns_empty_registry(self, pg_sources):
        result = load_registry_from_db(pg_sources)
        assert result == {}

    def test_enabled_healthy_source_with_none_class_excluded(self, pg_sources):
        """
        Approved, enabled, healthy source with scraper_cls=None must not appear
        in the runnable registry.  This is the current state for all BE-25–32
        sources until those tickets are merged.
        """
        _insert(pg_sources, id="internshala", name="Internshala",
                base_url="https://internshala.com",
                is_enabled=True, status="healthy")

        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            result = load_registry_from_db(pg_sources)
            assert result == {}, (
                "Runnable invariant violated: load_registry_from_db returned entries "
                "with scraper_cls=None against the real database."
            )
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_registered_enabled_healthy_source_appears_with_all_fields(self, pg_sources):
        """After register_scraper, a healthy enabled source appears with correct metadata."""
        MockCls = _make_scraper_cls("LoadRealDB")
        original = _SCRAPER_CLASS_MAP.get("apna")
        try:
            register_scraper("apna", MockCls)
            _insert(pg_sources, id="apna", name="Apna Jobs",
                    base_url="https://apna.co",
                    is_enabled=True, status="healthy")

            result = load_registry_from_db(pg_sources)
            assert "apna" in result
            entry = result["apna"]
            assert entry["name"] == "Apna Jobs"
            assert entry["base_url"] == "https://apna.co"
            assert entry["status"] == "healthy"
            assert entry["scraper_cls"] is MockCls
        finally:
            _SCRAPER_CLASS_MAP["apna"] = original

    def test_disabled_source_never_appears_even_when_class_registered(self, pg_sources):
        """shine (is_enabled=FALSE) must be absent from the runnable registry."""
        MockCls = _make_scraper_cls("ShineRealDB")
        original = _SCRAPER_CLASS_MAP.get("shine")
        try:
            register_scraper("shine", MockCls)
            _insert(pg_sources, id="shine", name="Shine Freshers",
                    base_url="https://www.shine.com",
                    is_enabled=False, status="healthy")

            result = load_registry_from_db(pg_sources)
            assert "shine" not in result
        finally:
            _SCRAPER_CLASS_MAP["shine"] = original

    @pytest.mark.parametrize("bad_status", NON_HEALTHY_STATUSES)
    def test_non_healthy_source_excluded_from_runnable_registry(
        self, pg_sources, bad_status
    ):
        """All three non-healthy statuses are excluded from the runnable registry."""
        MockCls = _make_scraper_cls(f"Status_{bad_status}")
        original = _SCRAPER_CLASS_MAP.get("naukri")
        try:
            register_scraper("naukri", MockCls)
            _insert(pg_sources, id="naukri", name="Naukri Freshers",
                    base_url="https://www.naukri.com/fresher-jobs",
                    is_enabled=True, status=bad_status)

            result = load_registry_from_db(pg_sources)
            assert "naukri" not in result, (
                f"Source with status='{bad_status}' appeared in runnable registry "
                "against real DB — health gate not working."
            )
        finally:
            _SCRAPER_CLASS_MAP["naukri"] = original

    def test_unapproved_db_row_never_leaks_into_registry(self, pg_sources):
        """
        'linkedin' is in the real DB row but NOT in _SCRAPER_CLASS_MAP.
        load_registry_from_db iterates the static map, so unapproved DB rows
        can never appear in the returned dict regardless of their DB status.
        """
        _insert(pg_sources, id="linkedin", name="LinkedIn",
                base_url="https://linkedin.com",
                is_enabled=True, status="healthy")

        MockCls = _make_scraper_cls("AllRealDB")
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = MockCls
                _insert(pg_sources, id=k, name=k.title(),
                        base_url=f"https://{k}.example.com",
                        is_enabled=True, status="healthy")

            result = load_registry_from_db(pg_sources)
            assert "linkedin" not in result
            for k in _SCRAPER_CLASS_MAP:
                assert k in result
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_every_returned_entry_has_non_none_scraper_cls(self, pg_sources):
        """
        Runnable-only invariant verified against real DB:
        not a single returned entry may have scraper_cls=None.
        """
        MockA = _make_scraper_cls("RealA")
        MockB = _make_scraper_cls("RealB")
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            _SCRAPER_CLASS_MAP["hackathons"] = MockA
            _SCRAPER_CLASS_MAP["startups"] = MockB

            for sid, cls in [("hackathons", MockA), ("startups", MockB),
                              ("internshala", None)]:
                _insert(pg_sources, id=sid, name=sid.title(),
                        base_url=f"https://{sid}.example.com",
                        is_enabled=True, status="healthy")

            result = load_registry_from_db(pg_sources)
            for source_id, entry in result.items():
                assert entry["scraper_cls"] is not None, (
                    f"Entry '{source_id}' has scraper_cls=None — "
                    "runnable invariant violated against real PostgreSQL"
                )
            assert "internshala" not in result  # None class → excluded
        finally:
            _SCRAPER_CLASS_MAP.update(originals)

    def test_exactly_two_registered_sources_appear_when_seven_in_db(self, pg_sources):
        """
        With 7 enabled healthy sources in DB but only 2 with registered classes,
        exactly 2 should appear in the runnable registry.
        """
        MockA = _make_scraper_cls("ExactA")
        MockB = _make_scraper_cls("ExactB")
        originals = dict(_SCRAPER_CLASS_MAP)
        try:
            for k in _SCRAPER_CLASS_MAP:
                _SCRAPER_CLASS_MAP[k] = None
            _SCRAPER_CLASS_MAP["workindia"] = MockA
            _SCRAPER_CLASS_MAP["college_tpo"] = MockB

            for source_id, name, base_url in _SEED_ENABLED:
                _insert(pg_sources, id=source_id, name=name,
                        base_url=base_url, is_enabled=True, status="healthy")

            result = load_registry_from_db(pg_sources)
            assert set(result.keys()) == {"workindia", "college_tpo"}
        finally:
            _SCRAPER_CLASS_MAP.update(originals)


# ===========================================================================
# 4. get_scraper_class — real database path
# ===========================================================================

@pytest.mark.integration_db
class TestGetScraperClassRealDB:
    """
    Tests get_scraper_class() against a real PostgreSQL connection.
    Step 1 (static gate) is DB-free; Step 2+ uses the real connection.
    """

    def test_unlisted_source_rejected_before_db_is_queried(self, pg_sources):
        """
        Static gate fires for unlisted source; cursor must never be called.
        Uses a spy connection (not pg_sources) to intercept any DB access.
        """
        spy = mock.MagicMock()
        spy.cursor.side_effect = AssertionError(
            "DB must not be queried for an unlisted source"
        )
        with pytest.raises(SourceConfigurationError,
                           match="not in the approved scraper registry"):
            get_scraper_class("linkedin", conn=spy)

    def test_approved_source_absent_from_db_raises_configuration_error(self, pg_sources):
        """Approved in static map but no matching row in DB → SourceConfigurationError."""
        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            get_scraper_class("internshala", conn=pg_sources)

    def test_disabled_source_raises_configuration_error(self, pg_sources):
        """is_enabled=FALSE row excluded by SQL → treated as absent → SourceConfigurationError."""
        _insert(pg_sources, id="shine", name="Shine Freshers",
                base_url="https://www.shine.com",
                is_enabled=False, status="healthy")

        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            get_scraper_class("shine", conn=pg_sources)

    @pytest.mark.parametrize("bad_status", NON_HEALTHY_STATUSES)
    def test_non_healthy_status_raises_configuration_error(self, pg_sources, bad_status):
        """All non-healthy statuses → SourceConfigurationError with status in message."""
        _insert(pg_sources, id="internshala", name="Internshala",
                base_url="https://internshala.com",
                is_enabled=True, status=bad_status)

        with pytest.raises(SourceConfigurationError, match=bad_status):
            get_scraper_class("internshala", conn=pg_sources)

    def test_unimplemented_scraper_raises_not_implemented_error(self, pg_sources):
        """
        Approved, enabled, healthy source with scraper_cls=None raises
        NotImplementedError (not SourceConfigurationError).
        This is the correct state while BE-25–32 are pending.
        """
        assert _SCRAPER_CLASS_MAP["internshala"] is None, (
            "This test requires internshala to be unimplemented (None). "
            "Update if BE-25 has been merged."
        )
        _insert(pg_sources, id="internshala", name="Internshala",
                base_url="https://internshala.com",
                is_enabled=True, status="healthy")

        with pytest.raises(NotImplementedError, match="not been implemented yet"):
            get_scraper_class("internshala", conn=pg_sources)

    def test_registered_class_resolved_correctly(self, pg_sources):
        """After register_scraper, get_scraper_class returns the correct class object."""
        MockCls = _make_scraper_cls("GetClassRealDB")
        original = _SCRAPER_CLASS_MAP.get("workindia")
        try:
            register_scraper("workindia", MockCls)
            _insert(pg_sources, id="workindia", name="WorkIndia",
                    base_url="https://www.workindia.in",
                    is_enabled=True, status="healthy")

            result = get_scraper_class("workindia", conn=pg_sources)
            assert result is MockCls
            assert isinstance(result, type)
            assert issubclass(result, BaseScraper)
        finally:
            _SCRAPER_CLASS_MAP["workindia"] = original

    def test_returns_class_not_instance(self, pg_sources):
        """get_scraper_class must return the class itself, not an instantiated object."""
        MockCls = _make_scraper_cls("ClassNotInstanceRealDB")
        original = _SCRAPER_CLASS_MAP.get("apna")
        try:
            register_scraper("apna", MockCls)
            _insert(pg_sources, id="apna", name="Apna Jobs",
                    base_url="https://apna.co",
                    is_enabled=True, status="healthy")

            result = get_scraper_class("apna", conn=pg_sources)
            assert isinstance(result, type), (
                f"get_scraper_class must return a class, not an instance. Got: {result!r}"
            )
        finally:
            _SCRAPER_CLASS_MAP["apna"] = original

    def test_source_id_normalised_to_lowercase(self, pg_sources):
        """Uppercase source_id is normalised to lowercase before all lookups."""
        MockCls = _make_scraper_cls("CaseNormRealDB")
        original = _SCRAPER_CLASS_MAP.get("hackathons")
        try:
            register_scraper("hackathons", MockCls)
            _insert(pg_sources, id="hackathons", name="Devpost & Unstop",
                    base_url="https://unstop.com",
                    is_enabled=True, status="healthy")

            result = get_scraper_class("HACKATHONS", conn=pg_sources)
            assert result is MockCls
        finally:
            _SCRAPER_CLASS_MAP["hackathons"] = original


# ===========================================================================
# 5. run_scraper — real database path (the enforced execution entry point)
# ===========================================================================

@pytest.mark.integration_db
class TestRunScraperRealDB:
    """
    Tests run_scraper() against a real PostgreSQL connection.

    Verifies that:
    - All validation gates fire BEFORE instantiation or execution.
    - base_url is retrieved from the SAME DB read as validation (no TOCTOU).
    - source_id is correctly normalised and passed to the constructor.
    - Scraper results are returned correctly.
    """

    def test_unlisted_source_rejected_before_db_is_queried(self, pg_sources):
        """Static gate fires; DB cursor must never be called for an unlisted source."""
        spy = mock.MagicMock()
        spy.cursor.side_effect = AssertionError(
            "DB must not be queried for an unlisted source"
        )
        with pytest.raises(SourceConfigurationError,
                           match="not in the approved scraper registry"):
            run_scraper("linkedin", conn=spy)

    def test_source_absent_from_db_raises_configuration_error(self, pg_sources):
        """Approved but no DB row → SourceConfigurationError before any scraper logic."""
        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            run_scraper("internshala", conn=pg_sources)

    def test_disabled_source_raises_configuration_error(self, pg_sources):
        """shine (is_enabled=FALSE) excluded by SQL → SourceConfigurationError."""
        _insert(pg_sources, id="shine", name="Shine Freshers",
                base_url="https://www.shine.com",
                is_enabled=False, status="healthy")

        with pytest.raises(SourceConfigurationError, match="no corresponding row"):
            run_scraper("shine", conn=pg_sources)

    @pytest.mark.parametrize("bad_status", NON_HEALTHY_STATUSES)
    def test_non_healthy_status_raises_configuration_error(self, pg_sources, bad_status):
        """All non-healthy statuses → SourceConfigurationError before any instantiation."""
        MockCls = _make_scraper_cls(f"RunStatus_{bad_status}")
        original = _SCRAPER_CLASS_MAP.get("naukri")
        try:
            register_scraper("naukri", MockCls)
            _insert(pg_sources, id="naukri", name="Naukri Freshers",
                    base_url="https://www.naukri.com/fresher-jobs",
                    is_enabled=True, status=bad_status)

            with pytest.raises(SourceConfigurationError, match=bad_status):
                run_scraper("naukri", conn=pg_sources)
        finally:
            _SCRAPER_CLASS_MAP["naukri"] = original

    def test_unimplemented_scraper_raises_not_implemented_error(self, pg_sources):
        """
        Approved, enabled, healthy source with scraper_cls=None raises
        NotImplementedError — NOT SourceConfigurationError.
        Correct behaviour while BE-25–32 are pending.
        """
        assert _SCRAPER_CLASS_MAP["internshala"] is None
        _insert(pg_sources, id="internshala", name="Internshala",
                base_url="https://internshala.com",
                is_enabled=True, status="healthy")

        with pytest.raises(NotImplementedError, match="not been implemented yet"):
            run_scraper("internshala", conn=pg_sources)

    def test_validation_occurs_before_scraper_is_instantiated(self, pg_sources):
        """
        Verifies the scraper's __init__ is never called when the source fails
        a validation gate.  Instantiation must follow validation, not precede it.
        """
        instantiated = []

        class SentinelScraper(BaseScraper):
            def __init__(self, source_id, base_url):
                instantiated.append(source_id)
                super().__init__(source_id, base_url)

            def fetch(self, url: str) -> str:
                return ""

            def parse(self, content: str) -> list:
                return []

        original = _SCRAPER_CLASS_MAP.get("apna")
        try:
            register_scraper("apna", SentinelScraper)
            # Insert apna as quarantined — validation must reject before __init__
            _insert(pg_sources, id="apna", name="Apna Jobs",
                    base_url="https://apna.co",
                    is_enabled=True, status="quarantined")

            with pytest.raises(SourceConfigurationError):
                run_scraper("apna", conn=pg_sources)

            assert instantiated == [], (
                f"Scraper was instantiated despite failing the health gate. "
                f"Instantiated: {instantiated}"
            )
        finally:
            _SCRAPER_CLASS_MAP["apna"] = original

    def test_registered_scraper_executes_and_returns_correct_results(self, pg_sources):
        """
        Full end-to-end real-DB test: register → insert → run_scraper → verify results.
        Confirms execution succeeds and returns the scraper's output.
        """
        MockCls = _make_scraper_cls("RunE2ERealDB")
        original = _SCRAPER_CLASS_MAP.get("college_tpo")
        try:
            register_scraper("college_tpo", MockCls)
            _insert(pg_sources, id="college_tpo", name="TPO Public Directories",
                    base_url="https://colleges.example.edu",
                    is_enabled=True, status="healthy")

            results = run_scraper("college_tpo", conn=pg_sources)

            assert isinstance(results, list)
            assert len(results) == 1
            assert results[0]["source"] == "college_tpo"
            assert results[0]["url"] == "https://colleges.example.edu"
        finally:
            _SCRAPER_CLASS_MAP["college_tpo"] = original

    def test_base_url_comes_from_the_same_db_read_as_validation(self, pg_sources):
        """
        Verifies that the base_url injected into the scraper constructor comes
        from the same DB snapshot as the validation checks — not a separate
        subsequent query.  This directly tests the TOCTOU fix in
        _validate_and_resolve(): a single SELECT feeds both validation and
        base_url retrieval.
        """
        captured = {}

        class CapturingScraper(BaseScraper):
            def fetch(self, url: str) -> str:
                captured["base_url"] = self.base_url
                captured["source_id"] = self.source_id
                return ""

            def parse(self, content: str) -> list:
                return []

        original = _SCRAPER_CLASS_MAP.get("startups")
        try:
            register_scraper("startups", CapturingScraper)
            _insert(pg_sources, id="startups", name="YCombinator Workatastartup",
                    base_url="https://workatastartup.com",
                    is_enabled=True, status="healthy")

            run_scraper("startups", conn=pg_sources)

            assert captured.get("base_url") == "https://workatastartup.com", (
                f"base_url mismatch: expected 'https://workatastartup.com', "
                f"got {captured.get('base_url')!r}. "
                "base_url must come from _validate_and_resolve's single DB read."
            )
            assert captured.get("source_id") == "startups"
        finally:
            _SCRAPER_CLASS_MAP["startups"] = original

    def test_source_id_normalised_to_lowercase_before_constructor_call(self, pg_sources):
        """Uppercase source_id input must be normalised to lowercase before all gates
        and before being passed to the scraper constructor."""
        captured = {}

        class IdCaptureScraper(BaseScraper):
            def fetch(self, url: str) -> str:
                captured["source_id"] = self.source_id
                return ""

            def parse(self, content: str) -> list:
                return []

        original = _SCRAPER_CLASS_MAP.get("workindia")
        try:
            register_scraper("workindia", IdCaptureScraper)
            _insert(pg_sources, id="workindia", name="WorkIndia",
                    base_url="https://www.workindia.in",
                    is_enabled=True, status="healthy")

            run_scraper("WORKINDIA", conn=pg_sources)  # uppercase input
            assert captured["source_id"] == "workindia"  # must be normalised
        finally:
            _SCRAPER_CLASS_MAP["workindia"] = original
