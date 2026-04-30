"""Cover the safety guarantees of ConversationStore.persist_turn.

The store is a sidecar to run_email_agent — it must not propagate failures
up the call stack. Tests below pin the three cases where silent degradation
is the contract:
  1. psycopg unavailable  → no-op, no raise
  2. empty thread_key     → no-op, no raise
  3. PG connect raises    → caught, logged, no raise
"""
from __future__ import annotations

import logging

import pytest

from src.conversations import store as store_module
from src.conversations.store import ConversationStore


def _make_messages():
    user = {"role": "user", "content": "hi", "metadata": {}}
    assistant = {"role": "assistant", "content": "hello", "metadata": {}}
    return user, assistant


def test_persist_turn_noop_when_psycopg_missing(monkeypatch):
    monkeypatch.setattr(store_module, "psycopg", None)
    cs = ConversationStore()
    user, assistant = _make_messages()

    cs.persist_turn(
        thread_key="t1",
        thread_title="T",
        user_message=user,
        assistant_message=assistant,
    )


def test_persist_turn_noop_when_thread_key_empty():
    cs = ConversationStore()
    user, assistant = _make_messages()

    cs.persist_turn(
        thread_key="",
        thread_title="T",
        user_message=user,
        assistant_message=assistant,
    )


def test_persist_turn_swallows_connect_errors(monkeypatch, caplog):
    class _BoomPsycopg:
        @staticmethod
        def connect(_dsn):
            raise RuntimeError("simulated RDS outage")

    monkeypatch.setattr(store_module, "psycopg", _BoomPsycopg)
    cs = ConversationStore()
    cs._dsn = "postgresql://stub"  # bypass dsn-empty short-circuit
    user, assistant = _make_messages()

    with caplog.at_level(logging.WARNING, logger=store_module.__name__):
        cs.persist_turn(
            thread_key="t1",
            thread_title="T",
            user_message=user,
            assistant_message=assistant,
        )

    assert any("persist_turn failed" in r.message for r in caplog.records), (
        "expected a WARNING log when PG connect fails, got: "
        + repr([r.message for r in caplog.records])
    )
