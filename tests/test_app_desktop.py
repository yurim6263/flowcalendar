from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from flowcalendar import app as app_module
from flowcalendar.data import db
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services.reminder_scheduler import ReminderScheduler
from flowcalendar.services.secrets import SecretError
from flowcalendar.ui import tokens
from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


class FakeTray(QObject):
    open_requested = Signal()
    quit_requested = Signal()
    widget_mode_toggled = Signal(bool)

    def __init__(self, available=True):
        super().__init__()
        self.available = available
        self.shown = False
        self.messages: list[tuple[str, str]] = []

    def show(self):
        self.shown = True

    def hide(self):
        self.shown = False

    def set_widget_mode_checked(self, on):
        self.widget_checked = on

    def notify(self, title, message, ms=0):
        self.messages.append((title, message))


class FakeSecrets:
    def __init__(self):
        self.data = {}
        self.fail = False

    def has(self, p):
        return p in self.data

    def set(self, p, v):
        if self.fail:
            raise SecretError("저장 실패")
        self.data[p] = v.strip()

    def delete(self, p):
        self.data.pop(p, None)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


# ---- 알림 스케줄러 (트레이에 있어도 울린다) ------------------------------------------


def _scheduler(conn, now):
    clock = Clock(now)
    return ReminderScheduler(ScheduleRepository(conn), SettingsRepository(conn), clock=clock), clock


def test_scheduler_emits_once_for_one_time_and_recurring(qapp):
    conn = db.connect(":memory:")
    repo = ScheduleRepository(conn)
    repo.add(Schedule("회의", datetime(2026, 10, 27, 10, 0), remind_before_min=10))
    repo.add(Schedule("스탠드업", datetime(2026, 10, 1, 9, 30), recurrence="daily", remind_before_min=5))
    sched, clock = _scheduler(conn, datetime(2026, 10, 27, 9, 0))
    got = []
    sched.reminder_due.connect(lambda r: got.append((r.occurrence.title, r.fire_at.strftime("%H:%M"))))
    for minutes in range(0, 120, 1):  # 1분 간격 틱으로 9:00~10:59 를 훑는다
        clock.now = datetime(2026, 10, 27, 9, 0) + timedelta(minutes=minutes)
        sched.tick()
    assert got == [("스탠드업", "09:25"), ("회의", "09:50")]


def test_scheduler_respects_notification_toggle_without_backlog(qapp):
    conn = db.connect(":memory:")
    ScheduleRepository(conn).add(Schedule("회의", datetime(2026, 10, 27, 10, 0), remind_before_min=30))
    settings = SettingsRepository(conn)
    sched, clock = _scheduler(conn, datetime(2026, 10, 27, 9, 0))
    settings.set_bool("notifications_enabled", False)
    clock.now = datetime(2026, 10, 27, 9, 45)  # 알림 시각(9:30)이 꺼진 동안 지나갔다
    assert sched.tick() == []
    settings.set_bool("notifications_enabled", True)
    clock.now = datetime(2026, 10, 27, 9, 46)
    assert sched.tick() == []  # 다시 켜도 지난 알림이 뒤늦게 쏟아지지 않는다


def test_scheduler_survives_clock_going_backwards(qapp):
    conn = db.connect(":memory:")
    sched, clock = _scheduler(conn, datetime(2026, 10, 27, 9, 0))
    clock.now = datetime(2026, 10, 27, 8, 0)
    assert sched.tick() == []


# ---- 앱 컨트롤러: 트레이 상주, 알림 전달 ------------------------------------------------


@pytest.fixture
def controller(qapp, tmp_path):
    conn = db.connect(":memory:")
    tray = FakeTray()
    c = app_module.FlowCalendarApp(conn, tmp_path / "bk", tray=tray, register_hotkey=False)
    yield c
    c.scheduler.stop()


def test_close_hides_to_tray_and_keeps_scheduler_running(controller):
    w = controller.window
    assert w.hide_on_close and controller.tray.shown
    w.show()
    w.close()
    assert not w.isVisible()
    assert controller.scheduler._timer.isActive()  # 창이 없어도 알림 타이머는 계속 돈다


def test_open_from_tray_shows_window_again(controller):
    controller.window.close()
    controller.tray.open_requested.emit()
    assert controller.window.isVisible()


def test_reminder_is_delivered_as_toast_even_while_hidden(controller):
    controller.window.close()
    ScheduleRepository(controller.conn).add(Schedule("팀 미팅", datetime(2026, 10, 27, 10, 10), remind_before_min=10))
    controller.scheduler._last_checked = datetime(2026, 10, 27, 9, 59, 50)
    controller.scheduler._clock = Clock(datetime(2026, 10, 27, 10, 0, 20))
    controller.scheduler.tick()
    reminders = [(t, m) for t, m in controller.tray.messages if t != "Flow Calendar"]  # 첫 숨김 안내 제외
    assert [t for t, _ in reminders] == ["팀 미팅"]
    assert "10분 후" in reminders[0][1]
    assert not controller.window.isVisible()


