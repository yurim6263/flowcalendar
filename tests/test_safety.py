"""데이터 안전(자동 백업, 업그레이드 전 백업), 완료 할 일 보관 기간, 브리핑 대기, AI 모델 자동 대체."""

import sqlite3
from datetime import date, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from flowcalendar import app as app_module
from flowcalendar.ai.errors import AIError
from flowcalendar.data import db
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Todo
from flowcalendar.services import auto_backup, backup
from flowcalendar.services.ai_service import (
    BRIEFING_TIMEOUT, AIService, model_setting_key, pick_replacement,
)
from flowcalendar.ui import tokens
from flowcalendar.ui.settings_dialog import SettingsDialog, saved_keep_days
from tests.conftest import MemorySecrets
from tests.test_app_desktop import FakeTray
from tests.test_theme import _backend

NOW = datetime(2026, 10, 28, 9, 0)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


# ---- 자동 백업 -------------------------------------------------------------------


def _conn_with_data(path=":memory:"):
    conn = db.connect(path)
    TodoRepository(conn).add(Todo("소중한 할 일"))
    return conn


def test_auto_backup_makes_one_copy_per_day_with_data(tmp_path):
    conn = _conn_with_data()
    first = auto_backup.run_if_due(conn, tmp_path, today=date(2026, 10, 28))
    assert first is not None and first.name == "auto-20261028.db"
    assert auto_backup.run_if_due(conn, tmp_path, today=date(2026, 10, 28)) is None  # 같은 날은 한 번만
    copy = sqlite3.connect(str(first))
    assert copy.execute("SELECT title FROM todos").fetchone()[0] == "소중한 할 일"
    copy.close()
    assert not list(tmp_path.glob("*.part"))


def test_auto_backup_keeps_only_the_latest_seven(tmp_path):
    conn = _conn_with_data()
    for i in range(10):
        auto_backup.run_if_due(conn, tmp_path, today=date(2026, 10, 1) + timedelta(days=i))
    names = [p.name for p in auto_backup.list_backups(tmp_path)]
    assert names == [f"auto-202610{d:02d}.db" for d in range(4, 11)]


def test_auto_backup_never_removes_other_backup_files(tmp_path):
    conn = _conn_with_data()
    other = tmp_path / "before-ai-inbox-20261028-115052.db"
    other.write_bytes(b"x")
    for i in range(9):
        auto_backup.run_if_due(conn, tmp_path, today=date(2026, 10, 1) + timedelta(days=i))
    assert other.exists()


def test_app_makes_backup_on_start_and_respects_setting(qapp, tmp_path):
    conn = _conn_with_data()
    c = app_module.FlowCalendarApp(conn, tmp_path / "bk", tray=FakeTray(), register_hotkey=False)
    try:
        assert len(auto_backup.list_backups(tmp_path / "bk")) == 1
    finally:
        c.scheduler.stop()

    conn2 = _conn_with_data()
    SettingsRepository(conn2).set_bool("auto_backup", False)
    c2 = app_module.FlowCalendarApp(conn2, tmp_path / "bk2", tray=FakeTray(), register_hotkey=False)
    try:
        assert auto_backup.list_backups(tmp_path / "bk2") == []
    finally:
        c2.scheduler.stop()


