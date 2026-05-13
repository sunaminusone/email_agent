"""Tests for runtime PG timeout DSN helper."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from urllib.parse import parse_qsl, urlparse

from src.common.pg_runtime import with_runtime_timeouts


def _query(dsn: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(dsn).query, keep_blank_values=True))


def test_appends_connect_timeout_to_bare_dsn():
    dsn = with_runtime_timeouts("postgresql://user:pass@host:5432/db")
    assert _query(dsn).get("connect_timeout") == "5"


def test_appends_statement_timeout_via_options():
    dsn = with_runtime_timeouts("postgresql://user:pass@host:5432/db")
    assert "-c statement_timeout=30000" in _query(dsn).get("options", "")


def test_preserves_existing_connect_timeout():
    dsn = with_runtime_timeouts("postgresql://user@host/db?connect_timeout=15")
    assert _query(dsn).get("connect_timeout") == "15"


def test_preserves_existing_statement_timeout_in_options():
    dsn = with_runtime_timeouts(
        "postgresql://user@host/db?options=-c%20statement_timeout%3D60000"
    )
    options = _query(dsn).get("options", "")
    assert "60000" in options
    assert "30000" not in options  # didn't double-add the default


def test_merges_timeout_into_existing_unrelated_options():
    dsn = with_runtime_timeouts(
        "postgresql://user@host/db?options=-c%20application_name%3Demail_agent"
    )
    options = _query(dsn).get("options", "")
    assert "application_name=email_agent" in options
    assert "statement_timeout=30000" in options


def test_postgres_scheme_alias_also_modified():
    dsn = with_runtime_timeouts("postgres://user@host/db")
    assert _query(dsn).get("connect_timeout") == "5"


def test_empty_dsn_passthrough():
    assert with_runtime_timeouts("") == ""


def test_non_postgres_dsn_passthrough():
    # Registry sources may legitimately accept non-PG DSNs (file:// etc.)
    assert with_runtime_timeouts("file:///tmp/x.db") == "file:///tmp/x.db"


def test_options_space_encoded_as_percent20_for_libpq():
    """libpq treats '+' as literal '+' in the options query value, not as a
    space. Use %20 so '-c statement_timeout=30000' parses correctly."""
    dsn = with_runtime_timeouts("postgresql://user@host/db")
    # Raw URL must contain %20 for the space, never '+'
    raw = dsn.split("options=", 1)[1]
    assert "+" not in raw
    assert "%20" in raw

    # And libpq's own parser yields a space-separated options string
    import psycopg
    parsed = psycopg.conninfo.conninfo_to_dict(dsn)
    assert parsed.get("options") == "-c statement_timeout=30000"
