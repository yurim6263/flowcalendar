import sqlite3


class MemoRepository:
    """Quick Memo는 한 장이라 memos 테이블의 첫 행만 쓴다 (정의서 8장)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self) -> str:
        row = self.conn.execute("SELECT content FROM memos ORDER BY id LIMIT 1").fetchone()
        return row["content"] if row else ""

    def set(self, content: str) -> None:
        with self.conn:
            row = self.conn.execute("SELECT id FROM memos ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self.conn.execute("INSERT INTO memos (content) VALUES (?)", (content,))
            else:
                self.conn.execute(
                    "UPDATE memos SET content = ?, updated_at = datetime('now', 'localtime') "
                    "WHERE id = ?",
                    (content, row["id"]),
                )
