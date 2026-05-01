"""Apply runtime PG timeout policy to a connection DSN.

connect_timeout bounds how long libpq waits when establishing the TCP
connection — without it, an unreachable RDS / collapsed SSM tunnel
hangs the executor indefinitely. statement_timeout bounds how long a
query may run server-side, after which Postgres cancels it; protects
the CSR loop from a runaway seq scan or wedged lock.

Both are tuned for the runtime request path. Offline scripts that
build their own DSNs are unaffected.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse


_CONNECT_TIMEOUT_SECONDS = 5
_STATEMENT_TIMEOUT_MS = 30_000


def with_runtime_timeouts(dsn: str) -> str:
    """Return *dsn* annotated with connect_timeout + statement_timeout.

    Existing user-supplied values for either parameter are preserved.
    Empty / non-postgres DSNs are returned unchanged so registries that
    legitimately have no PG configured still work.
    """
    if not dsn:
        return dsn

    parsed = urlparse(dsn)
    if parsed.scheme not in ("postgresql", "postgres"):
        return dsn

    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_pairs.setdefault("connect_timeout", str(_CONNECT_TIMEOUT_SECONDS))

    existing_options = query_pairs.get("options", "")
    if "statement_timeout" not in existing_options:
        statement_clause = f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}"
        query_pairs["options"] = f"{existing_options} {statement_clause}".strip()

    # libpq treats '+' as a literal '+' (not a space) inside ?options=, so
    # encode spaces as %20 by routing through quote instead of quote_plus.
    new_query = urlencode(query_pairs, quote_via=quote)
    return urlunparse(parsed._replace(query=new_query))
