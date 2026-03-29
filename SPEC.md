# tap-hotmart — Technical Specification
**Version 1.1 — March 2026**

> This document is the contract for the tap. It defines streams, schemas, incremental behavior, configuration, and error contracts. All code and tests are derived from this spec — not the other way around.

---

## 1. Overview

`tap-hotmart` is a Singer tap built with the Meltano Singer SDK. It extracts data from the Hotmart v1 API and emits a Singer message stream (`SCHEMA → RECORD* → STATE`) to stdout.

The tap uses the `hotmart-python` SDK as its HTTP client — it does not make HTTP calls directly.

**Repository:** `tap-hotmart`
**SDK:** [Meltano Singer SDK](https://sdk.meltano.com)
**Primary dependency:** `hotmart-python`
**Python:** ≥ 3.11

---

## 2. Configuration

### 2.1 Required parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `client_id` | string | Hotmart OAuth client ID |
| `client_secret` | string | Hotmart OAuth client secret |
| `basic` | string | Basic token for OAuth authentication |
| `start_date` | string (ISO 8601) | Incremental extraction start date. e.g. `2024-01-01T00:00:00Z` |

### 2.2 Optional parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sandbox` | boolean | `false` | Use Hotmart sandbox environment |
| `user_agent` | string | `tap-hotmart/1.0` | User-agent sent with requests |

### 2.3 Example config.json

```json
{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "basic": "your-basic-token",
  "start_date": "2024-01-01T00:00:00Z",
  "sandbox": false
}
```

### 2.4 Configuration guard clauses

The tap must fail immediately (before any API call) if:
- `client_id` is missing or empty → `ConfigurationError`
- `client_secret` is missing or empty → `ConfigurationError`
- `basic` is missing or empty → `ConfigurationError`
- `start_date` is missing → `ConfigurationError`
- `start_date` is not a valid ISO 8601 string → `ConfigurationError`

---

## 3. Streams

### 3.1 Overview

| Stream | SDK method | Primary key | Bookmark field | Replication |
|--------|-----------|-------------|----------------|-------------|
| `transactions` | `sales.history()` | `transaction` | `purchase.approved_date` | INCREMENTAL |
| `subscriptions` | `subscriptions.list()` | `subscriber_code` | `date_next_charge` | INCREMENTAL |
| `commissions` | `sales.commissions()` | `transaction` | `purchase.approved_date` | INCREMENTAL |
| `products` | `products.list()` | `product.id` | — | FULL_TABLE |

> **Note on `products`:** The Hotmart API does not expose an updated-at field for products. This stream uses FULL_TABLE — all products are synced on every run. It is the only stream without incremental replication.

---

### 3.2 Stream: `transactions`

**Description:** Sales history including purchases, refunds, and chargebacks.

**SDK method:** `client.sales.history(start_date=<ms>, page_token=<token>)`

**Pagination:** cursor-based via `page_info.next_page_token` in the response.

**Bookmark field:** `purchase.approved_date` (millisecond timestamp)

**Incremental behavior:**
- First run: uses `start_date` from config (converted to ms)
- Subsequent runs: uses bookmark value from STATE
- Bookmark is updated at the end of each successfully processed page with the highest `approved_date` seen
- Records are filtered server-side via the `start_date` API parameter

**Schema (required minimum fields):**

```json
{
  "type": "object",
  "properties": {
    "transaction": { "type": "string" },
    "product": {
      "type": "object",
      "properties": {
        "id": { "type": ["integer", "null"] },
        "name": { "type": ["string", "null"] },
        "ucode": { "type": ["string", "null"] }
      }
    },
    "purchase": {
      "type": "object",
      "properties": {
        "approved_date": { "type": ["integer", "null"] },
        "date_next_charge": { "type": ["integer", "null"] },
        "full_price": {
          "type": ["object", "null"],
          "properties": {
            "value": { "type": ["number", "null"] },
            "currency_value": { "type": ["string", "null"] }
          }
        },
        "original_offer_price": {
          "type": ["object", "null"],
          "properties": {
            "value": { "type": ["number", "null"] },
            "currency_value": { "type": ["string", "null"] }
          }
        },
        "status": { "type": ["string", "null"] },
        "payment": {
          "type": ["object", "null"],
          "properties": {
            "method": { "type": ["string", "null"] },
            "installments_number": { "type": ["integer", "null"] },
            "type": { "type": ["string", "null"] }
          }
        }
      }
    },
    "buyer": {
      "type": ["object", "null"],
      "properties": {
        "email": { "type": ["string", "null"] },
        "name": { "type": ["string", "null"] },
        "ucode": { "type": ["string", "null"] }
      }
    },
    "producer": {
      "type": ["object", "null"],
      "properties": {
        "name": { "type": ["string", "null"] },
        "ucode": { "type": ["string", "null"] }
      }
    },
    "commissions": {
      "type": ["array", "null"],
      "items": {
        "type": "object",
        "properties": {
          "value": { "type": ["number", "null"] },
          "currency_value": { "type": ["string", "null"] },
          "source": { "type": ["string", "null"] }
        }
      }
    },
    "tracking": {
      "type": ["object", "null"],
      "properties": {
        "source": { "type": ["string", "null"] },
        "source_sck": { "type": ["string", "null"] },
        "external_code": { "type": ["string", "null"] }
      }
    }
  },
  "required": ["transaction"]
}
```

**Possible values for `purchase.status`:** `APPROVED`, `BLOCKED`, `CANCELLED`, `CHARGEBACK`, `COMPLETE`, `EXPIRED`, `NO_FUNDS`, `OVERDUE`, `PARTIALLY_REFUNDED`, `PRE_ORDER`, `PRINTED_BILLET`, `PROCESSING_TRANSACTION`, `REFUNDED`, `STARTED`, `UNDER_ANALISYS`, `WAITING_PAYMENT`

---

### 3.3 Stream: `subscriptions`

**Description:** Active and inactive subscriptions for recurring products.

**SDK method:** `client.subscriptions.list(page_token=<token>)`

**Pagination:** cursor-based via `page_info.next_page_token`.

**Bookmark field:** `date_next_charge` (millisecond timestamp)

**Incremental behavior:**
- Filters server-side by `accession_date` via `start_date` parameter
- Bookmark records the highest `date_next_charge` seen in the run

**Schema (required minimum fields):**

```json
{
  "type": "object",
  "properties": {
    "subscriber_code": { "type": "string" },
    "subscription_id": { "type": ["integer", "null"] },
    "status": { "type": ["string", "null"] },
    "accession_date": { "type": ["integer", "null"] },
    "end_accession_date": { "type": ["integer", "null"] },
    "date_next_charge": { "type": ["integer", "null"] },
    "trial": { "type": ["boolean", "null"] },
    "plan": {
      "type": ["object", "null"],
      "properties": {
        "name": { "type": ["string", "null"] },
        "id": { "type": ["integer", "null"] }
      }
    },
    "product": {
      "type": ["object", "null"],
      "properties": {
        "id": { "type": ["integer", "null"] },
        "name": { "type": ["string", "null"] },
        "ucode": { "type": ["string", "null"] }
      }
    },
    "subscriber": {
      "type": ["object", "null"],
      "properties": {
        "email": { "type": ["string", "null"] },
        "name": { "type": ["string", "null"] },
        "ucode": { "type": ["string", "null"] }
      }
    },
    "transaction": { "type": ["string", "null"] }
  },
  "required": ["subscriber_code"]
}
```

**Possible values for `status`:** `ACTIVE`, `INACTIVE`, `DELAYED`, `CANCELLED_BY_CUSTOMER`, `CANCELLED_BY_SELLER`, `CANCELLED_BY_ADMIN`, `STARTED`, `OVERDUE`

---

### 3.4 Stream: `commissions`

**Description:** Commissions paid to affiliates and co-producers per transaction.

**SDK method:** `client.sales.commissions(start_date=<ms>, page_token=<token>)`

**Pagination:** cursor-based via `page_info.next_page_token`.

**Bookmark field:** `purchase.approved_date` (millisecond timestamp)

**Incremental behavior:** identical to the `transactions` stream.

**Schema (required minimum fields):**

```json
{
  "type": "object",
  "properties": {
    "transaction": { "type": "string" },
    "product": {
      "type": ["object", "null"],
      "properties": {
        "id": { "type": ["integer", "null"] },
        "name": { "type": ["string", "null"] },
        "ucode": { "type": ["string", "null"] }
      }
    },
    "purchase": {
      "type": ["object", "null"],
      "properties": {
        "approved_date": { "type": ["integer", "null"] },
        "status": { "type": ["string", "null"] },
        "full_price": {
          "type": ["object", "null"],
          "properties": {
            "value": { "type": ["number", "null"] },
            "currency_value": { "type": ["string", "null"] }
          }
        }
      }
    },
    "users": {
      "type": ["array", "null"],
      "items": {
        "type": "object",
        "properties": {
          "role": { "type": ["string", "null"] },
          "commission": {
            "type": ["object", "null"],
            "properties": {
              "value": { "type": ["number", "null"] },
              "currency_value": { "type": ["string", "null"] }
            }
          },
          "user": {
            "type": ["object", "null"],
            "properties": {
              "name": { "type": ["string", "null"] },
              "ucode": { "type": ["string", "null"] }
            }
          }
        }
      }
    }
  },
  "required": ["transaction"]
}
```

---

### 3.5 Stream: `products`

**Description:** Producer's product catalog.

**SDK method:** `client.products.list(page_token=<token>)`

**Pagination:** cursor-based via `page_info.next_page_token`.

**Replication:** FULL_TABLE — no incremental, no bookmark.

**Schema (required minimum fields):**

```json
{
  "type": "object",
  "properties": {
    "product": {
      "type": "object",
      "properties": {
        "id": { "type": "integer" },
        "name": { "type": ["string", "null"] },
        "ucode": { "type": ["string", "null"] }
      },
      "required": ["id"]
    },
    "status": { "type": ["string", "null"] },
    "format": { "type": ["string", "null"] },
    "price": {
      "type": ["object", "null"],
      "properties": {
        "value": { "type": ["number", "null"] },
        "currency_value": { "type": ["string", "null"] }
      }
    }
  },
  "required": ["product"]
}
```

---

## 4. State management (bookmarks)

### 4.1 STATE format

```json
{
  "bookmarks": {
    "transactions": {
      "approved_date": 1704067200000
    },
    "subscriptions": {
      "date_next_charge": 1704067200000
    },
    "commissions": {
      "approved_date": 1704067200000
    }
  }
}
```

### 4.2 Update rules

- The bookmark is written **at the end of each successfully processed page**, not at the end of the full run
- If the run fails mid-stream, the STATE written so far is preserved — the next run resumes from the last completed page
- The bookmark never regresses — if the current STATE value is higher than the records on the current page, the bookmark is not updated
- `products` does not write a bookmark (FULL_TABLE)

### 4.3 Date conversion

The Hotmart API uses **millisecond timestamps** since UTC epoch. The tap converts internally:
- `start_date` from config (ISO 8601) → ms for API parameters
- Millisecond timestamps in records → kept as integers in the schema (conversion to datetime is the responsibility of the target or dbt)

---

## 5. Pagination

**All streams with pagination use the SDK base method** (e.g. `sales.history(page_token=...)`), not `_autopaginate`. This is required to allow STATE emission at the end of each page — `_autopaginate` yields item-by-item and does not expose the boundary between pages.

Standard loop for all streams:

```python
def get_records(self, context):
    page_token = None  # or bookmark from previous STATE
    while True:
        page = self.client.<resource>.<method>(
            start_date=self._start_date_ms,
            page_token=page_token,
        )
        for item in page.items:
            yield item.model_dump()
        # STATE can be emitted here, after each page's yield
        if not page.page_info or not page.page_info.next_page_token:
            break
        page_token = page.page_info.next_page_token
```

**SDK fields:**
- Next page: `page.page_info.next_page_token` (None when there are no more pages)
- Page items: `page.items` (list of Pydantic objects)

**Guard clause:** if `page_token` is an empty string, treat it as `None` (do not send the parameter).

---

## 6. Error handling

> **Architectural note:** the `hotmart-python` SDK manages retry, backoff, rate limiting, and token renewal internally. The tap **does not reimplement any of these mechanisms** — it lets the SDK handle them.

### 6.1 What the SDK already does — the tap must not reimplement

**Retry and backoff (automatic):**
- Retryable: 429, 500, 502, 503, `httpx.TransportError`
- Not retryable: 400, 401, 403, 404
- Strategy: `0.5s × 2^attempt + jitter` (jitter 0–0.5s), capped at 30s
- For 429: uses the `RateLimit-Reset` header directly when present; falls back to exponential if absent
- Max retries: configurable via `ClientConfig.max_retries` (default: 3)

**Proactive rate limiting (automatic):**
- The SDK parses `RateLimit-Remaining` and calls `time.sleep()` before each request when needed

**Authentication (automatic):**
- Proactive renewal: 5 minutes before expiry
- On 401: invalidates the cache, renews the token, and retries the request automatically
- Thread-safe via `threading.Lock()` with double-checked locking

**Typed exceptions:**
- `AuthenticationError` → 401, 403
- `BadRequestError` → 400
- `NotFoundError` → 404
- `RateLimitError` → 429 (after exhausting retries)
- `InternalServerError` → 500, 502, 503
- `APIStatusError` → other status codes

### 6.2 What the tap is responsible for

**Missing / null fields:**
- Fields absent in the API response must be emitted as `null` in the record — never omitted
- The tap must not fail on a missing field that is marked as nullable in the schema

**Records without primary key:**
- Guard clause: if the primary field (`transaction`, `subscriber_code`, `product.id`) is absent in the record, the record is discarded with `logger.warning` — never raises an exception

**Non-retryable errors propagated by the SDK:**
- `NotFoundError` (404) in a stream → log warning and continue (resource may have been deleted)
- `AuthenticationError` → re-raise — invalid credentials require human intervention
- `BadRequestError` → re-raise with a clear message including the parameters used

---

## 7. Discovery mode

The tap must support the `--discover` flag, returning a catalog with all 4 streams and their complete schemas. Each stream in the catalog must include:

```json
{
  "stream": "transactions",
  "tap_stream_id": "transactions",
  "schema": { "..." },
  "metadata": [
    {
      "breadcrumb": [],
      "metadata": {
        "selected": true,
        "replication-method": "INCREMENTAL",
        "replication-key": "purchase.approved_date",
        "valid-replication-keys": ["purchase.approved_date"]
      }
    }
  ],
  "key_properties": ["transaction"]
}
```

---

## 8. Repository structure

```
tap-hotmart/
├── tap_hotmart/
│   ├── __init__.py
│   ├── tap.py              # Singer SDK entrypoint
│   ├── client.py           # hotmart-python SDK wrapper
│   ├── streams.py          # Stream definitions
│   └── schemas/            # JSON Schemas — source of truth
│       ├── transactions.json
│       ├── subscriptions.json
│       ├── commissions.json
│       └── products.json
├── tests/
│   ├── conftest.py         # Shared fixtures
│   ├── cassettes/          # VCR HTTP recordings
│   ├── test_client.py      # Unit tests
│   ├── test_streams.py     # Integration tests
│   └── test_core.py        # Singer SDK standard tests (do not modify)
├── SPEC.md                 # This document
├── CLAUDE.md               # Agent instructions
├── CHANGELOG.md            # Generated by cookiecutter — keep updated
├── CONTRIBUTING.md         # Generated by cookiecutter — keep updated
├── pyproject.toml
└── README.md
```

---

## 9. Code conventions

### 9.1 Early returns and guard clauses

Every validation and parsing function uses early return — no `else` after `return` or `raise`:

```python
# Correct
def parse_timestamp(value: int | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return int(value)
```

### 9.2 Naming

- Streams: snake_case, plural (`transactions`, `subscriptions`)
- Stream classes: PascalCase, singular + "Stream" (`TransactionStream`)
- Extraction methods: `get_records()` for all streams
- Constants: UPPER_SNAKE_CASE (`BOOKMARK_KEY`, `MAX_RETRIES`)

### 9.3 Type hints

Required on all public functions. Use `from __future__ import annotations` for forward references.

---

## 10. Test plan

### 10.1 Test pyramid

| Layer | File | Target coverage |
|-------|------|----------------|
| Unit | `test_client.py` | Config validation, pagination loop, field mapping, timestamp conversion |
| Integration | `test_streams.py` | SCHEMA/RECORD/STATE emission per stream |
| Contract | `test_core.py` | Singer spec conformance via SDK |

> **Do not test in the tap:** retry, backoff, rate limiting, token renewal — all of these are SDK responsibilities and must be tested in the SDK, not here.

### 10.2 Required test cases — `test_client.py`

**Configuration validation (guard clauses):**
- `test_config_missing_client_id` → must raise `ConfigurationError`
- `test_config_missing_client_secret` → must raise `ConfigurationError`
- `test_config_missing_basic` → must raise `ConfigurationError`
- `test_config_missing_start_date` → must raise `ConfigurationError`
- `test_config_invalid_start_date_format` → must raise `ConfigurationError`

**Pagination (tap responsibility):**
- `test_pagination_loop_stops_on_null_next_token` → loop ends when `page_info.next_page_token` is None
- `test_pagination_loop_stops_on_empty_next_token` → empty string treated as None
- `test_pagination_emits_state_after_each_page` → STATE emitted between pages, not only at the end

**Field mapping:**
- `test_null_fields_emitted_as_null` → fields absent in SDK response → `null` in Singer record
- `test_record_missing_primary_key_is_discarded` → record without primary key discarded with `logger.warning`
- `test_start_date_converted_to_milliseconds` → ISO 8601 from config → int ms passed to SDK

**SDK errors propagated to tap:**
- `test_not_found_error_is_skipped` → SDK `NotFoundError` → log warning, stream continues
- `test_authentication_error_propagates` → SDK `AuthenticationError` → re-raised without catching

### 10.3 Required test cases — `test_streams.py`

For each stream (`transactions`, `subscriptions`, `commissions`, `products`):
- `test_{stream}_emits_schema_before_records`
- `test_{stream}_records_match_schema`
- `test_{stream}_primary_key_present_in_all_records`
- `test_{stream}_state_written_after_each_page`
- `test_{stream}_bookmark_does_not_regress`

For incremental streams only:
- `test_{stream}_uses_start_date_on_first_run`
- `test_{stream}_resumes_from_bookmark`

### 10.4 VCR cassettes

- Use `pytest-recording` (vcrpy wrapper) with `@pytest.mark.vcr()`
- One cassette per endpoint, reused across tests for the same stream
- Record once with real sandbox credentials
- Sanitize before committing: run `tests/sanitize_cassettes.py` to scrub tokens and emails
- Never regenerate cassettes without a reason

---

## 11. v1 Acceptance criteria

The tap is ready for Meltano integration when:

- [ ] `tap-hotmart --config config.json --discover` returns a valid catalog with 4 streams
- [ ] `tap-hotmart --config config.json` emits `SCHEMA → RECORD* → STATE` for all streams
- [ ] Incremental run after existing STATE uses bookmark and does not return records prior to it
- [ ] Run without STATE uses `start_date` from config
- [ ] Full test suite passes (`pytest tests/`)
- [ ] SDK standard tests pass (`test_core.py`)
- [ ] No sensitive data (credentials, tokens) appears in logs even with `log_level=DEBUG`
- [ ] `ruff check .` passes with no errors
- [ ] `mypy tap_hotmart/` passes with no errors

---

*tap-hotmart SPEC v1.1*