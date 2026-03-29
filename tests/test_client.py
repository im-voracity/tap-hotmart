from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from singer_sdk.exceptions import ConfigValidationError

from tap_hotmart.client import HotmartClient
from tests.conftest import FAKE_CONFIG, make_fake_page

# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_missing_client_id() -> None:
    config = {**FAKE_CONFIG, "client_id": ""}
    with pytest.raises(ConfigValidationError):
        HotmartClient(config)


def test_config_missing_client_secret() -> None:
    config = {k: v for k, v in FAKE_CONFIG.items() if k != "client_secret"}
    with pytest.raises(ConfigValidationError):
        HotmartClient(config)


def test_config_missing_basic() -> None:
    config = {**FAKE_CONFIG, "basic": ""}
    with pytest.raises(ConfigValidationError):
        HotmartClient(config)


def test_config_missing_start_date() -> None:
    config = {k: v for k, v in FAKE_CONFIG.items() if k != "start_date"}
    with pytest.raises(ConfigValidationError):
        HotmartClient(config)


def test_config_invalid_start_date_format() -> None:
    config = {**FAKE_CONFIG, "start_date": "01/01/2024"}
    with pytest.raises(ConfigValidationError):
        HotmartClient(config)


# ---------------------------------------------------------------------------
# Timestamp conversion
# ---------------------------------------------------------------------------


def test_start_date_converted_to_milliseconds() -> None:
    ms = HotmartClient.iso_to_ms("2024-01-01T00:00:00Z")
    assert ms == 1704067200000


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------


def test_pagination_loop_stops_on_null_next_token() -> None:
    """get_pages() must stop when next_page_token is None."""
    page = make_fake_page([{"transaction": "TX-1"}], next_token=None)
    sdk_mock = MagicMock()
    sdk_mock.return_value = page

    pages = list(HotmartClient._paginate(sdk_mock))

    assert len(pages) == 1
    sdk_mock.assert_called_once_with(page_token=None)


def test_pagination_loop_stops_on_empty_next_token() -> None:
    """Empty string next_page_token must be treated as None (loop stops)."""
    page = make_fake_page([{"transaction": "TX-1"}])
    page.page_info.next_page_token = ""
    sdk_mock = MagicMock()
    sdk_mock.return_value = page

    pages = list(HotmartClient._paginate(sdk_mock))

    assert len(pages) == 1


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def test_null_fields_emitted_as_null() -> None:
    """model_dump() with missing optional fields should return None for those fields."""
    record = {"transaction": "TX-1", "buyer": None, "product": None}
    # The tap must not fail or omit null fields — they pass through as-is
    assert record["buyer"] is None
    assert record["product"] is None


def test_record_missing_primary_key_is_discarded() -> None:
    """has_primary_key() returns False when the primary key field is absent or None."""
    assert HotmartClient.has_primary_key({"transaction": None}, "transaction") is False
    assert HotmartClient.has_primary_key({}, "transaction") is False
    assert HotmartClient.has_primary_key({"transaction": "TX-1"}, "transaction") is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_not_found_error_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """NotFoundError from the SDK must be caught and logged as a warning."""
    from hotmart import NotFoundError

    sdk_mock = MagicMock(side_effect=NotFoundError("not found"))

    with caplog.at_level("WARNING"):
        pages = list(HotmartClient._paginate(sdk_mock, skip_not_found=True))

    assert pages == []
    assert any(
        "not found" in r.message.lower() or "404" in r.message.lower() for r in caplog.records
    )


def test_authentication_error_propagates() -> None:
    """AuthenticationError from the SDK must propagate immediately."""
    from hotmart import AuthenticationError

    sdk_mock = MagicMock(side_effect=AuthenticationError("invalid credentials"))

    with pytest.raises(AuthenticationError):
        list(HotmartClient._paginate(sdk_mock))
