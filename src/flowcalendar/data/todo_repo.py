import sqlite3
from datetime import date, datetime, timedelta

from flowcalendar.data.schedule_repo import like_pattern
from flowcalendar.domain.models import Todo, validate_todo

# 완료한 항목은 아래로, 그 안에서는 우선순위가 높은 것부터 입력 순서대로.
_ORDER = "ORDER BY done, priority DESC, sort_order, id"


def _d(value: date | None) -> str | None:
    return value.isoformat() if value else None


class TodoRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, todo: Todo) -> int:
        validate_todo(todo)
        with self.conn:
            return self._insert(todo, self._next_order(todo.day))

    def get(self, todo_id: int) -> Todo | None:
        row = self.conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        return self._to_todo(row) if row else None

    def update(self, todo: Todo) -> None:
        validate_todo(todo)
        with self.conn:
            self.conn.execute(
                """
                UPDATE todos SET title = ?, done = ?, priority = ?,
                  done_at = CASE WHEN ? = 1 THEN COALESCE(done_at, datetime('now', 'localtime')) ELSE NULL END,
                  updated_at = datetime('now', 'localtime')
                WHERE id = ?
                """,
                (todo.title.strip(), int(todo.done), todo.priority, int(todo.done), todo.id),
            )

    def move_to_date(self, todo_id: int, day: date | None) -> None:
        """Quick -> Daily (또는 반대로). 옮겨 간 곳의 맨 끝에 놓는다."""
        with self.conn:
            self.conn.execute(
                "UPDATE todos SET date = ?, sort_order = ?, "
                "updated_at = datetime('now', 'localtime') WHERE id = ?",
                (_d(day), self._next_order(day), todo_id),
            )

    def delete(self, todo_id: int) -> Todo | None:
        """삭제하고, Undo에 쓸 수 있게 지운 항목을 돌려준다."""
        snapshot = self.get(todo_id)
        with self.conn:
            self.conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        return snapshot

    def restore(self, todo: Todo) -> None:
        """delete()가 돌려준 항목을 같은 id, 같은 순서로 되살린다."""
        with self.conn:
            self._insert(todo, todo.sort_order, keep_id=True)

    def purge_done(self, keep_days: int, now: datetime | None = None) -> int:
        """완료한 지 keep_days 일이 지난 할 일을 지우고, 지운 개수를 돌려준다. keep_days <= 0 이면 계속 보관한다."""
        if keep_days <= 0:
            return 0
        cutoff = ((now or datetime.now()) - timedelta(days=keep_days)).isoformat(sep=" ", timespec="seconds")
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM todos WHERE done = 1 AND done_at IS NOT NULL AND done_at < ?", (cutoff,)
            )
        return cur.rowcount

    def search(self, query: str, today: date, limit: int = 30) -> list[Todo]:
        """내용에 query 가 들어 있는 할 일. 안 끝낸 것이 먼저, 그 안에서는 오늘에서 가까운 날짜 순(날짜 없는 것은 뒤)."""
        rows = self.conn.execute(
            """
            SELECT * FROM todos WHERE title LIKE :q ESCAPE '\\'
            ORDER BY done, date IS NULL, ABS(julianday(date) - julianday(:today)), id
            LIMIT :limit
            """,
            {"q": like_pattern(query), "today": today.isoformat(), "limit": limit},
        ).fetchall()
        return [self._to_todo(r) for r in rows]

    def list_daily(self, start: date, end: date) -> list[Todo]:
        rows = self.conn.execute(
            f"SELECT * FROM todos WHERE date BETWEEN ? AND ? {_ORDER}",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._to_todo(r) for r in rows]

    def list_quick(self) -> list[Todo]:
        rows = self.conn.execute(f"SELECT * FROM todos WHERE date IS NULL {_ORDER}").fetchall()
        return [self._to_todo(r) for r in rows]

    # ---- 내부 -----------------------------------------------------------

    def _next_order(self, day: date | None) -> int:
        if day is None:
            row = self.conn.execute("SELECT MAX(sort_order) FROM todos WHERE date IS NULL")
        else:
            row = self.conn.execute(
                "SELECT MAX(sort_order) FROM todos WHERE date = ?", (day.isoformat(),)
            )
        top = row.fetchone()[0]
        return 0 if top is None else top + 1

    def _insert(self, todo: Todo, sort_order: int, keep_id: bool = False) -> int:
        columns = "title, date, done, priority, sort_order, done_at"
        values = [todo.title.strip(), _d(todo.day), int(todo.done), todo.priority, sort_order,
                  datetime.now().isoformat(sep=" ", timespec="seconds") if todo.done else None]
        if keep_id:
            columns = "id, " + columns
            values.insert(0, todo.id)
        marks = ", ".join("?" * len(values))
        return self.conn.execute(
            f"INSERT INTO todos ({columns}) VALUES ({marks})", values
        ).lastrowid

    @staticmethod
    def _to_todo(row: sqlite3.Row) -> Todo:
        return Todo(
            id=row["id"],
            title=row["title"],
            day=date.fromisoformat(row["date"]) if row["date"] else None,
            done=bool(row["done"]),
            priority=row["priority"],
            sort_order=row["sort_order"],
        )
