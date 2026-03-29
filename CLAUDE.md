# tap-hotmart — Agent Instructions

## Language

- **All code, comments, docstrings, variable names, function names, class names, and commit messages must be in English**

---

## Project context

`tap-hotmart` is a Singer tap for the Hotmart API, built with the Meltano Singer SDK.

This tap is **open source** and contains only Singer data extraction infrastructure.

**Read `SPEC.md` before starting any task.** It is the contract of this project — every implementation decision must be derived from it, not invented.

---

## Initial setup (run once if the repository is empty)

```bash
# 1. Generate base structure with the Meltano Singer SDK cookiecutter
pipx run cookiecutter gh:meltano/sdk --directory="cookiecutter/tap-template"
# When prompted:
#   tap_id: tap-hotmart
#   tap_name: HotmartTap
#   stream_type: REST
#   python_version: 3.11

# 2. Enter generated directory
cd tap-hotmart

# 3. Replace the generated pyproject.toml with the one in this repo root
# (includes hotmart-python dependency and all tooling configuration)

# 4. Install dependencies
uv sync

# 5. Verify base tests run without setup errors
uv run pytest tests/
```

After the cookiecutter runs, adapt the generated files per the sections below before writing any logic.

---

## Repository structure

```
tap_hotmart/
├── __init__.py
├── tap.py          # Entrypoint — defines TapHotmart, lists streams, declares config schema
├── client.py       # Wrapper around hotmart-python SDK — does NOT make HTTP calls directly
├── streams.py      # All streams inherit from HotmartStream (custom base)
└── schemas/        # JSON Schemas as source of truth — derived from SPEC.md
    ├── transactions.json
    ├── subscriptions.json
    ├── commissions.json
    └── products.json

tests/
├── conftest.py         # Shared fixtures: fake config, fake state, fake SDK page response
├── cassettes/          # VCR recordings — recorded once, do not regenerate without reason
├── test_client.py      # Unit tests: config validation, pagination loop, field mapping
├── test_streams.py     # Integration tests: Singer message emission per stream
└── test_core.py        # SDK standard tests — do not modify
```

---

## Fixed architectural decisions

These decisions are final. Do not question or suggest alternatives without explicit context:

**1. HTTP client:** use `hotmart-python` as the full HTTP client. Do not use `RESTStream` from the Singer SDK for HTTP calls — the Hotmart SDK already handles retry, backoff, rate limiting, and token renewal. The tap does not reimplement any of these mechanisms.

**2. Pagination:** use the base method for each endpoint (e.g. `client.sales.history(page_token=...)`) — never the `_autopaginate` methods. `_autopaginate` does not expose the boundary between pages, which prevents emitting STATE per page.

**3. Schemas:** the `.json` files in `schemas/` are the source of truth. Code is derived from schemas, never the other way around.

**4. Streams:** 4 streams in v1 — `transactions`, `subscriptions`, `commissions`, `products`. See SPEC.md section 3 for fields, primary keys, and bookmark fields.

**5. Replication:** `transactions`, `subscriptions`, and `commissions` are INCREMENTAL. `products` is FULL_TABLE (the API does not expose an updated-at field).

---

## Code conventions

### Required in every file

```python
from __future__ import annotations  # always at the top of every file
```

**Early returns and guard clauses — no `else` after `return` or `raise`:**

```python
# CORRECT
def parse_timestamp(value: int | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        return None
    return int(value)

# WRONG — never do this
def parse_timestamp(value):
    if value is not None:
        if isinstance(value, (int, float)):
            return int(value)
```

**Type hints required on all public functions.**

**Naming:**
- Streams: `snake_case` plural (`transactions`)
- Classes: `PascalCase` singular + `"Stream"` (`TransactionStream`)
- Constants: `UPPER_SNAKE_CASE`

### Quality tools

```bash
uv run ruff check .                                               # lint
uv run ruff format .                                              # format
uv run mypy tap_hotmart/                                          # type check
uv run pytest tests/ -v                                           # all tests
uv run pytest tests/ -m "not integration"                         # unit only
uv run pytest tests/ --cov=tap_hotmart --cov-report=term-missing  # coverage
```

