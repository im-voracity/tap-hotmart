"""Singer SDK standard compliance tests.

These tests verify that the tap conforms to the Singer spec.
Requires a real config.json at the repo root with valid Hotmart credentials.
Without config.json, this file defines no tests and is silently skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from singer_sdk.testing import SuiteConfig, get_tap_test_class

from tap_hotmart.tap import TapHotmart

_config_path = Path(__file__).parent.parent / "config.json"

if _config_path.exists():
    with _config_path.open() as _f:
        _TEST_CONFIG = json.load(_f)

    TestTapHotmart = get_tap_test_class(
        TapHotmart,
        config=_TEST_CONFIG,
        suite_config=SuiteConfig(
            ignore_no_records_for_streams=["transactions", "subscriptions", "commissions"]
        ),
    )
