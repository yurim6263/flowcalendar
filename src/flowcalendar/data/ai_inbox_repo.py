import sqlite3
from dataclasses import dataclass

MAX_ITEMS = 50  # 오래된 것부터 정리한다. 목록이 끝없이 쌓이지 않게 한다


@dataclass
class InboxItem:
    id: int
    text: str
    reason: str


class AIInboxRepository:
    """AI 빠른 추가에서 처리하지 못한 입력 목록. 사용자가 쓴 글을 잃지 않게 하려고 로컬 DB 에만 남긴다."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, text: str, reason: str) -> None:
        """같은 글이 이미 있으면 한 줄만 남기고 이유를 갱신해 맨 위로 올린다 (다시 시도했다 또 실패한 경우).
        최신순은 번호로 정한다: 시각은 초 단위라 같은 초 안의 일은 순서를 가릴 수 없다."""
        text = text.strip()
        if not text:
            return
        with self.conn:
            self.conn.execute("DELETE FROM ai_inbox WHERE text = ?", (text,))
            self.conn.execute("INSERT INTO ai_inbox (text, reason) VALUES (?, ?)", (text, reason))
            self.conn.execute(
                "DELETE FROM ai_inbox WHERE id NOT IN (SELECT id FROM ai_inbox ORDER BY id DESC LIMIT ?)",
                (MAX_ITEMS,),
            )

    def list(self) -> list[InboxItem]:
        rows = self.conn.execute("SELECT id, text, reason FROM ai_inbox ORDER BY id DESC").fetchall()
        return [InboxItem(r["id"], r["text"], r["reason"]) for r in rows]

    def delete(self, item_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM ai_inbox WHERE id = ?", (item_id,))

    def delete_text(self, text: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM ai_inbox WHERE text = ?", (text.strip(),))

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM ai_inbox").fetchone()[0]
