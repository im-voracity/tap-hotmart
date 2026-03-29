"""Sanitize VCR cassette files before committing.

Scrubs credentials, tokens, and PII from recorded HTTP interactions.
Run this script after recording new cassettes with real sandbox credentials:

    uv run python tests/sanitize_cassettes.py
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

CASSETTES_DIR = Path(__file__).parent / "cassettes"

REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # Authorization headers
    (re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.IGNORECASE), r"\1REDACTED"),
    (re.compile(r"(Authorization:\s*Basic\s+)\S+", re.IGNORECASE), r"\1REDACTED"),
    # OAuth tokens in response bodies
    (re.compile(r'"access_token"\s*:\s*"[^"]*"'), '"access_token": "REDACTED"'),
    (re.compile(r'"refresh_token"\s*:\s*"[^"]*"'), '"refresh_token": "REDACTED"'),
    # Email addresses
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "user@example.com"),
    # client_id / client_secret values
    (re.compile(r'(client_id=)[^&"\s]+'), r"\1REDACTED"),
    (re.compile(r'(client_secret=)[^&"\s]+'), r"\1REDACTED"),
    (re.compile(r'"client_id"\s*:\s*"[^"]*"'), '"client_id": "REDACTED"'),
    (re.compile(r'"client_secret"\s*:\s*"[^"]*"'), '"client_secret": "REDACTED"'),
]


def sanitize_file(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    for pattern, replacement in REPLACEMENTS:
        content = pattern.sub(replacement, content)
    path.write_text(content, encoding="utf-8")
    print(f"Sanitized: {path.name}")


def main() -> None:
    cassettes = list(CASSETTES_DIR.glob("*.yaml"))
    if not cassettes:
        print("No cassette files found in", CASSETTES_DIR)
        sys.exit(0)

    for cassette in cassettes:
        sanitize_file(cassette)

    print(f"\nDone. {len(cassettes)} cassette(s) sanitized.")


if __name__ == "__main__":
    main()
