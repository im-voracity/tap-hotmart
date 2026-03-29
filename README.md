# tap-hotmart

[![PyPI version](https://img.shields.io/pypi/v/tap-hotmart.svg)](https://pypi.org/project/tap-hotmart/)
[![Python](https://img.shields.io/pypi/pyversions/tap-hotmart.svg)](https://pypi.org/project/tap-hotmart/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Singer SDK](https://img.shields.io/badge/built%20with-Singer%20SDK-blue)](https://sdk.meltano.com)

A [Singer](https://www.singer.io/) tap for the [Hotmart](https://hotmart.com) API, built with the [Meltano Singer SDK](https://sdk.meltano.com).

Extracts sales, subscriptions, commissions, and product data from Hotmart and delivers it as a standard Singer stream — ready to load into any data warehouse (Postgres, BigQuery, Snowflake, etc.) or consumed by any Singer-compatible target.

## Relationship with hotmart-python

This tap is built on top of [**hotmart-python**](https://github.com/im-voracity/hotmart-python), a Python SDK for the Hotmart API maintained by the same author. Both projects are developed in tandem:

- `hotmart-python` handles authentication, pagination, retry, rate limiting, and API model definitions
- `tap-hotmart` handles Singer protocol compliance: schema emission, incremental state, and record extraction

Whenever `hotmart-python` adds support for a new Hotmart API endpoint or model, a corresponding stream is added here. The two projects share the same release cadence.

## Streams

| Stream | Replication | Primary Key | Description |
|---|---|---|---|
| `transactions` | INCREMENTAL (`approved_date`) | `transaction` | Full sales history with buyer, product, payment, and fee details |
| `subscriptions` | INCREMENTAL (`accession_date`) | `subscriber_code` | Subscription records with plan, status, and next charge date |
| `commissions` | FULL_TABLE | `transaction` | Per-sale commission breakdown by role (producer, co-producer, affiliate) |
| `products` | FULL_TABLE | `product_id` | Products registered in the account |

**Notes:**
- `transactions` and `subscriptions` are **incremental**: on each run, only records newer than the last bookmark are fetched.
- `commissions` is **full table** because the Hotmart API does not expose a date field in commission responses, making reliable incremental extraction impossible. It is re-fetched in full on every run.
- All incremental streams use **automatic date chunking** (30-day windows) to stay within Hotmart's per-request date range limits, so any `start_date` works without manual configuration.

## Requirements

- Python 3.11+
- A Hotmart account with API access enabled
- API credentials from the [Hotmart Developer Portal](https://developers.hotmart.com)

## Installation

```bash
pip install tap-hotmart
```

## Configuration

Create a `config.json` file:

```json
{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "basic": "Basic <your-base64-token>",
  "start_date": "2021-01-01T00:00:00Z",
  "sandbox": false
}
```

| Setting | Required | Default | Description |
|---|---|---|---|
| `client_id` | ✅ | — | Hotmart API Client ID |
| `client_secret` | ✅ | — | Hotmart API Client Secret |
| `basic` | ✅ | — | `Basic <base64(client_id:client_secret)>` — available directly in the Hotmart Developer Portal |
| `start_date` | ✅ | — | Earliest record date to sync (ISO 8601). Set to whenever you first started using Hotmart. |
| `sandbox` | — | `false` | Use the Hotmart sandbox environment |

> **Note:** The `basic` token is the Base64 encoding of `client_id:client_secret`. The Hotmart Developer Portal shows this value ready to copy — it starts with `Basic `.

## Usage

```bash
# Discover available streams
tap-hotmart --config config.json --discover

# Sync all streams to stdout
tap-hotmart --config config.json

# Pipe to a Singer target
tap-hotmart --config config.json | target-jsonl --config target-config.json

# Incremental run with state
tap-hotmart --config config.json --state state.json \
  | target-postgres --config target-config.json \
  | tail -1 > state.json
```

## Usage with Meltano

```bash
meltano add extractor tap-hotmart --variant im-voracity
meltano config tap-hotmart set client_id "your-client-id"
meltano config tap-hotmart set client_secret "your-client-secret"
meltano config tap-hotmart set basic "Basic <your-base64-token>"
meltano config tap-hotmart set start_date "2021-01-01T00:00:00Z"

meltano run tap-hotmart <your-target>
```

## Development

```bash
git clone https://github.com/im-voracity/tap-hotmart
cd tap-hotmart
uv sync
uv run pytest tests/
uv run ruff check .
uv run mypy tap_hotmart/
```

To run tests against the live API, add a `config.json` with real credentials at the repo root. The test suite detects it automatically and runs the full Singer compliance suite (`test_core.py`) against the real API. Without `config.json`, all live tests are skipped and only unit/mock tests run.

## Contributing

Bug reports and pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## Author

Maintained by [Matheus Tenório](https://github.com/im-voracity). Also the author of [hotmart-python](https://github.com/im-voracity/hotmart-python), the underlying SDK this tap depends on.

## License

[Apache 2.0](LICENSE)
