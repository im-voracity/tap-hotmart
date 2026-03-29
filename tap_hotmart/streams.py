from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from singer_sdk import SchemaDirectory, Stream, StreamSchema

from tap_hotmart.client import HotmartClient

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Mapping

    from singer_sdk import Tap

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).parent / "schemas"
_schema_source = SchemaDirectory(SCHEMAS_DIR)


class HotmartStream(Stream):
    """Base class for all tap-hotmart streams.

    Provides shared helpers: ISO-to-ms conversion, primary key checking,
    and the per-page state flush pattern.
    """

    def __init__(self, tap: Tap, hotmart_client: HotmartClient) -> None:
        super().__init__(tap)
        self.hotmart_client = hotmart_client

    @staticmethod
    def _iso_to_ms(date_str: str) -> int:
        return HotmartClient.iso_to_ms(date_str)

    def _has_primary_key(self, record: Mapping[str, Any]) -> bool:
        """Return True only when every declared primary key is present and non-None."""
        return all(record.get(key) for key in self.primary_keys or [])

    def _start_date_ms(self, context: Mapping[str, Any] | None) -> int:
        """Return the effective start timestamp in milliseconds.

        Uses the replication bookmark from state when available; falls back to
        the configured start_date on the first run.

        The Singer SDK may store either an integer ms value (from a prior run)
        or an ISO 8601 string (from config's start_date on first run), so both
        forms are handled here.
        """
        value = self.get_starting_replication_key_value(context)
        if value is None:
            return self._iso_to_ms(str(self.config["start_date"]))
        if isinstance(value, (int, float)):
            return int(value)
        # String from config (e.g. "2024-01-01T00:00:00Z") stored by the SDK
        return self._iso_to_ms(str(value))

    @staticmethod
    def _date_chunks(start_ms: int, chunk_days: int = 30) -> Generator[tuple[int, int], None, None]:
        """Yield (chunk_start_ms, chunk_end_ms) covering [start_ms, now] in chunk_days intervals.

        Splits long date ranges to stay within the Hotmart API's undocumented per-request limit.
        """
        now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
        chunk_ms = chunk_days * 24 * 60 * 60 * 1000
        chunk_start = start_ms
        while chunk_start < now_ms:
            chunk_end = min(chunk_start + chunk_ms, now_ms)
            yield chunk_start, chunk_end
            chunk_start = chunk_end + 1

    def get_records(self, context: Mapping[str, Any] | None) -> Iterable[dict]:
        raise NotImplementedError  # each subclass must override


# ---------------------------------------------------------------------------
# TransactionStream
# ---------------------------------------------------------------------------


class TransactionStream(HotmartStream):
    name = "transactions"
    primary_keys: ClassVar[list[str]] = ["transaction"]
    replication_method = "INCREMENTAL"
    replication_key = "approved_date"
    schema = StreamSchema(_schema_source)

    def get_records(self, context: Mapping[str, Any] | None) -> Iterable[dict]:
        start_ms = self._start_date_ms(context)

        for chunk_start, chunk_end in self._date_chunks(start_ms):
            for page in HotmartClient._paginate(
                self.hotmart_client.sales.history,
                skip_not_found=True,
                start_date=chunk_start,
                end_date=chunk_end,
            ):
                for item in page.items:
                    record: dict[str, Any] = item.model_dump()
                    # Hoist primary key and bookmark from nested purchase object
                    purchase = record.get("purchase") or {}
                    record["transaction"] = purchase.get("transaction")
                    record["approved_date"] = purchase.get("approved_date")
                    if not self._has_primary_key(record):
                        self.logger.warning("Record missing primary key, skipping: %s", record)
                        continue
                    yield record

                self._write_state_message()


# ---------------------------------------------------------------------------
# SubscriptionStream
# ---------------------------------------------------------------------------


class SubscriptionStream(HotmartStream):
    name = "subscriptions"
    primary_keys: ClassVar[list[str]] = ["subscriber_code"]
    replication_method = "INCREMENTAL"
    replication_key = "accession_date"
    schema = StreamSchema(_schema_source)

    def get_records(self, context: Mapping[str, Any] | None) -> Iterable[dict]:
        start_ms = self._start_date_ms(context)

        for page in HotmartClient._paginate(
            self.hotmart_client.subscriptions.list,
            skip_not_found=True,
            accession_date=start_ms,
        ):
            for item in page.items:
                record: dict[str, Any] = item.model_dump()
                if not self._has_primary_key(record):
                    self.logger.warning("Record missing primary key, skipping: %s", record)
                    continue
                yield record

            self._write_state_message()


# ---------------------------------------------------------------------------
# CommissionStream
# ---------------------------------------------------------------------------


class CommissionStream(HotmartStream):
    name = "commissions"
    primary_keys: ClassVar[list[str]] = ["transaction"]
    replication_method = "FULL_TABLE"
    schema = StreamSchema(_schema_source)

    def get_records(self, context: Mapping[str, Any] | None) -> Iterable[dict]:
        # Commissions endpoint returns no date field — use config start_date as base for chunking.
        start_ms = self._iso_to_ms(str(self.config["start_date"]))

        for chunk_start, chunk_end in self._date_chunks(start_ms):
            for page in HotmartClient._paginate(
                self.hotmart_client.sales.commissions,
                skip_not_found=True,
                start_date=chunk_start,
                end_date=chunk_end,
            ):
                for item in page.items:
                    record: dict[str, Any] = item.model_dump()
                    if not self._has_primary_key(record):
                        self.logger.warning("Record missing primary key, skipping: %s", record)
                        continue
                    yield record

                self._write_state_message()


# ---------------------------------------------------------------------------
# ProductStream
# ---------------------------------------------------------------------------


class ProductStream(HotmartStream):
    name = "products"
    primary_keys: ClassVar[list[str]] = ["product_id"]
    replication_method = "FULL_TABLE"
    schema = StreamSchema(_schema_source)

    def get_records(self, context: Mapping[str, Any] | None) -> Iterable[dict]:
        for page in HotmartClient._paginate(
            self.hotmart_client.products.list,
            skip_not_found=True,
        ):
            for item in page.items:
                raw: dict[str, Any] = item.model_dump()
                product_id = raw.get("id")
                if not product_id:
                    self.logger.warning("Record missing product id, skipping: %s", raw)
                    continue
                # ProductItem is flat; reshape to match schema and set top-level primary key
                record: dict[str, Any] = {
                    "product_id": product_id,
                    "product": {
                        "id": product_id,
                        "name": raw.get("name"),
                        "ucode": raw.get("ucode"),
                    },
                    "status": raw.get("status"),
                    "format": raw.get("format"),
                    "price": None,
                }
                yield record

            self._write_state_message()
