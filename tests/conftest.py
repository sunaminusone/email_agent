"""Pytest configuration shared across the test suite.

Adds the ``--integration`` flag that gates tests hitting real external
backends (Postgres / Chroma / S3 / QuickBooks). Without the flag, any
test marked ``@pytest.mark.integration`` is skipped, so the default
``pytest`` invocation stays hermetic and fast.
"""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests against real PG/Chroma/S3/QuickBooks backends.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: hits a real external backend; skipped unless --integration is passed",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="integration test; pass --integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
