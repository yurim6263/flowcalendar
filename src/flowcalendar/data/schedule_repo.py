import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta

from flowcalendar.domain.models import Occurrence, Schedule, validate
from flowcalendar.domain.recurrence import expand, sort_key


def _dt(value: datetime | None) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


def _d(value: date | None) -> str | None:
    return value.isoformat() if value else None


def like_pattern(query: str) -> str:
    """LIKE 검색용: 입력한 % 와 _ 는 글자 그대로 찾도록 막는다 (SQL 쪽 ESCAPE 문자는 역슬래시)."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class ScheduleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- 단건 CRUD ------------------------------------------------------

    def add(self, schedule: Schedule) -> int:
        validate(schedule)
        with self.conn:
            return self._insert(schedule)

    def get(self, schedule_id: int) -> Schedule | None:
        row = self.conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        return self._to_schedule(row) if row else None

    def update(self, schedule: Schedule) -> None:
        validate(schedule)
        with self.conn:
            self._update(schedule)

    def delete(self, schedule_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    # ---- 조회 -----------------------------------------------------------

    def list_occurrences(self, start: date, end: date) -> list[Occurrence]:
        # 여러 날에 걸친 일정은 범위보다 먼저 시작했어도 범위 안으로 이어지면 포함한다.
        rows = self.conn.execute(
            """
            WITH s AS (
              SELECT *, CAST(COALESCE(julianday(substr(end_at, 1, 10))
                                      - julianday(substr(start_at, 1, 10)), 0) AS INTEGER) AS span
              FROM schedules
            )
            SELECT * FROM s
            WHERE (recurrence IS NULL
                   AND substr(start_at, 1, 10) <= :e
                   AND substr(COALESCE(end_at, start_at), 1, 10) >= :s)
               OR (recurrence IS NOT NULL
                   AND substr(start_at, 1, 10) <= :e
                   AND (recurrence_until IS NULL
                        OR date(recurrence_until, '+' || span || ' days') >= :s))
            """,
            {"s": start.isoformat(), "e": end.isoformat()},
        ).fetchall()
        lookback = max((r["span"] for r in rows), default=0)
        deleted = self._deleted_dates(
            [r["id"] for r in rows], start - timedelta(days=lookback), end
        )
        result: list[Occurrence] = []
        for row in rows:
            schedule = self._to_schedule(row)
            result.extend(expand(schedule, start, end, deleted.get(schedule.id, set())))
        result.sort(key=lambda o: (o.date, *sort_key(o)))
        return result

    def search(self, query: str, today: date, limit: int = 30) -> list[Schedule]:
        """제목에 query 가 들어 있는 일정(반복 일정은 한 건). 오늘에서 가까운 날짜부터."""
        rows = self.conn.execute(
            """
            SELECT * FROM schedules WHERE title LIKE :q ESCAPE '\\'
            ORDER BY ABS(julianday(substr(start_at, 1, 10)) - julianday(:today)), id
            LIMIT :limit
            """,
            {"q": like_pattern(query), "today": today.isoformat(), "limit": limit},
        ).fetchall()
        return [self._to_schedule(r) for r in rows]

    # ---- 반복 일정: "이 일정만" / "이후 전체" ------------------------------

    def delete_occurrence(self, schedule_id: int, day: date) -> None:
        """이 일정만 삭제."""
        with self.conn:
            self._mark_deleted(schedule_id, day)

    def restore_occurrence(self, schedule_id: int, day: date) -> None:
        """delete_occurrence / update_occurrence 로 뺀 회차를 다시 살린다 (되돌리기용)."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM recurrence_exceptions WHERE schedule_id = ? AND occurrence_date = ?",
                (schedule_id, day.isoformat()),
            )

    def delete_from(self, schedule_id: int, day: date) -> None:
        """이 일정과 이후 전체 삭제. 첫 회차이면 시리즈 전체를 지운다."""
        schedule = self.get(schedule_id)
        if schedule is None:
            return
        with self.conn:
            if day <= schedule.start_at.date():
                self.conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
            else:
                self._set_until(schedule_id, day - timedelta(days=1))

    def update_occurrence(self, schedule_id: int, day: date, new: Schedule) -> int:
        """이 일정만 수정: 해당 회차를 빼고, 수정본을 반복 없는 단일 일정으로 만든다."""
        validate(new)
        with self.conn:
            self._mark_deleted(schedule_id, day)
            return self._insert(replace(new, id=None, recurrence=None, recurrence_until=None))

    def update_from(self, schedule_id: int, day: date, new: Schedule) -> int:
        """이 일정과 이후 전체 수정: 시리즈를 이 날 전날까지로 끊고, 수정본을 새 시리즈로 만든다."""
        validate(new)
        old = self.get(schedule_id)
        if old is None:
            raise KeyError(schedule_id)
        with self.conn:
            if day <= old.start_at.date():
                self._update(replace(new, id=schedule_id))
                self.conn.execute(
                    "DELETE FROM recurrence_exceptions WHERE schedule_id = ?", (schedule_id,)
                )
                return schedule_id
            self._set_until(schedule_id, day - timedelta(days=1))
            return self._insert(replace(new, id=None))

    # ---- 내부 -----------------------------------------------------------

    def _insert(self, s: Schedule) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO schedules
              (title, start_at, end_at, all_day, color, recurrence, recurrence_until,
               remind_before_min)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (s.title.strip(), _dt(s.start_at), _dt(s.end_at), int(s.all_day), s.color,
             s.recurrence, _d(s.recurrence_until), s.remind_before_min),
        )
        return cur.lastrowid

    def _update(self, s: Schedule) -> None:
        self.conn.execute(
            """
            UPDATE schedules SET title = ?, start_at = ?, end_at = ?, all_day = ?, color = ?,
              recurrence = ?, recurrence_until = ?, remind_before_min = ?,
              updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (s.title.strip(), _dt(s.start_at), _dt(s.end_at), int(s.all_day), s.color,
             s.recurrence, _d(s.recurrence_until), s.remind_before_min, s.id),
        )

    def _mark_deleted(self, schedule_id: int, day: date) -> None:
        schedule = self.get(schedule_id)
        if schedule is not None and schedule.recurrence is None:
            self.conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
            return
        self.conn.execute(
            """
            INSERT INTO recurrence_exceptions (schedule_id, occurrence_date, is_deleted)
            VALUES (?, ?, 1)
            ON CONFLICT (schedule_id, occurrence_date) DO UPDATE SET is_deleted = 1
            """,
            (schedule_id, day.isoformat()),
        )

    def _set_until(self, schedule_id: int, until: date) -> None:
        self.conn.execute(
            "UPDATE schedules SET recurrence_until = ?, "
            "updated_at = datetime('now', 'localtime') WHERE id = ?",
            (until.isoformat(), schedule_id),
        )

    def _deleted_dates(self, ids: list[int], start: date, end: date) -> dict[int, set[date]]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT schedule_id, occurrence_date FROM recurrence_exceptions "
            f"WHERE is_deleted = 1 AND schedule_id IN ({marks}) "
            f"AND occurrence_date BETWEEN ? AND ?",
            (*ids, start.isoformat(), end.isoformat()),
        ).fetchall()
        result: dict[int, set[date]] = {}
        for row in rows:
            result.setdefault(row["schedule_id"], set()).add(
                date.fromisoformat(row["occurrence_date"])
            )
        return result

    @staticmethod
    def _to_schedule(row: sqlite3.Row) -> Schedule:  # 'span' 같은 보조 열은 무시한다
        return Schedule(
            id=row["id"],
            title=row["title"],
            start_at=datetime.fromisoformat(row["start_at"]),
            end_at=datetime.fromisoformat(row["end_at"]) if row["end_at"] else None,
            all_day=bool(row["all_day"]),
            color=row["color"],
            recurrence=row["recurrence"],
            recurrence_until=(
                date.fromisoformat(row["recurrence_until"]) if row["recurrence_until"] else None
            ),
            remind_before_min=row["remind_before_min"],
        )
