import json
import sqlite3
from datetime import date, datetime

import pytest

from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services import backup


def _populate(conn):
    sch = ScheduleRepository(conn)
    sid = sch.add(Schedule("스탠드업", datetime(2026, 10, 1, 9, 30), datetime(2026, 10, 1, 10, 0),
                           color="blue", recurrence="daily", remind_before_min=10))
    sch.delete_occurrence(sid, date(2026, 10, 3))
    sch.add(Schedule("종일 행사", datetime(2026, 10, 9, 0, 0), all_day=True, color="pink"))
    todos = TodoRepository(conn)
    todos.add(Todo("데일리", day=date(2026, 10, 5), priority=2))
    todos.add(Todo("퀵"))
    MemoRepository(conn).set("메모 내용\n두 번째 줄")
    SettingsRepository(conn).set("hotkey", "Ctrl+Alt+K")


def _snapshot(conn):
    return backup.export_data(conn) | {"exported_at": ""}


def test_export_import_roundtrip_is_lossless(tmp_path):
    src = db.connect(":memory:")
    _populate(src)
    file = tmp_path / "out.json"
    backup.export_to_file(src, file)

    dst = db.connect(":memory:")
    TodoRepository(dst).add(Todo("지워질 기존 데이터"))
    backup.import_from_file(dst, file, tmp_path / "bk")
    assert _snapshot(dst) == _snapshot(src)
    # 삭제 예외까지 복원되어 화면에도 같은 결과가 나온다
    days = [o.date.day for o in ScheduleRepository(dst).list_occurrences(date(2026, 10, 1), date(2026, 10, 5))
            if o.title == "스탠드업"]
    assert days == [1, 2, 4, 5]


def test_export_never_contains_secrets(tmp_path):
    conn = db.connect(":memory:")
    SettingsRepository(conn).set("ai_provider", "gemini")
    for bad in ("ai_api_key", "gemini_key", "openai_token", "secret_thing"):
        SettingsRepository(conn).set(bad, "SUPER-SECRET-VALUE")
    file = tmp_path / "out.json"
    backup.export_to_file(conn, file)
    text = file.read_text(encoding="utf-8")
    assert "SUPER-SECRET-VALUE" not in text
    assert json.loads(text)["settings"] == {"ai_provider": "gemini"}


def test_import_ignores_secrets_even_if_file_contains_them(tmp_path):
    conn = db.connect(":memory:")
    data = backup.export_data(conn)
    data["settings"] = {"ai_provider": "claude", "api_key": "LEAK"}
    file = tmp_path / "in.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    backup.import_from_file(conn, file, tmp_path / "bk")
    assert SettingsRepository(conn).get("ai_provider") == "claude"
    assert SettingsRepository(conn).get("api_key") == ""


def test_import_makes_backup_of_current_db_first(tmp_path):
    conn = db.connect(":memory:")
    TodoRepository(conn).add(Todo("가져오기 전 데이터"))
    empty = tmp_path / "empty.json"
    backup.export_to_file(db.connect(":memory:"), empty)

    saved = backup.import_from_file(conn, empty, tmp_path / "bk")
    assert saved.parent == tmp_path / "bk" and saved.exists()
    assert TodoRepository(conn).list_quick() == []
    old = sqlite3.connect(str(saved))
    try:
        assert old.execute("SELECT title FROM todos").fetchall() == [("가져오기 전 데이터",)]
    finally:
        old.close()


@pytest.mark.parametrize("content", [
    "이건 JSON이 아님",
    "[]",
    '{"app": "Other", "format_version": 1}',
    '{"app": "FlowCalendar", "format_version": 99}',
    '{"app": "FlowCalendar", "format_version": 1, "todos": [{"id": 1}]}',
    '{"app": "FlowCalendar", "format_version": 1, "schedules": "x"}',
])
def test_invalid_file_is_rejected_and_nothing_changes(tmp_path, content):
    conn = db.connect(":memory:")
    _populate(conn)
    before = _snapshot(conn)
    file = tmp_path / "bad.json"
    file.write_text(content, encoding="utf-8")
    with pytest.raises(backup.BackupError):
        backup.import_from_file(conn, file, tmp_path / "bk")
    assert _snapshot(conn) == before
    assert not (tmp_path / "bk").exists()  # 검증 단계에서 막혀 백업도 만들지 않는다


def test_failure_in_the_middle_rolls_back(tmp_path):
    conn = db.connect(":memory:")
    _populate(conn)
    before = _snapshot(conn)
    data = backup.export_data(conn)
    data["schedules"][0]["color"] = "yellow"
    # 존재하지 않는 일정을 가리키는 예외 행 -> 외래키 위반이 삭제/삽입 한참 뒤에 터진다
    data["recurrence_exceptions"].append(
        {"id": 99, "schedule_id": 12345, "occurrence_date": "2026-10-01", "is_deleted": 1}
    )
    data["todos"] = []
    file = tmp_path / "broken.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(backup.BackupError):
        backup.import_from_file(conn, file, tmp_path / "bk")
    assert _snapshot(conn) == before
    assert (tmp_path / "bk").exists()  # 이 경우 백업은 이미 만들어져 있다


def test_missing_file_gives_readable_error(tmp_path):
    with pytest.raises(backup.BackupError):
        backup.import_from_file(db.connect(":memory:"), tmp_path / "없음.json", tmp_path / "bk")
