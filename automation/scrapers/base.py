"""
Base Scraper Class.
Provides resilient extraction framework, error capture, and human-like request pacing.
"""

import abc
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# --- 1. Custom Exception Hierarchy ---
class ScraperException(Exception):
    """Base exception for all scraper errors."""
    pass


class SelectorNotFoundError(ScraperException):
    """Raised when an expected DOM element/selector is missing or changed."""
    pass


class RateLimitedError(ScraperException):
    """Raised when HTTP 429 Too Many Requests is encountered."""
    pass


class AccessDeniedError(ScraperException):
    """Raised when HTTP 403 Forbidden is encountered."""
    pass


class NetworkTimeoutError(ScraperException):
    """Raised when a network request times out."""
    pass


# --- 2. Base Scraper Implementation ---
class BaseScraper(abc.ABC):
    def __init__(self, source_id: str, base_url: str, snapshot_dir: str = "snapshots"):
        self.source_id = source_id
        self.base_url = base_url
        self.snapshot_dir = snapshot_dir
        self.is_rate_limited = False  # Track if source is currently halted

    def human_delay(self, min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """Injects human-like random pause between page transitions."""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def _save_snapshot(self, html_content: str, max_kb: int = 50) -> Optional[str]:
        """
        Saves a size-capped HTML snapshot (max 50KB) on selector failure for AI diagnosis.
        The cap is strictly clamped to an unconditional maximum of 50KB.
        """
        if not html_content:
            return None

        os.makedirs(self.snapshot_dir, exist_ok=True)
        filename = os.path.join(self.snapshot_dir, f"{self.source_id}_selector_failure.html")

        # Clamp max_kb so it can never exceed the 50 KB requirement
        effective_kb = min(max_kb, 50)
        max_bytes = effective_kb * 1024

        encoded = html_content.encode("utf-8")[:max_bytes]
        capped_content = encoded.decode("utf-8", errors="ignore")

        with open(filename, "w", encoding="utf-8") as f:
            f.write(capped_content)

        logger.warning(
            "Saved selector failure snapshot for [%s] to %s (%d bytes).",
            self.source_id,
            filename,
            len(capped_content.encode("utf-8")),
        )
        return filename

    def _extract_status_code(self, exc: Exception) -> Optional[int]:
        """Inspects exception attributes for HTTP status codes (requests, httpx, urllib)."""
        if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
            return getattr(exc.response, "status_code")
        if hasattr(exc, "status_code"):
            return getattr(exc, "status_code")
        if hasattr(exc, "code"):  # urllib.error.HTTPError
            return getattr(exc, "code")
        return None

    @abc.abstractmethod
    def fetch(self, url: str) -> str:
        """Retrieves raw HTML or JSON from approved target source."""
        pass

    @abc.abstractmethod
    def parse(self, content: str) -> List[Dict[str, Any]]:
        """Parses raw content into standardized lead extraction dictionaries."""
        pass

    def run(self) -> List[Dict[str, Any]]:
        """
        Executes scrape workflow with resilient exception handling.
        Halts immediately if HTTP 429 was encountered.
        """
        # Halt check: HTTP 429 immediately stops further requests for that source
        if self.is_rate_limited:
            logger.error(
                "Scraper [%s] is halted due to HTTP 429 rate limit. Aborting request.",
                self.source_id,
            )
            return []

        logger.info("Executing scraper for source: %s (%s)", self.source_id, self.base_url)
        content = ""

        try:
            # Random delay 1-3 seconds before outgoing request
            self.human_delay()

            # 1. Fetch
            content = self.fetch(self.base_url)

            # 2. Parse
            results = self.parse(content)
            logger.info("Scraper [%s] extracted %d records.", self.source_id, len(results))
            return results

        # Explicit custom exceptions
        except RateLimitedError as exc:
            self.is_rate_limited = True
            logger.error(
                "HTTP 429 rate limit reached for source [%s]. Halting further requests: %s",
                self.source_id,
                exc,
            )
            return []

        except AccessDeniedError as exc:
            logger.error("HTTP 403 Forbidden for source [%s]: %s", self.source_id, exc)
            return []

        except (NetworkTimeoutError, TimeoutError) as exc:
            logger.error("Network timeout for source [%s]: %s", self.source_id, exc)
            return []

        except SelectorNotFoundError as exc:
            logger.error("DOM Selector missing or changed for [%s]: %s", self.source_id, exc)
            if content:
                self._save_snapshot(content)
            return []

        # Generic exception handling relying strictly on HTTP status attributes
        except Exception as exc:
            status_code = self._extract_status_code(exc)
            exc_name = type(exc).__name__.lower()

            if status_code == 429:
                self.is_rate_limited = True
                logger.error(
                    "HTTP 429 detected for source [%s]. Halting future requests: %s",
                    self.source_id,
                    exc,
                )
            elif status_code == 403:
                logger.error("HTTP 403 Forbidden for source [%s]: %s", self.source_id, exc)
            elif "timeout" in exc_name:
                logger.error("Network timeout encountered for source [%s]: %s", self.source_id, exc)
            else:
                logger.error("Scraper [%s] encountered unexpected error: %s", self.source_id, exc)
            return []