def test_first_hide_shows_tray_hint_only_once(controller):
    for _ in range(2):
        controller.window.show()
        controller.window.close()
    hints = [m for m in controller.tray.messages if "트레이" in m[1]]
    assert len(hints) == 1


def test_without_tray_close_really_closes(qapp, tmp_path):
    c = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path, tray=FakeTray(False),
                                   register_hotkey=False)
    assert c.window.hide_on_close is False
    c.scheduler.stop()


def test_start_hidden_keeps_window_hidden_only_when_tray_available(qapp, tmp_path):
    hidden = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path, tray=FakeTray(True),
                                        start_hidden=True, register_hotkey=False)
    assert not hidden.window.isVisible()
    shown = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path, tray=FakeTray(False),
                                       start_hidden=True, register_hotkey=False)
    assert shown.window.isVisible()  # 트레이가 없으면 숨기면 찾을 수 없으니 보여 준다
    hidden.scheduler.stop()
    shown.scheduler.stop()


def test_hotkey_failure_is_kept_as_warning_not_exception(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GlobalHotkey, "register", lambda self, text: (False, "이미 사용 중"))
    c = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path, tray=FakeTray())
    assert c.hotkey_warning == "이미 사용 중"
    assert c.window.isVisible()  # 단축키가 안 돼도 앱은 정상
    c.scheduler.stop()


def test_hotkey_trigger_brings_window_forward(controller):
    controller.window.close()
    controller.hotkey.triggered.emit()
    assert controller.window.isVisible()


# ---- 헤더 / 메뉴 ------------------------------------------------------------------------


def test_menu_has_only_settings_and_calendar_view(controller):
    controller.window.open_main_menu()
    menu = controller.window._menu
    assert list(menu.items) == ["settings", "widget", "view"]
    assert "프로필" not in "".join(b.text() for b in menu.items.values())
    assert "프로젝트" not in "".join(b.text() for b in menu.items.values())
    menu.close()


def test_menu_settings_item_requests_settings(controller):
    got = []
    controller.window.settings_requested.disconnect(controller.open_settings)  # 실제 모달 창은 열지 않는다
    controller.window.settings_requested.connect(lambda: got.append(1))
    controller.window.open_main_menu()
    controller.window._menu.items["settings"].click()
    assert got == [1]


def test_view_menu_month_only_enabled(controller):
    controller.window.open_view_menu(controller.window.view_btn)
    items = controller.window._menu.items
    assert items["month"].isEnabled() and not items["week"].isEnabled() and not items["day"].isEnabled()
    controller.window._menu.close()


# ---- 설정 화면 ---------------------------------------------------------------------------


@pytest.fixture
def backend():
    conn = db.connect(":memory:")
    state = {"autostart": False, "hotkey_result": (True, ""), "exported": None, "imported": None}

    def set_autostart(v):
        state["autostart"] = v

    def apply_hotkey(text):
        state["applied"] = text
        return state["hotkey_result"]

    def export_data(path):
        state["exported"] = path

    def import_data(path):
        state["imported"] = path
        return Path("백업.db")

    b = SettingsBackend(
        settings=SettingsRepository(conn),
        secrets=FakeSecrets(),
        autostart_enabled=lambda: state["autostart"],
        set_autostart=set_autostart,
        apply_hotkey=apply_hotkey,
        export_data=export_data,
        import_data=import_data,
    )
    b.state = state
    return b


def test_settings_defaults(qapp, backend):
    d = SettingsDialog(backend)
    assert d.notify.isChecked() and not d.autostart.isChecked()
    assert d.hotkey_text() == "Ctrl+Alt+Space"
    assert d.current_provider() == "gemini"
    assert not d.delete_key_btn.isEnabled()
    assert "무료 티어" in "".join(w.text() for w in d.findChildren(type(d.key_status)))


def test_settings_save_applies_everything(qapp, backend):
    d = SettingsDialog(backend)
    d.notify.setChecked(False)
    d.autostart.setChecked(True)
    d.provider.setCurrentIndex(d.provider.findData("claude"))
    d.api_key.setText("  sk-test-123 ")
    d._on_save()
    s = backend.settings
    assert s.get_bool("notifications_enabled") is False
    assert backend.state["autostart"] is True
    assert s.get("ai_provider") == "claude"
    assert backend.secrets.data == {"claude": "sk-test-123"}
    assert d.result() == d.DialogCode.Accepted


def test_api_key_is_never_stored_in_settings_table(qapp, backend):
    d = SettingsDialog(backend)
    d.api_key.setText("SECRET-KEY-VALUE")
    d._on_save()
    rows = backend.settings.conn.execute("SELECT key, value FROM settings").fetchall()
    assert all("SECRET-KEY-VALUE" not in (v or "") for _, v in rows)


