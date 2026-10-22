"""本地对话。SQLite，只放在用户数据目录里。"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ConversationStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                expert TEXT,
                expert_label TEXT,
                sim REAL,
                fired INTEGER,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def list_conversations(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def create(self, title: str = "新对话") -> dict[str, Any]:
        now = _now()
        conv_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conv_id, title, now, now),
        )
        self._conn.commit()
        return {"id": conv_id, "title": title, "created_at": now, "updated_at": now}

    def get(self, conv_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
        return dict(row) if row else None

    def set_title(self, conv_id: str, title: str) -> None:
        title = title.strip().replace("\n", " ")[:40] or "新对话"
        self._conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), conv_id),
        )
        self._conn.commit()

    def delete(self, conv_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        self._conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        self._conn.commit()

    def messages(self, conv_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, conversation_id, role, content, expert, expert_label, sim, fired, reason, created_at
            FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid
            """,
            (conv_id,),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["fired"] = bool(item["fired"]) if item["fired"] is not None else False
            out.append(item)
        return out

    def user_text(self, conv_id: str) -> str:
        parts = [msg["content"] for msg in self.messages(conv_id) if msg["role"] == "user"]
        return "\n".join(parts)

    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        expert: str | None = None,
        expert_label: str | None = None,
        sim: float | None = None,
        fired: bool | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        message_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            """
            INSERT INTO messages
            (id, conversation_id, role, content, expert, expert_label, sim, fired, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                conv_id,
                role,
                content,
                expert,
                expert_label,
                sim,
                None if fired is None else int(fired),
                reason,
                now,
            ),
        )
        self._conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
        self._conn.commit()
        return {
            "id": message_id,
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "expert": expert,
            "expert_label": expert_label,
            "sim": sim,
            "fired": fired,
            "reason": reason,
            "created_at": now,
        }