def test_backup_failure_does_not_stop_the_app(qapp, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("디스크가 가득 찼습니다")

    monkeypatch.setattr(auto_backup, "run_if_due", boom)
    c = app_module.FlowCalendarApp(_conn_with_data(), tmp_path / "bk", tray=FakeTray(), register_hotkey=False)
    try:
        assert "가득" in c.last_backup_error and c.window is not None
    finally:
        c.scheduler.stop()


# ---- 업그레이드 전 자동 백업 -----------------------------------------------------------


def test_old_database_is_copied_before_schema_upgrade(tmp_path):
    path = tmp_path / "flowcalendar.db"
    old = sqlite3.connect(str(path))
    old.row_factory = sqlite3.Row
    for target, script in enumerate(db.MIGRATIONS[:2], start=1):  # 옛 버전(스키마 2)을 흉내 낸다
        old.executescript(script)
        old.execute(f"PRAGMA user_version = {target}")
    old.execute("INSERT INTO todos (title, done) VALUES ('옛 데이터', 1)")
    old.commit()
    old.close()

    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    copies = list((tmp_path / "backups").glob("before-schema2to*.db"))
    assert len(copies) == 1
    saved = sqlite3.connect(str(copies[0]))
    assert saved.execute("PRAGMA user_version").fetchone()[0] == 2  # 올리기 전 모습 그대로
    assert saved.execute("SELECT title FROM todos").fetchone()[0] == "옛 데이터"
    saved.close()
    conn.close()


def test_new_or_current_database_makes_no_upgrade_backup(tmp_path):
    db.connect(tmp_path / "a.db").close()  # 새 DB
    db.connect(tmp_path / "a.db").close()  # 이미 최신
    assert not (tmp_path / "backups").exists()


def test_existing_done_todos_start_their_keep_period_at_upgrade(tmp_path):
    path = tmp_path / "x.db"
    old = sqlite3.connect(str(path))
    for target, script in enumerate(db.MIGRATIONS[:2], start=1):
        old.executescript(script)
        old.execute(f"PRAGMA user_version = {target}")
    old.execute("INSERT INTO todos (title, done) VALUES ('끝낸 일', 1), ('안 끝낸 일', 0)")
    old.commit()
    old.close()
    conn = db.connect(path)
    rows = dict(conn.execute("SELECT title, done_at FROM todos").fetchall())
    assert rows["끝낸 일"] is not None and rows["안 끝낸 일"] is None
    conn.close()


# ---- 완료한 할 일 보관 기간 -------------------------------------------------------------


@pytest.fixture
def todos():
    return TodoRepository(db.connect(":memory:"))


def _done(todos, title, days_ago, now=NOW):
    todo_id = todos.add(Todo(title))
    todo = todos.get(todo_id)
    todo.done = True
    todos.update(todo)
    stamp = (now - timedelta(days=days_ago)).isoformat(sep=" ", timespec="seconds")
    with todos.conn:  # 커밋까지 해 둔다 (열린 트랜잭션이 남아 있으면 같은 연결의 백업이 끝나지 않는다)
        todos.conn.execute("UPDATE todos SET done_at = ? WHERE id = ?", (stamp, todo_id))
    return todo_id


def test_completing_a_todo_records_when(todos):
    todo_id = todos.add(Todo("해야 할 일"))
    assert todos.conn.execute("SELECT done_at FROM todos WHERE id = ?", (todo_id,)).fetchone()[0] is None
    todo = todos.get(todo_id)
    todo.done = True
    todos.update(todo)
    assert todos.conn.execute("SELECT done_at FROM todos WHERE id = ?", (todo_id,)).fetchone()[0] is not None
    todo.done = False
    todos.update(todo)
    assert todos.conn.execute("SELECT done_at FROM todos WHERE id = ?", (todo_id,)).fetchone()[0] is None


def test_purge_removes_only_done_todos_older_than_keep_days(todos):
    old = _done(todos, "오래전에 끝냄", 31)
    recent = _done(todos, "어제 끝냄", 1)
    edge = _done(todos, "딱 30일 전", 29)
    open_id = todos.add(Todo("아직 안 끝냄"))
    removed = todos.purge_done(30, now=NOW)
    assert removed == 1
    assert todos.get(old) is None
    assert all(todos.get(i) is not None for i in (recent, edge, open_id))


def test_unchecking_resets_the_clock_and_keeps_todo(todos):
    todo_id = _done(todos, "다시 열 일", 40)
    todo = todos.get(todo_id)
    todo.done = False
    todos.update(todo)
    assert todos.purge_done(30, now=NOW) == 0 and todos.get(todo_id) is not None


def test_keep_forever_never_deletes(todos):
    old = _done(todos, "아주 오래전", 400)
    assert todos.purge_done(0, now=NOW) == 0 and todos.get(old) is not None


def test_keep_days_setting_validation():
    s = SettingsRepository(db.connect(":memory:"))
    assert saved_keep_days(s) == 30
    s.set("done_keep_days", "90")
    assert saved_keep_days(s) == 90
    s.set("done_keep_days", "0")
    assert saved_keep_days(s) == 0
    s.set("done_keep_days", "엉뚱")
    assert saved_keep_days(s) == 30
    s.set("done_keep_days", "-5")
    assert saved_keep_days(s) == 30


def test_app_purges_old_done_todos_at_start_but_after_backup(qapp, tmp_path):
    conn = db.connect(":memory:")
    repo = TodoRepository(conn)
    old = _done(repo, "오래된 완료", 45, now=datetime.now())
    keep = _done(repo, "최근 완료", 2, now=datetime.now())
    c = app_module.FlowCalendarApp(conn, tmp_path / "bk", tray=FakeTray(), register_hotkey=False)
    try:
        assert repo.get(old) is None and repo.get(keep) is not None
        copy = sqlite3.connect(str(auto_backup.list_backups(tmp_path / "bk")[0]))
        assert copy.execute("SELECT COUNT(*) FROM todos WHERE title = '오래된 완료'").fetchone()[0] == 1
        copy.close()  # 정리로 지워진 것도 방금 만든 백업에는 남아 있다
    finally:
        c.scheduler.stop()


def test_backup_json_keeps_done_at_and_old_files_still_import(tmp_path):
    conn = db.connect(":memory:")
    repo = TodoRepository(conn)
    tid = _done(repo, "끝낸 일", 3, now=datetime.now())
    path = tmp_path / "b.json"
    backup.export_to_file(conn, path)
    other = db.connect(":memory:")
    backup.import_from_file(other, path, tmp_path / "bk")
    assert other.execute("SELECT done_at FROM todos").fetchone()[0] is not None
    # done_at 이 없는 옛 내보내기 파일
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["todos"]:
        row.pop("done_at")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    backup.import_from_file(other, path, tmp_path / "bk")
    assert other.execute("SELECT title FROM todos").fetchone()[0] == "끝낸 일"
    assert tid


def test_settings_dialog_saves_backup_and_keep_days(qapp):
    conn = db.connect(":memory:")
    d = SettingsDialog(_backend(conn))
    assert d.auto_backup.isChecked() and d.keep_days.currentData() == 30
    d.auto_backup.setChecked(False)
    d.keep_days.setCurrentIndex(d.keep_days.findData(90))
    d._on_save()
    s = SettingsRepository(conn)
    assert not s.get_bool("auto_backup") and s.get("done_keep_days") == "90"


# ---- 브리핑 대기 시간 ------------------------------------------------------------------


class _Spy:
    """어댑터 대신: 만들 때 받은 옵션과 모델을 기록하고, 정해 둔 오류/결과를 낸다."""

    def __init__(self, log, behaviours):
        self.log, self.behaviours = log, behaviours

    def __call__(self, provider, key, model, **kwargs):
        self.log.append({"model": model, **kwargs})
        return _SpyAdapter(model, self.behaviours)


class _SpyAdapter:
    def __init__(self, model, behaviours):
        self.model, self.behaviours = model, behaviours

    def complete_json(self, system, user, schema, name="result"):
        outcome = self.behaviours[self.model]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def list_models(self):
        return self.behaviours["__models__"]


def _service(behaviours, model="old-flash"):
    conn = db.connect(":memory:")
    settings = SettingsRepository(conn)
    settings.set(model_setting_key("gemini"), model)
    log = []
    secrets = MemorySecrets()
    secrets.set("gemini", "KEY")
    service = AIService(settings, secrets, clock=lambda: NOW, adapter_factory=_Spy(log, behaviours))
    service.log = log
    return service


SUMMARY = {"summary": "오늘은 일정이 하나 있어요."}


def test_briefing_uses_short_timeout_and_no_retry_but_quick_add_does_not():
    from flowcalendar.ai import briefing

    service = _service({"old-flash": SUMMARY})
    data = briefing.build_data("day", date(2026, 10, 28), [], [], [])
    service.summarize_with(service.prepare(), data)
    assert service.log[-1]["timeout"] == BRIEFING_TIMEOUT == 10.0 and service.log[-1]["retry_delays"] == ()

    service2 = _service({"old-flash": {"items": []}})
    service2.parse_text_with(service2.prepare(), "내일 회의")
    assert "timeout" not in service2.log[-1]  # 빠른 추가는 기본 대기(30초)와 자동 재시도를 그대로 쓴다


# ---- AI 모델 자동 대체 -----------------------------------------------------------------


def test_pick_replacement_prefers_same_family_and_skips_old_and_preview():
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-pro", "gemini-2.5-flash-preview-09"]
    assert pick_replacement("gemini", "gemini-2.5-flash", models) == "gemini-2.5-flash-lite"
    assert pick_replacement("gemini", "gemini-2.0-flash", ["gemini-2.0-flash"]) is None
    assert pick_replacement("gemini", "x", []) is None


def test_missing_model_falls_back_once_and_reports(qapp):
    gone = AIError("model", "no longer available")
    service = _service({"old-flash": gone, "new-flash": {"items": []},
                        "__models__": ["old-flash", "new-flash"]})
    assert service.parse_text_with(service.prepare(), "내일 회의") == []
    assert [c["model"] for c in service.log] == ["old-flash", "old-flash", "new-flash"]
    notice = service.apply_fallback()
    assert "old-flash" in notice and "new-flash" in notice
    assert service.model() == "new-flash"  # 설정에 저장돼 다음부터는 바로 새 모델을 쓴다
    assert service.apply_fallback() is None  # 안내는 한 번만


def test_fallback_not_applied_when_user_changed_model_meanwhile():
    service = _service({"old-flash": AIError("model", "x"), "new-flash": {"items": []},
                        "__models__": ["new-flash"]})
    call = service.prepare()
    service.parse_text_with(call, "회의")
    service.settings.set(model_setting_key("gemini"), "내가 고른 모델")
    assert service.apply_fallback() is None and service.model() == "내가 고른 모델"


def test_other_errors_are_not_retried_with_another_model():
    service = _service({"old-flash": AIError("auth", "bad key"), "__models__": ["new-flash"]})
    with pytest.raises(AIError) as exc:
        service.parse_text_with(service.prepare(), "회의")
    assert exc.value.kind == "auth" and len(service.log) == 1


def test_original_error_when_no_replacement_exists():
    service = _service({"old-flash": AIError("model", "gone"), "__models__": ["old-flash"]})
    with pytest.raises(AIError) as exc:
        service.parse_text_with(service.prepare(), "회의")
    assert exc.value.kind == "model"


def test_original_error_when_model_list_cannot_be_read():
    class NoList(_SpyAdapter):
        def list_models(self):
            raise AIError("network", "offline")

    service = _service({"old-flash": AIError("model", "gone")})
    service._factory = lambda provider, key, model, **kw: NoList(model, {"old-flash": AIError("model", "gone")})
    with pytest.raises(AIError) as exc:
        service.parse_text_with(service.prepare(), "회의")
    assert exc.value.kind == "model"  # 목록을 못 읽어도 사용자에게는 원래 오류(모델 문제)를 보여 준다
