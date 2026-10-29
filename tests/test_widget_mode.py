from datetime import date

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

from flowcalendar import app as app_module
from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.ui import tokens
from flowcalendar.ui.main_window import MainWindow
from tests.test_app_desktop import FakeTray


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


@pytest.fixture
def window(qapp):
    conn = db.connect(":memory:")
    w = MainWindow(ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn),
                   today=date(2026, 10, 27))
    w.resize(1000, 700)
    w.show()
    return w


def _new_app(tmp_path, conn=None, **kw):
    return app_module.FlowCalendarApp(conn or db.connect(":memory:"), tmp_path, tray=FakeTray(),
                                      register_hotkey=False, **kw)


# ---- 창 ---------------------------------------------------------------------


def test_widget_mode_is_frameless_tool_window_with_drag_and_grip(window):
    window.set_widget_mode(True)
    flags = window.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.Tool  # 작업 표시줄과 Alt+Tab 에 나오지 않는다
    assert window.widget_mode and window.isVisible()  # 모드를 바꿔도 창은 계속 떠 있다
    assert window.header_bar.drag_enabled
    assert not window.size_grip.isHidden()


def test_back_to_normal_restores_frame_and_old_geometry(window):
    window.move(50, 60)
    before = window.geometry()
    window.set_widget_mode(True, QRect(300, 200, 900, 600))
    assert window.geometry().size().width() == 900 and window.geometry().topLeft().x() == 300
    window.set_widget_mode(False)
    assert not window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.geometry() == before
    assert not window.header_bar.drag_enabled and window.size_grip.isHidden()


def test_mode_signal_and_hidden_window_stays_hidden(window):
    got = []
    window.widget_mode_changed.connect(got.append)
    window.hide()
    window.set_widget_mode(True)
    window.set_widget_mode(True)  # 같은 값은 무시
    assert got == [True] and not window.isVisible()


def test_geometry_signal_uses_xywh_format(window):
    got = []
    window.widget_geometry_changed.connect(got.append)
    window.set_widget_mode(True, QRect(10, 20, 900, 600))
    window._emit_geometry()
    assert got[-1] == "10,20,900,600"


def test_geometry_not_reported_in_normal_mode(window):
    got = []
    window.widget_geometry_changed.connect(got.append)
    window.move(5, 5)
    window._schedule_geometry()
    assert not window._geometry_timer.isActive() and got == []


def test_minimize_in_widget_mode_is_undone_but_normal_mode_is_not(window, qapp):
    window.showMinimized()
    qapp.processEvents()
    assert window.isMinimized()  # 일반 모드에서는 평소처럼 최소화된다
    window.showNormal()
    window.set_widget_mode(True)
    window.showMinimized()
    for _ in range(5):
        qapp.processEvents()
    assert not window.isMinimized()  # 위젯은 바탕화면 보기 등으로 사라지지 않는다


def test_menu_offers_toggle_and_hide_only_in_widget_mode(window):
    window.open_main_menu()
    assert "켜기" in window._menu.items["widget"].text() and "hide" not in window._menu.items
    window._menu.close()
    window.set_widget_mode(True)
    window.open_main_menu()
    assert "끄기" in window._menu.items["widget"].text() and "hide" in window._menu.items
    window._menu.items["widget"].click()
    assert not window.widget_mode
    window._menu.close()


def test_bring_forward_marks_temporary_raise_only_when_pinned(window):
    window.set_widget_mode(True)
    window.bring_forward()  # offscreen 에서는 고정(pin)이 없어 아무 일 없이 보이기만 한다
    assert window.isVisible() and window._raised is False


# ---- 앱 연결: 설정 저장 / 시작 / 트레이 -----------------------------------------------


def test_default_is_normal_window(qapp, tmp_path):
    c = _new_app(tmp_path)
    assert not c.window.widget_mode
    c.scheduler.stop()


def test_turning_on_saves_setting_and_tray_check(qapp, tmp_path):
    c = _new_app(tmp_path)
    c.window.set_widget_mode(True)
    assert c.settings.get_bool("widget_mode") is True and c.tray.widget_checked is True
    c.window.set_widget_mode(False)
    assert c.settings.get_bool("widget_mode") is False and c.tray.widget_checked is False
    c.scheduler.stop()


def test_tray_toggle_switches_window_mode(qapp, tmp_path):
    c = _new_app(tmp_path)
    c.tray.widget_mode_toggled.emit(True)
    assert c.window.widget_mode
    c.tray.widget_mode_toggled.emit(False)
    assert not c.window.widget_mode
    c.scheduler.stop()


def test_starts_as_widget_with_saved_geometry_even_when_launched_hidden(qapp, tmp_path):
    conn = db.connect(":memory:")
    settings = SettingsRepository(conn)
    settings.set_bool("widget_mode", True)
    settings.set("widget_geometry", "40,50,980,640")
    c = _new_app(tmp_path, conn, start_hidden=True)  # 자동 실행(--tray)으로 켜졌어도
    assert c.window.widget_mode and c.window.isVisible()  # 위젯은 바탕화면에 바로 보여야 한다
    assert (c.window.x(), c.window.y(), c.window.width(), c.window.height()) == (40, 50, 980, 640)
    assert c.tray.widget_checked is True
    c.scheduler.stop()


def test_geometry_changes_are_persisted(qapp, tmp_path):
    c = _new_app(tmp_path)
    c.window.set_widget_mode(True, QRect(100, 120, 900, 600))
    c.window._emit_geometry()
    assert c.settings.get("widget_geometry") == "100,120,900,600"
    c.scheduler.stop()


@pytest.mark.parametrize("saved", ["", "abc", "1,2,3", "99999,99999,900,600", "-5000,-5000,900,600"])
def test_unusable_saved_geometry_is_discarded(qapp, tmp_path, saved):
    conn = db.connect(":memory:")
    SettingsRepository(conn).set("widget_geometry", saved)
    c = _new_app(tmp_path, conn)
    assert c._saved_widget_geometry() is None  # 모니터를 뺀 경우 등: 화면 밖에 갇히지 않는다
    c.scheduler.stop()


def test_closing_widget_hides_to_tray_and_open_shows_it_again(qapp, tmp_path):
    c = _new_app(tmp_path)
    c.window.set_widget_mode(True)
    c.window.close()
    assert not c.window.isVisible() and c.window.widget_mode  # 모드는 유지된 채 숨는다
    assert c.scheduler._timer.isActive()
    c.tray.open_requested.emit()
    assert c.window.isVisible()
    c.scheduler.stop()