def test_empty_key_field_keeps_existing_key_and_delete_removes_it(qapp, backend):
    backend.secrets.data["gemini"] = "old"
    d = SettingsDialog(backend)
    assert d.delete_key_btn.isEnabled()
    d._on_save()
    assert backend.secrets.data == {"gemini": "old"}
    d._delete_key()
    assert backend.secrets.data == {} and not d.delete_key_btn.isEnabled()


def test_switching_provider_shows_that_providers_key_status(qapp, backend):
    backend.secrets.data["gemini"] = "k"
    d = SettingsDialog(backend)
    assert d.delete_key_btn.isEnabled()
    d.provider.setCurrentIndex(d.provider.findData("openai"))
    assert not d.delete_key_btn.isEnabled()


def test_hotkey_failure_keeps_dialog_open_and_old_setting(qapp, backend):
    backend.state["hotkey_result"] = (False, "다른 프로그램이 이미 쓰고 있습니다")
    d = SettingsDialog(backend)
    d.hotkey.setKeySequence(__import__("PySide6.QtGui", fromlist=["QKeySequence"]).QKeySequence("Ctrl+Shift+K"))
    d.notify.setChecked(False)
    d._on_save()
    assert d.result() != d.DialogCode.Accepted
    assert "이미" in d.message.text() and d.message.objectName() == "error"
    assert backend.settings.get("hotkey") == "Ctrl+Alt+Space"
    assert backend.settings.get_bool("notifications_enabled") is True  # 아무것도 저장되지 않았다


def test_hotkey_success_is_saved(qapp, backend):
    from PySide6.QtGui import QKeySequence

    d = SettingsDialog(backend)
    d.hotkey.setKeySequence(QKeySequence("Ctrl+Shift+K"))
    d._on_save()
    assert backend.state["applied"] == "Ctrl+Shift+K"
    assert backend.settings.get("hotkey") == "Ctrl+Shift+K"


def test_unchanged_hotkey_is_not_reapplied(qapp, backend):
    d = SettingsDialog(backend)
    d._on_save()
    assert "applied" not in backend.state


def test_secret_store_error_is_shown_not_raised(qapp, backend):
    backend.secrets.fail = True
    d = SettingsDialog(backend)
    d.api_key.setText("x")
    d._on_save()
    assert "저장 실패" in d.message.text() and d.result() != d.DialogCode.Accepted


def test_startup_hotkey_warning_is_shown(qapp, backend):
    d = SettingsDialog(backend, warning="이미 사용 중")
    assert "이미 사용 중" in d.message.text()


def test_export_and_import_flow(qapp, backend, monkeypatch, tmp_path):
    d = SettingsDialog(backend)
    monkeypatch.setattr(d, "_ask_save_path", lambda: str(tmp_path / "out.json"))
    d._on_export()
    assert backend.state["exported"] == tmp_path / "out.json"

    got = []
    d.data_imported.connect(lambda: got.append(1))
    monkeypatch.setattr(d, "_ask_open_path", lambda: str(tmp_path / "in.json"))
    monkeypatch.setattr(d, "_confirm_import", lambda: False)
    d._on_import()
    assert backend.state["imported"] is None and got == []  # 확인 안 하면 아무 일도 없다
    monkeypatch.setattr(d, "_confirm_import", lambda: True)
    d._on_import()
    assert backend.state["imported"] == tmp_path / "in.json" and got == [1]
    assert d.message.objectName() == "ok"


def test_import_error_message_is_shown(qapp, backend, monkeypatch, tmp_path):
    from flowcalendar.services.backup import BackupError

    def boom(path):
        raise BackupError("Flow Calendar에서 내보낸 파일이 아닙니다.")

    backend.import_data = boom
    d = SettingsDialog(backend)
    monkeypatch.setattr(d, "_ask_open_path", lambda: "x.json")
    monkeypatch.setattr(d, "_confirm_import", lambda: True)
    d._on_import()
    assert "내보낸 파일이 아닙니다" in d.message.text() and d.message.objectName() == "error"


def test_reload_all_after_import_refreshes_data_and_memo(controller):
    TodoRepository(controller.conn).add(Todo("가져온 할 일", day=date.today()))
    controller.window.memo_repo.set("가져온 메모")
    controller.window.reload_all()
    assert controller.window.memo_card.edit.content() == "가져온 메모"


def test_all_day_schedule_disables_reminder_field(qapp):
    from flowcalendar.ui.dialogs import ScheduleDialog

    d = ScheduleDialog(day=date(2026, 10, 27))
    d.reminder.setCurrentIndex(d.reminder.findData(10))
    assert d.reminder.isEnabled()
    d.all_day.setChecked(True)
    assert not d.reminder.isEnabled()
    assert d.schedule().remind_before_min is None
