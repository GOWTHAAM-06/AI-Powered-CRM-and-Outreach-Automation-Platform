"""
Approved Scraper Registry (BE-22).

Maps validated source keys to their respective Scraper implementation classes.
Fetches only enabled sources (``is_enabled = TRUE``) from the ``sources``
database table via ``fetch_enabled_sources``, mapping each to its scraper class.

Design:
  - ``_SCRAPER_CLASS_MAP`` is the **static approved-source list**.  A key's
    PRESENCE here is what makes a source "approved/listed".  All values start
    as None until the individual scraper modules (BE-25..32) call
    ``register_scraper``.
  - ``load_registry_from_db`` returns only **runnable** sources: approved in
    the static map, enabled and healthy in the DB, AND with a concrete scraper
    class already registered.  Unimplemented (None) entries are always excluded.
  - ``run_scraper`` is the single enforced execution entry-point.  It performs
    a single atomic DB read that covers all three validation gates AND retrieves
    ``base_url`` — eliminating any TOCTOU window.

Enforcement rules:
  - A source key not present in the static registry raises SourceConfigurationError.
  - ``fetch_enabled_sources`` loads only DB rows where ``is_enabled = TRUE``
    (disabled sources are excluded at the SQL level).
  - A source that is non-healthy in the DB is rejected at resolution time.
  - Scraper classes that have not yet been implemented raise NotImplementedError.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple, Type

import psycopg

from automation.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Static approved-source registry
# ---------------------------------------------------------------------------
# Keys are the canonical source IDs stored in `sources.id`.
# Values are the concrete BaseScraper subclasses (None = not yet implemented).
# A key's PRESENCE here is what makes a source "approved/listed".
# ---------------------------------------------------------------------------
_SCRAPER_CLASS_MAP: Dict[str, Optional[Type[BaseScraper]]] = {
    "internshala": None,   # BE-25
    "naukri": None,        # BE-26
    "apna": None,          # BE-27
    "workindia": None,     # BE-28
    "shine": None,         # BE-29
    "hackathons": None,    # BE-30
    "college_tpo": None,   # BE-31
    "startups": None,      # BE-32
}


class SourceConfigurationError(ValueError):
    """
    Raised when a source key is unrecognised, disabled, or not approved
    for execution.  Subclasses ValueError so callers can catch it generically.
    """


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_database_url() -> str:
    """
    Returns the DATABASE_URL connection string.
    Reads from the environment variable; raises SourceConfigurationError if absent.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SourceConfigurationError(
            "DATABASE_URL environment variable is not set. "
            "Cannot fetch source status from the database."
        )
    return url


def fetch_enabled_sources(conn: psycopg.Connection) -> Dict[str, dict]:
    """
    Queries the ``sources`` table and returns a mapping of
    source_id -> {is_enabled, status, name, base_url}
    for rows where ``is_enabled = TRUE`` only.

    Disabled sources are excluded at the SQL level so that the returned dict
    contains only sources that are candidates for execution.  Runtime checks
    for approved status and health are still enforced by callers.

    Uses the caller-supplied connection so that tests can inject a mock
    connection without touching a real database.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, base_url, is_enabled, status
            FROM sources
            WHERE is_enabled = TRUE
            ORDER BY id;
            """
        )
        rows = cur.fetchall()

    return {
        row[0]: {
            "name": row[1],
            "base_url": row[2],
            "is_enabled": row[3],
            "status": row[4],
        }
        for row in rows
    }


