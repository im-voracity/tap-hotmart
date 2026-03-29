from __future__ import annotations

from typing import Any, ClassVar

from singer_sdk import Stream, Tap

from tap_hotmart.client import HotmartClient
from tap_hotmart.streams import (
    CommissionStream,
    ProductStream,
    SubscriptionStream,
    TransactionStream,
)


class TapHotmart(Tap):
    """Singer tap for the Hotmart API."""

    name = "tap-hotmart"

    config_jsonschema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Hotmart OAuth client ID.",
            },
            "client_secret": {
                "type": "string",
                "description": "Hotmart OAuth client secret.",
                "secret": True,
            },
            "basic": {
                "type": "string",
                "description": "Basic token for OAuth authentication.",
                "secret": True,
            },
            "start_date": {
                "type": "string",
                "format": "date-time",
                "description": "Earliest date for incremental extraction (ISO 8601).",
            },
            "sandbox": {
                "type": "boolean",
                "default": False,
                "description": "Use Hotmart sandbox environment.",
            },
            "user_agent": {
                "type": "string",
                "default": "tap-hotmart/1.0",
                "description": "User-agent string sent with requests.",
            },
        },
        "required": ["client_id", "client_secret", "basic", "start_date"],
    }

    def discover_streams(self) -> list[Stream]:
        """Return all tap streams, sharing a single SDK client instance."""
        client = HotmartClient(self.config)
        return [
            TransactionStream(self, client),
            SubscriptionStream(self, client),
            CommissionStream(self, client),
            ProductStream(self, client),
        ]


if __name__ == "__main__":
    TapHotmart.cli()
