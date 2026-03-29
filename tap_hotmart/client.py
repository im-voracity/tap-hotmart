from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from datetime import UTC, datetime
import logging
from typing import Any

from hotmart import AuthenticationError, Hotmart, NotFoundError
from singer_sdk.exceptions import ConfigValidationError

logger = logging.getLogger(__name__)

# Type alias for SDK page-fetching callables
_PageCallable = Callable[..., Any]


class HotmartClient:
    """Thin wrapper around the hotmart-python SDK.

    Responsibilities:
    - Validate tap configuration (raises ConfigValidationError on bad input)
    - Convert ISO 8601 start dates to millisecond timestamps
    - Expose a shared pagination helper used by all streams
    - Proxy SDK resource accessors (sales, subscriptions, products)
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._validate_config(config)
        self._sdk = Hotmart(
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            basic=config["basic"],
            sandbox=config.get("sandbox", False),
        )

    # ------------------------------------------------------------------
    # Config validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_config(config: Mapping[str, Any]) -> None:
        """Raise ConfigValidationError early, before any API call."""
        required_str = ("client_id", "client_secret", "basic")
        for field in required_str:
            if not config.get(field):
                msg = f"Configuration error: '{field}' is required and must not be empty."
                raise ConfigValidationError(msg)

        if "start_date" not in config or config["start_date"] is None:
            raise ConfigValidationError("Configuration error: 'start_date' is required.")

        try:
            datetime.fromisoformat(config["start_date"].replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            msg = f"Configuration error: 'start_date' must be a valid ISO 8601 string, got: {config['start_date']!r}"
            raise ConfigValidationError(msg) from exc

    # ------------------------------------------------------------------
    # Timestamp helpers
    # ------------------------------------------------------------------

    @staticmethod
    def iso_to_ms(date_str: str) -> int:
        """Convert an ISO 8601 string to a millisecond epoch timestamp."""
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)

    # ------------------------------------------------------------------
    # Primary key helper
    # ------------------------------------------------------------------

    @staticmethod
    def has_primary_key(record: dict[str, Any], key: str) -> bool:
        """Return True only when the primary key field is present and non-None.

        Supports simple flat keys only (e.g. 'transaction', 'subscriber_code').
        """
        return bool(record.get(key))

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    @staticmethod
    def _paginate(
        sdk_callable: _PageCallable,
        *,
        skip_not_found: bool = False,
        **kwargs: Any,
    ) -> Generator[Any, None, None]:
        """Yield pages from a cursor-based SDK endpoint.

        Args:
            sdk_callable: A bound SDK method (e.g. client.sales.history).
            skip_not_found: If True, log a warning on NotFoundError and return
                instead of re-raising. All other errors propagate unchanged.
            **kwargs: Extra keyword arguments forwarded to sdk_callable on every call
                (e.g. start_date=<ms>, end_date=<ms>).
        """
        page_token: str | None = None

        while True:
            try:
                page = sdk_callable(page_token=page_token, **kwargs)
            except NotFoundError as exc:
                if not skip_not_found:
                    raise
                logger.warning("Resource not found (404), skipping: %s", exc)
                return
            except AuthenticationError:
                raise

            if not page or not page.items:
                break

            yield page

            next_token = page.page_info.next_page_token if page.page_info else None
            if not next_token:
                break

            page_token = next_token

    # ------------------------------------------------------------------
    # SDK resource proxies
    # ------------------------------------------------------------------

    @property
    def sales(self) -> Any:
        return self._sdk.sales

    @property
    def subscriptions(self) -> Any:
        return self._sdk.subscriptions

    @property
    def products(self) -> Any:
        return self._sdk.products
