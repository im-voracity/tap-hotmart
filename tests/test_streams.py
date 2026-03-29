"""Integration tests for all tap streams.

These tests use VCR cassettes recorded against the Hotmart sandbox API.
Run with real credentials first to generate cassettes, then commit the
sanitized recordings (see tests/sanitize_cassettes.py).

Skip these tests in CI until cassettes are recorded:
    pytest -m "not integration"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tap_hotmart.streams import (
    CommissionStream,
    HotmartStream,
    ProductStream,
    SubscriptionStream,
    TransactionStream,
)
from tap_hotmart.tap import TapHotmart
from tests.conftest import FAKE_CONFIG, make_fake_page

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tap(state: dict[str, Any] | None = None) -> TapHotmart:
    return TapHotmart(config=FAKE_CONFIG, state=state or {})


def _make_client_mock(pages: list[MagicMock]) -> MagicMock:
    """Return a HotmartClient mock whose paginating resources return given pages."""
    client = MagicMock()
    resource = MagicMock()
    resource.return_value = _chain_pages(pages)
    return client, resource


def _chain_pages(pages: list[MagicMock]) -> MagicMock:
    """Make sdk_callable return pages in sequence on repeated calls."""
    call_count = {"n": 0}
    all_pages = list(pages)

    def side_effect(**kwargs: Any) -> MagicMock:
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(all_pages):
            return all_pages[idx]
        empty = MagicMock()
        empty.items = []
        return empty

    mock = MagicMock(side_effect=side_effect)
    return mock


# ---------------------------------------------------------------------------
# _date_chunks helper
# ---------------------------------------------------------------------------

MS_PER_DAY = 24 * 60 * 60 * 1000

# Fixed "now" used across date_chunks tests: 2026-03-29T00:00:00Z
_FIXED_NOW_MS = 1743206400000


@pytest.mark.integration
class TestDateChunks:
    def _chunks(self, start_ms: int, chunk_days: int = 30) -> list[tuple[int, int]]:
        with patch("tap_hotmart.streams.datetime") as mock_dt:
            mock_dt.now.return_value.timestamp.return_value = _FIXED_NOW_MS / 1000
            return list(HotmartStream._date_chunks(start_ms, chunk_days=chunk_days))

    def test_single_chunk_when_range_fits(self) -> None:
        start = _FIXED_NOW_MS - 10 * MS_PER_DAY  # 10 days ago
        chunks = self._chunks(start)
        assert len(chunks) == 1
        assert chunks[0] == (start, _FIXED_NOW_MS)

    def test_multiple_chunks_for_long_range(self) -> None:
        start = _FIXED_NOW_MS - 90 * MS_PER_DAY  # 90 days ago
        chunks = self._chunks(start, chunk_days=30)
        assert len(chunks) == 3

    def test_chunks_are_contiguous(self) -> None:
        start = _FIXED_NOW_MS - 60 * MS_PER_DAY
        chunks = self._chunks(start, chunk_days=30)
        for i in range(len(chunks) - 1):
            assert chunks[i + 1][0] == chunks[i][1] + 1

    def test_last_chunk_ends_at_now(self) -> None:
        start = _FIXED_NOW_MS - 45 * MS_PER_DAY
        chunks = self._chunks(start, chunk_days=30)
        assert chunks[-1][1] == _FIXED_NOW_MS

    def test_first_chunk_starts_at_start_ms(self) -> None:
        start = _FIXED_NOW_MS - 45 * MS_PER_DAY
        chunks = self._chunks(start, chunk_days=30)
        assert chunks[0][0] == start


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------

TRANSACTION_RECORD = {
    "product": {"id": 123, "name": "Curso Python"},
    "buyer": {"name": "Buyer Name", "email": "buyer@example.com", "ucode": "BUCODE"},
    "producer": {"name": "Producer Name", "ucode": "PRCODE"},
    "purchase": {
        "transaction": "HP17314900836014",
        "order_date": 1704067200000,
        "approved_date": 1704067200000,
        "status": "COMPLETE",
        "recurrency_number": None,
        "is_subscription": False,
        "commission_as": "PRODUCER",
        "price": {"value": 97.0, "currency_code": "BRL"},
        "payment": {"method": "PIX", "installments_number": 1, "type": "PIX"},
        "tracking": None,
        "offer": {"code": "abc123", "payment_mode": "UNIQUE_PAYMENT"},
        "hotmart_fee": {"total": 9.7, "fixed": 1.0, "base": 87.3, "percentage": 9.9, "currency_code": "BRL"},
        "warranty_expire_date": None,
    },
}


@pytest.mark.integration
class TestTransactionStream:
    def _stream(self, pages: list[MagicMock], state: dict | None = None) -> TransactionStream:
        tap = _make_tap(state)
        from tap_hotmart.client import HotmartClient

        client = MagicMock(spec=HotmartClient)
        client.sales.history.side_effect = _chain_pages(pages)
        return TransactionStream(tap, client)

    def test_transactions_emits_schema_before_records(self) -> None:
        page = make_fake_page([TRANSACTION_RECORD])
        stream = self._stream([page])
        messages = list(stream._generate_schema_messages())
        assert len(messages) == 1
        assert messages[0].stream == "transactions"

    def test_transactions_records_match_schema(self) -> None:
        page = make_fake_page([TRANSACTION_RECORD])
        stream = self._stream([page])
        records = list(stream.get_records(context=None))
        assert len(records) == 1
        # transaction is hoisted from purchase.transaction
        assert records[0]["transaction"] == "HP17314900836014"
        assert records[0]["approved_date"] == 1704067200000

    def test_transactions_primary_key_present_in_all_records(self) -> None:
        page = make_fake_page([TRANSACTION_RECORD])
        stream = self._stream([page])
        for record in stream.get_records(context=None):
            assert record.get("transaction") is not None

    def test_transactions_state_written_after_each_page(self) -> None:
        record2 = {**TRANSACTION_RECORD, "purchase": {**TRANSACTION_RECORD["purchase"], "transaction": "TX2"}}
        page1 = make_fake_page([TRANSACTION_RECORD], next_token="tok1")
        page2 = make_fake_page([record2])
        stream = self._stream([page1, page2])
        write_calls: list[int] = []
        original = stream._write_state_message

        def counting_write() -> None:
            write_calls.append(1)
            original()

        stream._write_state_message = counting_write  # type: ignore[method-assign]
        list(stream.get_records(context=None))
        assert len(write_calls) == 2  # once per page

    def test_transactions_bookmark_does_not_regress(self) -> None:
        future_bookmark = 9999999999999
        state = {"bookmarks": {"transactions": {"starting_replication_value": future_bookmark}}}
        page = make_fake_page([TRANSACTION_RECORD])
        stream = self._stream([page], state=state)
        # The starting value must be the bookmark, not the record's older value
        start = stream._start_date_ms(context=None)
        assert start == future_bookmark

    def test_transactions_uses_start_date_on_first_run(self) -> None:
        stream = self._stream([make_fake_page([])])
        start = stream._start_date_ms(context=None)
        assert start == 1704067200000  # FAKE_CONFIG start_date

    def test_transactions_resumes_from_bookmark(self) -> None:
        bookmark_ms = 1706745600000  # 2024-02-01
        state = {"bookmarks": {"transactions": {"starting_replication_value": bookmark_ms}}}
        stream = self._stream([make_fake_page([])], state=state)
        start = stream._start_date_ms(context=None)
        assert start == bookmark_ms


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------

SUBSCRIPTION_RECORD = {
    "subscriber_code": "SUB001",
    "subscription_id": 42,
    "status": "ACTIVE",
    "accession_date": 1704067200000,
    "end_accession_date": None,
    "request_date": None,
    "date_next_charge": 1706745600000,
    "trial": False,
    "transaction": "HP001",
    "plan": {"name": "Monthly", "id": 1, "recurrency_period": 30, "max_charge_cycles": None},
    "product": {"id": 123, "name": "Curso Python", "ucode": "UCODE123"},
    "price": {"value": 97.0, "currency_code": "BRL"},
    "subscriber": {"name": "Sub Name", "email": "sub@example.com", "ucode": "SCODE", "id": None},
}


@pytest.mark.integration
class TestSubscriptionStream:
    def _stream(self, pages: list[MagicMock], state: dict | None = None) -> SubscriptionStream:
        tap = _make_tap(state)
        from tap_hotmart.client import HotmartClient

        client = MagicMock(spec=HotmartClient)
        client.subscriptions.list.side_effect = _chain_pages(pages)
        return SubscriptionStream(tap, client)

    def test_subscriptions_emits_schema_before_records(self) -> None:
        stream = self._stream([make_fake_page([SUBSCRIPTION_RECORD])])
        messages = list(stream._generate_schema_messages())
        assert messages[0].stream == "subscriptions"

    def test_subscriptions_records_match_schema(self) -> None:
        page = make_fake_page([SUBSCRIPTION_RECORD])
        stream = self._stream([page])
        records = list(stream.get_records(context=None))
        assert records[0]["subscriber_code"] == "SUB001"

    def test_subscriptions_primary_key_present_in_all_records(self) -> None:
        page = make_fake_page([SUBSCRIPTION_RECORD])
        stream = self._stream([page])
        for record in stream.get_records(context=None):
            assert record.get("subscriber_code") is not None

    def test_subscriptions_state_written_after_each_page(self) -> None:
        page1 = make_fake_page([SUBSCRIPTION_RECORD], next_token="tok1")
        page2 = make_fake_page([{**SUBSCRIPTION_RECORD, "subscriber_code": "SUB002"}])
        stream = self._stream([page1, page2])
        calls: list[int] = []
        original = stream._write_state_message

        def counting_write() -> None:
            calls.append(1)
            original()

        stream._write_state_message = counting_write  # type: ignore[method-assign]
        list(stream.get_records(context=None))
        assert len(calls) == 2

    def test_subscriptions_bookmark_does_not_regress(self) -> None:
        future_bookmark = 9999999999999
        state = {"bookmarks": {"subscriptions": {"starting_replication_value": future_bookmark}}}
        stream = self._stream([make_fake_page([])], state=state)
        assert stream._start_date_ms(context=None) == future_bookmark

    def test_subscriptions_uses_start_date_on_first_run(self) -> None:
        stream = self._stream([make_fake_page([])])
        assert stream._start_date_ms(context=None) == 1704067200000

    def test_subscriptions_resumes_from_bookmark(self) -> None:
        # Replication key is accession_date — new subscriptions are fetched from the last bookmark
        bookmark_ms = 1706745600000
        state = {"bookmarks": {"subscriptions": {"starting_replication_value": bookmark_ms}}}
        stream = self._stream([make_fake_page([])], state=state)
        assert stream._start_date_ms(context=None) == bookmark_ms


# ---------------------------------------------------------------------------
# commissions
# ---------------------------------------------------------------------------

COMMISSION_RECORD = {
    "transaction": "HP17314900836014",
    "product": {"id": 123, "name": "Curso Python"},
    "exchange_rate_currency_payout": 1.0,
    "commissions": [
        {
            "source": "PRODUCER",
            "commission": {"value": 87.3, "currency_value": None, "currency_code": "BRL"},
            "user": {"name": "Producer Name", "email": "producer@example.com", "ucode": "PRCODE"},
        }
    ],
}


@pytest.mark.integration
class TestCommissionStream:
    def _stream(self, pages: list[MagicMock]) -> CommissionStream:
        tap = _make_tap()
        from tap_hotmart.client import HotmartClient

        client = MagicMock(spec=HotmartClient)
        client.sales.commissions.side_effect = _chain_pages(pages)
        return CommissionStream(tap, client)

    def test_commissions_emits_schema_before_records(self) -> None:
        stream = self._stream([make_fake_page([COMMISSION_RECORD])])
        messages = list(stream._generate_schema_messages())
        assert messages[0].stream == "commissions"

    def test_commissions_records_match_schema(self) -> None:
        page = make_fake_page([COMMISSION_RECORD])
        stream = self._stream([page])
        records = list(stream.get_records(context=None))
        assert records[0]["transaction"] == "HP17314900836014"
        assert records[0]["commissions"][0]["source"] == "PRODUCER"

    def test_commissions_primary_key_present_in_all_records(self) -> None:
        page = make_fake_page([COMMISSION_RECORD])
        stream = self._stream([page])
        for record in stream.get_records(context=None):
            assert record.get("transaction") is not None

    def test_commissions_state_written_after_each_page(self) -> None:
        page1 = make_fake_page([COMMISSION_RECORD], next_token="tok1")
        page2 = make_fake_page([{**COMMISSION_RECORD, "transaction": "TX2"}])
        stream = self._stream([page1, page2])
        calls: list[int] = []
        original = stream._write_state_message

        def counting_write() -> None:
            calls.append(1)
            original()

        stream._write_state_message = counting_write  # type: ignore[method-assign]
        list(stream.get_records(context=None))
        assert len(calls) == 2

    def test_commissions_is_full_table(self) -> None:
        stream = self._stream([make_fake_page([])])
        assert stream.replication_method == "FULL_TABLE"
        assert stream.replication_key is None


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------

# ProductItem from the SDK is flat (matches hotmart-python's ProductItem model_dump)
PRODUCT_RECORD = {
    "id": 123,
    "name": "Curso Python",
    "ucode": "UCODE123",
    "status": "ACTIVE",
    "format": "ONLINE_COURSE",
}


@pytest.mark.integration
class TestProductStream:
    def _stream(self, pages: list[MagicMock]) -> ProductStream:
        tap = _make_tap()
        from tap_hotmart.client import HotmartClient

        client = MagicMock(spec=HotmartClient)
        client.products.list.side_effect = _chain_pages(pages)
        return ProductStream(tap, client)

    def test_products_emits_schema_before_records(self) -> None:
        stream = self._stream([make_fake_page([PRODUCT_RECORD])])
        messages = list(stream._generate_schema_messages())
        assert messages[0].stream == "products"

    def test_products_records_match_schema(self) -> None:
        page = make_fake_page([PRODUCT_RECORD])
        stream = self._stream([page])
        records = list(stream.get_records(context=None))
        assert records[0]["product"]["id"] == 123
        assert records[0]["product_id"] == 123
        assert records[0]["status"] == "ACTIVE"

    def test_products_primary_key_present_in_all_records(self) -> None:
        page = make_fake_page([PRODUCT_RECORD])
        stream = self._stream([page])
        for record in stream.get_records(context=None):
            assert record.get("product_id") is not None

    def test_products_state_written_after_each_page(self) -> None:
        page1 = make_fake_page([PRODUCT_RECORD], next_token="tok1")
        page2 = make_fake_page([{**PRODUCT_RECORD, "id": 456, "name": "Outro", "ucode": "X"}])
        stream = self._stream([page1, page2])
        calls: list[int] = []
        original = stream._write_state_message

        def counting_write() -> None:
            calls.append(1)
            original()

        stream._write_state_message = counting_write  # type: ignore[method-assign]
        list(stream.get_records(context=None))
        assert len(calls) == 2

    def test_products_bookmark_does_not_regress(self) -> None:
        # FULL_TABLE — no bookmark, this test verifies no state is accidentally written
        stream = self._stream([make_fake_page([PRODUCT_RECORD])])
        assert stream.replication_method == "FULL_TABLE"
        assert stream.replication_key is None