def _validate_and_resolve(
    key: str,
    source_id: str,
    db_conn: psycopg.Connection,
) -> Tuple[Type[BaseScraper], str]:
    """
    Single atomic DB read that enforces all runtime gates and returns the
    resolved scraper class together with the base_url from the same DB snapshot.

    Performing both steps in a single read eliminates the TOCTOU window that
    would exist if validation and base_url retrieval were separate queries.

    Enforcement order:
      1. Source present in DB with is_enabled=TRUE (SQL-level gate).
      2. Source status == 'healthy'.
      3. Scraper class is registered (not None).

    Returns:
        (scraper_cls, base_url) tuple ready for instantiation.

    Raises:
        SourceConfigurationError: if the source fails any DB-level gate.
        NotImplementedError:      if the scraper class is not yet implemented.
    """
    db_sources = fetch_enabled_sources(db_conn)

    if key not in db_sources:
        raise SourceConfigurationError(
            f"Source '{source_id}' is approved in the registry but has no "
            "corresponding row in the `sources` database table. "
            "Seed or insert the source record before executing."
        )

    row = db_sources[key]

    if row["status"] != "healthy":
        raise SourceConfigurationError(
            f"Source '{source_id}' has status '{row['status']}' "
            "and cannot be executed. Only sources with status='healthy' "
            "are eligible for scraping."
        )

    scraper_cls = _SCRAPER_CLASS_MAP[key]
    if scraper_cls is None:
        raise NotImplementedError(
            f"Source '{source_id}' is approved and enabled, but its scraper "
            "class has not been implemented yet. "
            f"See the task ticket for source '{key}' in the project task sheet."
        )

    return scraper_cls, row["base_url"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_source_approved(source_id: str) -> bool:
    """
    Returns True if source_id is present in the static approved registry.
    Does NOT consult the database; use get_scraper_class() for full enforcement.
    """
    return source_id.lower() in _SCRAPER_CLASS_MAP


def get_scraper_class(
    source_id: str,
    conn: Optional[psycopg.Connection] = None,
) -> Type[BaseScraper]:
    """
    Resolves a source key to its concrete BaseScraper subclass.

    Enforcement order:
      1. Reject if the key is not in the static approved registry
         (SourceConfigurationError).
      2. Single atomic DB read to verify the source is enabled, healthy,
         and the scraper class is registered.

    Args:
        source_id: The canonical source identifier (must match sources.id).
        conn:      Optional psycopg connection for testing.  When omitted, a
                   fresh connection is opened using DATABASE_URL.

    Returns:
        The concrete BaseScraper subclass (not an instance).

    Raises:
        SourceConfigurationError: Source not in registry, disabled, or not in DB.
        NotImplementedError:      Source is approved but scraper not yet built.
    """
    key = source_id.lower()

    # --- Step 1: Static registry gate (no DB needed) ---
    if key not in _SCRAPER_CLASS_MAP:
        raise SourceConfigurationError(
            f"Source '{source_id}' is not in the approved scraper registry. "
            "Only listed and approved sources may be executed."
        )

    # --- Step 2: Single atomic DB enforcement ---
    if conn is not None:
        scraper_cls, _ = _validate_and_resolve(key, source_id, conn)
    else:
        database_url = _get_database_url()
        with psycopg.connect(database_url) as live_conn:
            scraper_cls, _ = _validate_and_resolve(key, source_id, live_conn)

    return scraper_cls


def load_registry_from_db(conn: psycopg.Connection) -> Dict[str, dict]:
    """
    Returns the **runnable** live registry: the subset of approved sources
    that are currently enabled, healthy, AND have a concrete scraper class
    registered (i.e. ``register_scraper`` has been called for them).

    Sources with ``scraper_cls = None`` (pending BE-25..32) are always excluded
    so that callers can trust every entry in the returned mapping is immediately
    executable.  This invariant prevents orchestration code from iterating over
    entries it believes are runnable when they are not.

    Sources that are approved but not yet in the DB, or that are disabled /
    non-healthy, are silently excluded (logged at WARNING level).

    Args:
        conn: A live (or mock) psycopg connection.

    Returns:
        Dict mapping source_id -> {name, base_url, status, scraper_cls}.
        Every ``scraper_cls`` value in the returned dict is a concrete non-None
        BaseScraper subclass.
    """
    db_sources = fetch_enabled_sources(conn)
    registry: Dict[str, dict] = {}

    for source_id, scraper_cls in _SCRAPER_CLASS_MAP.items():
        # Exclude sources whose scraper class is not yet implemented.
        # They are approved but not runnable; callers must not see them
        # as ready-to-execute entries.
        if scraper_cls is None:
            logger.debug(
                "Approved source '%s' has no registered scraper class yet "
                "(pending BE-25..32); excluded from runnable registry.",
                source_id,
            )
            continue

        if source_id not in db_sources:
            logger.warning(
                "Approved source '%s' is not present in the database with "
                "is_enabled=TRUE. It will be excluded from the live registry.",
                source_id,
            )
            continue

        row = db_sources[source_id]

        if row["status"] != "healthy":
            logger.warning(
                "Approved source '%s' has status '%s' and will be excluded "
                "from the live registry until it returns to 'healthy'.",
                source_id,
                row["status"],
            )
            continue

        registry[source_id] = {
            "name": row["name"],
            "base_url": row["base_url"],
            "status": row["status"],
            "scraper_cls": scraper_cls,
        }
        logger.debug(
            "Live registry: loaded source '%s' (scraper=%s).",
            source_id,
            scraper_cls.__name__,
        )

    logger.info(
        "load_registry_from_db: %d runnable sources out of %d approved.",
        len(registry),
        len(_SCRAPER_CLASS_MAP),
    )
    return registry


def register_scraper(source_id: str, scraper_cls: Type[BaseScraper]) -> None:
    """
    Registers or updates the scraper class for an approved source key.

    Intended for use by individual scraper modules (BE-25..32) so they can
    self-register without circular imports:

        from automation.scrapers.registry import register_scraper
        from automation.scrapers.sources.internshala import IntershalaScraper
        register_scraper("internshala", IntershalaScraper)

    Args:
        source_id:   The canonical source key (must already exist in the registry).
        scraper_cls: A concrete subclass of BaseScraper.

    Raises:
        SourceConfigurationError: If source_id is not in the approved registry.
        TypeError:                If scraper_cls is not a BaseScraper subclass.
    """
    key = source_id.lower()
    if key not in _SCRAPER_CLASS_MAP:
        raise SourceConfigurationError(
            f"Cannot register scraper for '{source_id}': "
            "the source key is not in the approved registry."
        )
    if not (isinstance(scraper_cls, type) and issubclass(scraper_cls, BaseScraper)):
        raise TypeError(
            f"scraper_cls must be a subclass of BaseScraper, got {scraper_cls!r}"
        )
    _SCRAPER_CLASS_MAP[key] = scraper_cls
    logger.info(
        "Registered scraper class %s for source '%s'.", scraper_cls.__name__, key
    )


def run_scraper(
    source_id: str,
    conn: Optional[psycopg.Connection] = None,
) -> List[Dict]:
    """
    Single enforced entry-point for executing a scraper.

    Performs one atomic DB read that covers ALL validation gates (DB presence,
    enabled status, health status, scraper class registration) AND retrieves
    ``base_url`` from the same snapshot.  This eliminates the TOCTOU window
    that would exist if validation and base_url retrieval were separate queries.

    Enforcement order within the single DB read:
      1. Static registry gate (no DB involved — fast-fail for unlisted sources).
      2. Source present in DB with is_enabled=TRUE (SQL-level gate).
      3. Source status == 'healthy'.
      4. Scraper class is registered (not None).
      Then: scraper is instantiated and run() is called.

    Args:
        source_id: The canonical source identifier (must match sources.id).
        conn:      Optional psycopg connection for testing.  When omitted, a
                   fresh connection is opened using DATABASE_URL.

    Returns:
        The list of raw extracted records returned by the scraper's ``run()``.

    Raises:
        SourceConfigurationError: Source not in registry, disabled, or not in DB.
        NotImplementedError:      Source is approved but scraper not yet built.
    """
    key = source_id.lower()

    # Gate 1: static approval — no DB query needed
    if key not in _SCRAPER_CLASS_MAP:
        raise SourceConfigurationError(
            f"Source '{source_id}' is not in the approved scraper registry. "
            "Only listed and approved sources may be executed."
        )

    # Gates 2, 3, 4 + base_url — single atomic DB read, no TOCTOU
    if conn is not None:
        scraper_cls, base_url = _validate_and_resolve(key, source_id, conn)
    else:
        database_url = _get_database_url()
        with psycopg.connect(database_url) as live_conn:
            scraper_cls, base_url = _validate_and_resolve(key, source_id, live_conn)

    logger.info(
        "run_scraper: launching %s for source '%s' at %s.",
        scraper_cls.__name__,
        key,
        base_url,
    )
    instance = scraper_cls(source_id=key, base_url=base_url)
    return instance.run()
