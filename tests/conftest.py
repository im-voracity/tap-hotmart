from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

FAKE_CONFIG: dict[str, Any] = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "basic": "Basic dGVzdA==",
    "start_date": "2024-01-01T00:00:00Z",
    "sandbox": True,
}


@pytest.fixture
def tap_config() -> dict[str, Any]:
    return dict(FAKE_CONFIG)


def make_fake_page(items: list[dict], next_token: str | None = None) -> MagicMock:
    """Build a fake PaginatedResponse with the minimum duck-type surface the tap uses."""
    page = MagicMock()
    page.items = [_dict_to_mock(item) for item in items]
    if next_token:
        page.page_info = MagicMock()
        page.page_info.next_page_token = next_token
    else:
        page.page_info = MagicMock()
        page.page_info.next_page_token = None
    return page


def _dict_to_mock(data: dict) -> MagicMock:
    """Recursively build a MagicMock that also exposes .model_dump() -> data."""
    mock = MagicMock()
    mock.model_dump.return_value = data
    return mock