All must pass without errors before any commit. Tool configuration lives in `pyproject.toml` — do not override via CLI flags.

---

## Development workflow (TDD)

**Always in this order. Never skip steps:**

1. Read the relevant section of `SPEC.md`
2. Write the failing test (`pytest` must return RED)
3. Write the minimum code to make the test pass (GREEN)
4. Refactor while keeping tests passing (REFACTOR)
5. Repeat

Do not write implementation before having a failing test for it.

---

## Error handling

The `hotmart-python` SDK raises typed exceptions. The tap handles only what it is responsible for:

```python
from hotmart_python.exceptions import NotFoundError, AuthenticationError

# NotFoundError      → log warning and continue (resource may have been deleted)
# AuthenticationError → re-raise (invalid credentials require human intervention)
# Everything else    → let the SDK handle it (retry, backoff, rate limiting are SDK responsibilities)
```

**Never reimplement retry, backoff, or token renewal.** The SDK already does this.

---

## Pagination loop pattern

All incremental streams follow this exact pattern:

```python
def get_records(self, context: dict | None) -> Iterable[dict]:
    page_token: str | None = None
    start_date_ms = self._iso_to_ms(self.config["start_date"])

    while True:
        page = self.client.<resource>.<method>(
            start_date=start_date_ms,
            page_token=page_token,
        )

        if not page or not page.items:
            break

        for item in page.items:
            record = item.model_dump()
            if not self._has_primary_key(record):
                self.logger.warning("Record missing primary key, skipping: %s", record)
                continue
            yield record

        if not page.page_info or not page.page_info.next_page_token:
            break

        page_token = page.page_info.next_page_token
```

---

## Required test cases

Before considering any stream "done", all tests below must exist and pass.

**`test_client.py`** (unit — no real API calls):
- `test_config_missing_client_id`
- `test_config_missing_client_secret`
- `test_config_missing_basic`
- `test_config_missing_start_date`
- `test_config_invalid_start_date_format`
- `test_pagination_loop_stops_on_null_next_token`
- `test_pagination_loop_stops_on_empty_next_token`
- `test_null_fields_emitted_as_null`
- `test_record_missing_primary_key_is_discarded`
- `test_start_date_converted_to_milliseconds`
- `test_not_found_error_is_skipped`
- `test_authentication_error_propagates`

**`test_streams.py`** (integration — uses VCR cassettes):

For each stream (`transactions`, `subscriptions`, `commissions`, `products`):
- `test_{stream}_emits_schema_before_records`
- `test_{stream}_records_match_schema`
- `test_{stream}_primary_key_present_in_all_records`
- `test_{stream}_state_written_after_each_page`
- `test_{stream}_bookmark_does_not_regress`

For incremental streams only:
- `test_{stream}_uses_start_date_on_first_run`
- `test_{stream}_resumes_from_bookmark`

---

## VCR cassettes

- Use `pytest-recording` (wrapper around `vcrpy`) with `@pytest.mark.vcr()`
- Cassettes live in `tests/cassettes/`
- Record once using real sandbox credentials
- Before committing: run `tests/sanitize_cassettes.py` to scrub tokens and emails
- Do not regenerate cassettes without a reason — they are the source of truth for API responses

```python
@pytest.mark.vcr()
def test_transactions_emits_schema_before_records(tap_config: dict) -> None:
    ...
```

---

## v1 completion criteria

The tap is ready when:

- [ ] `tap-hotmart --config config.json --discover` returns a valid catalog with 4 streams
- [ ] `tap-hotmart --config config.json` emits `SCHEMA → RECORD* → STATE` for all streams
- [ ] Incremental run with existing STATE uses the bookmark and does not return records before it
- [ ] Run without STATE uses `start_date` from config
- [ ] `pytest tests/` passes with no errors
- [ ] `ruff check .` passes with no errors
- [ ] `mypy tap_hotmart/` passes with no errors
- [ ] No token or credential appears in logs even with `log_level=DEBUG`

---

## Out of scope

- Analytical data modeling (ClickHouse schemas, dbt models)
- Data transformation (responsibility of the target and dbt)
- Anything that is not Singer extraction and emission