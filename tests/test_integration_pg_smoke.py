"""PG schema smoke test against the configured catalog database.

First slice of #6.1 (tools-module e2e integration). Catches schema drift
— table renames, drops, permission breaks — before a customer query
crashes on a missing relation. Does not validate row content; that
belongs in tool-level integration tests.

Run with ``pytest tests/test_integration_pg_smoke.py --integration``.
"""
from __future__ import annotations

import psycopg
import pytest

from src.catalog.retrieval.shared import build_connection_string

pytestmark = pytest.mark.integration


EXPECTED_TABLES = frozenset(
    {
        "product_catalog",
        "antibody_product_catalog",
        "cart_product_catalog",
        "lnp_product_catalog",
        "service_catalog",
        "service_documents",
        "historical_threads",
        "historical_thread_messages",
        "conversation_threads",
        "conversation_messages",
        "conversation_message_documents",
    }
)

# Tables the CSR runtime reads on every turn — emptiness is a real outage,
# not just a structural check.
SEEDED_TABLES = frozenset(
    {
        "product_catalog",
        "antibody_product_catalog",
        "service_catalog",
    }
)


@pytest.fixture(scope="module")
def pg_conn():
    with psycopg.connect(build_connection_string()) as conn:
        yield conn


def test_expected_tables_present(pg_conn) -> None:
    cur = pg_conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    actual = {row[0] for row in cur.fetchall()}
    missing = EXPECTED_TABLES - actual
    assert not missing, f"missing public tables: {sorted(missing)}"


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_table_is_queryable(pg_conn, table: str) -> None:
    cur = pg_conn.execute(f"SELECT 1 FROM {table} LIMIT 1")
    cur.fetchall()


@pytest.mark.parametrize("table", sorted(SEEDED_TABLES))
def test_seeded_table_has_rows(pg_conn, table: str) -> None:
    cur = pg_conn.execute(f"SELECT count(*) FROM {table}")
    (count,) = cur.fetchone()
    assert count > 0, f"{table} has zero rows; expected seeded data"
