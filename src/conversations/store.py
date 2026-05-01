from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None

from src.config.settings import BASE_DIR


load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)

THREADS_TABLE = os.getenv("CONVERSATION_THREADS_TABLE", "conversation_threads").strip() or "conversation_threads"
MESSAGES_TABLE = os.getenv("CONVERSATION_MESSAGES_TABLE", "conversation_messages").strip() or "conversation_messages"
MESSAGE_DOCUMENTS_TABLE = os.getenv(
    "CONVERSATION_MESSAGE_DOCUMENTS_TABLE",
    "conversation_message_documents",
).strip() or "conversation_message_documents"


def build_connection_string() -> str:
    from src.common.pg_runtime import with_runtime_timeouts

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return with_runtime_timeouts(database_url)

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    dbname = os.getenv("PGDATABASE", "promab")
    auth = user if not password else f"{user}:{password}"
    return with_runtime_timeouts(f"postgresql://{auth}@{host}:{port}/{dbname}")


class ConversationStore:
    def __init__(self) -> None:
        self._dsn = build_connection_string()
        self._has_documents_table: bool | None = None

    def is_configured(self) -> bool:
        return psycopg is not None and bool(self._dsn)

    def persist_turn(
        self,
        *,
        thread_key: str,
        thread_title: str,
        user_message: dict[str, Any],
        assistant_message: dict[str, Any],
    ) -> None:
        if not self.is_configured() or not thread_key:
            return

        # Persistence is a best-effort sidecar to the agent's response. RDS
        # outages, network blips, or schema drift must not propagate up and
        # break run_email_agent — degrade to log-only and let the request
        # complete normally.
        try:
            with psycopg.connect(self._dsn) as conn:
                thread_id = self._upsert_thread(conn, thread_key=thread_key, title=thread_title)
                self._insert_message(conn, thread_id=thread_id, message=user_message)
                assistant_message_id = self._insert_message(conn, thread_id=thread_id, message=assistant_message)
                self._persist_message_documents(conn, assistant_message_id, assistant_message)
                conn.commit()
        except Exception as exc:
            logger.warning(
                "ConversationStore.persist_turn failed for thread_key=%s: %s",
                thread_key,
                exc,
            )

    def list_threads(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        sql = f"""
            SELECT
                t.id,
                t.thread_key,
                t.title,
                t.created_at,
                t.updated_at,
                COUNT(m.id) AS message_count,
                MAX(
                    CASE
                        WHEN m.role = 'assistant' AND NULLIF(m.content, '') IS NOT NULL THEN m.content
                        WHEN m.role = 'user' AND NULLIF(m.content, '') IS NOT NULL THEN m.content
                        ELSE NULL
                    END
                ) AS preview
            FROM {THREADS_TABLE} t
            LEFT JOIN {MESSAGES_TABLE} m
                ON m.thread_id = t.id
            GROUP BY t.id, t.thread_key, t.title, t.created_at, t.updated_at
            ORDER BY t.updated_at DESC
            LIMIT %s
        """
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_thread_messages(self, thread_key: str) -> list[dict[str, Any]]:
        if not self.is_configured() or not thread_key:
            return []

        sql = f"""
            SELECT
                m.id,
                m.role,
                m.content,
                m.response_type,
                m.response_path,
                m.metadata,
                m.created_at
            FROM {MESSAGES_TABLE} m
            JOIN {THREADS_TABLE} t
                ON t.id = m.thread_id
            WHERE t.thread_key = %s
            ORDER BY m.created_at ASC
        """
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (thread_key,))
                rows = cur.fetchall()
        return [
            {
                "id": str(row.get("id", "")),
                "role": row.get("role", "user"),
                "content": row.get("content", ""),
                "metadata": dict(row.get("metadata") or {}),
                "response_type": row.get("response_type") or "",
                "response_path": row.get("response_path") or "",
                "created_at": row.get("created_at").isoformat() if row.get("created_at") else "",
            }
            for row in rows
        ]

    def delete_thread(self, thread_key: str) -> bool:
        if not self.is_configured() or not thread_key:
            return False

        sql = f"""
            DELETE FROM {THREADS_TABLE}
            WHERE thread_key = %s
        """
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (thread_key,))
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def rename_thread(self, thread_key: str, title: str) -> bool:
        if not self.is_configured() or not thread_key:
            return False

        normalized_title = str(title or "").strip()
        if not normalized_title:
            return False

        sql = f"""
            UPDATE {THREADS_TABLE}
            SET title = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE thread_key = %s
        """
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (normalized_title, thread_key))
                updated = cur.rowcount > 0
            conn.commit()
        return updated

    def _upsert_thread(self, conn, *, thread_key: str, title: str):
        sql = f"""
            INSERT INTO {THREADS_TABLE} (thread_key, title)
            VALUES (%s, NULLIF(%s, ''))
            ON CONFLICT (thread_key)
            DO UPDATE SET
                title = COALESCE({THREADS_TABLE}.title, EXCLUDED.title),
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """
        with conn.cursor() as cur:
            cur.execute(sql, (thread_key, title))
            row = cur.fetchone()
        return row[0]

    def _insert_message(self, conn, *, thread_id, message: dict[str, Any]):
        metadata = dict(message.get("metadata") or {})
        sql = f"""
            INSERT INTO {MESSAGES_TABLE} (
                thread_id,
                role,
                content,
                response_type,
                response_path,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
        """
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    thread_id,
                    str(message.get("role", "user")),
                    str(message.get("content", "")),
                    str(metadata.get("response_type", "") or "") or None,
                    str(metadata.get("response_path", "") or "") or None,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        return row[0]

    def _persist_message_documents(self, conn, message_id, message: dict[str, Any]) -> None:
        documents = list((message.get("metadata") or {}).get("documents") or [])
        if not documents or not self._message_documents_table_exists(conn):
            return

        sql = f"""
            INSERT INTO {MESSAGE_DOCUMENTS_TABLE} (
                message_id,
                document_label,
                document_url,
                file_name,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s::jsonb)
        """
        with conn.cursor() as cur:
            for document in documents:
                document_url = str(document.get("document_url", "") or "").strip()
                if not document_url:
                    continue
                cur.execute(
                    sql,
                    (
                        message_id,
                        str(document.get("label", "") or "") or None,
                        document_url,
                        str(document.get("file_name", "") or "") or None,
                        json.dumps(document, ensure_ascii=False),
                    ),
                )

    def _message_documents_table_exists(self, conn) -> bool:
        if self._has_documents_table is not None:
            return self._has_documents_table

        query = """
            SELECT to_regclass(%s)
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (f"public.{MESSAGE_DOCUMENTS_TABLE}",))
            row = cur.fetchone()
        self._has_documents_table = bool(row and row.get("to_regclass"))
        return self._has_documents_table
