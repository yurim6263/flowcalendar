from datetime import date

import pytest
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QApplication

from flowcalendar import app as app_module
from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.ui import backdrop, tokens
from flowcalendar.ui.main_window import MainWindow
from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog, saved_opacity
from tests.test_app_desktop import FakeSecrets
from tests.test_widget_mode import FakeTray


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
    w.resize(900, 600)
    w.show()
    return w


def _alpha(w) -> int:
    root = w.centralWidget()
    root._cache = None
    pix = backdrop._render(QSize(60, 60), root._opacity)
    return pix.toImage().pixelColor(30, 30).alpha()


# ---- 배경 렌더러 -----------------------------------------------------------------


def test_render_alpha_follows_opacity_and_card_color_is_untouched(qapp):
    assert backdrop._render(QSize(40, 40), 1.0).toImage().pixelColor(20, 20).alpha() == 255
    assert abs(backdrop._render(QSize(40, 40), 0.65).toImage().pixelColor(20, 20).alpha() - 166) <= 2
    assert abs(backdrop._render(QSize(40, 40), 0.5).toImage().pixelColor(20, 20).alpha() - 128) <= 2


def test_changing_opacity_invalidates_cached_backdrop(qapp):
    w = backdrop.BackdropWidget()
    w.resize(80, 80)
    w.show()
    w.grab()
    first = w._cache
    w.set_opacity(0.5)
    w.grab()
    assert w._cache is not first and w._cache_opacity == 0.5


# ---- 메인 창: 위젯 모드에서만 투명 ---------------------------------------------------------


def test_normal_window_is_always_opaque_even_if_setting_is_low(window):
    window.set_widget_opacity(65)
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.centralWidget()._opacity == 1.0 and _alpha(window) == 255


def test_widget_mode_uses_translucent_window_with_chosen_opacity(window):
    window.set_widget_opacity(65)
    window.set_widget_mode(True)
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.centralWidget()._opacity == pytest.approx(0.65)
    assert abs(_alpha(window) - 166) <= 2


def test_leaving_widget_mode_goes_back_to_opaque(window):
    window.set_widget_opacity(60)
    window.set_widget_mode(True)
    window.set_widget_mode(False)
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.centralWidget()._opacity == 1.0


def test_changing_opacity_while_in_widget_mode_applies_immediately(window):
    window.set_widget_mode(True)
    window.set_widget_opacity(80)
    assert window.centralWidget()._opacity == pytest.approx(0.8)


@pytest.mark.parametrize("given,expected", [(30, 50), (0, 50), (49, 50), (50, 50), (75, 75), (100, 100), (150, 100)])
def test_opacity_is_clamped_to_50_100(window, given, expected):
    window.set_widget_opacity(given)
    assert window.widget_opacity == expected


def test_default_is_65_percent(window):
    assert window.widget_opacity == tokens.WIDGET_OPACITY_DEFAULT == 65


# ---- 설정 화면 슬라이더 -------------------------------------------------------------------


@pytest.fixture
def backend():
    conn = db.connect(":memory:")
    return SettingsBackend(
        settings=SettingsRepository(conn), secrets=FakeSecrets(),
        autostart_enabled=lambda: False, set_autostart=lambda v: None,
        apply_hotkey=lambda t: (True, ""), export_data=lambda p: None, import_data=lambda p: p,
    )


def test_slider_range_default_and_label(qapp, backend):
    d = SettingsDialog(backend)
    assert (d.opacity.minimum(), d.opacity.maximum()) == (50, 100)
    assert d.opacity.value() == 65 and d.opacity_label.text() == "65%"


def test_slider_emits_preview_in_5_percent_steps(qapp, backend):
    d = SettingsDialog(backend)
    got = []
    d.opacity_preview.connect(got.append)
    d.opacity.setValue(72)  # 5% 단위로 맞춰진다
    assert got[-1] == 70 and d.opacity.value() == 70 and d.opacity_label.text() == "70%"
    d.opacity.setValue(100)
    assert got[-1] == 100


def test_save_persists_opacity_and_close_does_not(qapp, backend):
    d = SettingsDialog(backend)
    d.opacity.setValue(80)
    d.reject()  # 닫기: 저장하지 않는다
    assert backend.settings.get("widget_opacity") == "65"
    d2 = SettingsDialog(backend)
    d2.opacity.setValue(80)
    d2._on_save()
    assert backend.settings.get("widget_opacity") == "80"
    assert SettingsDialog(backend).opacity.value() == 80


@pytest.mark.parametrize("stored,expected", [("abc", 65), ("", 65), ("10", 50), ("500", 100), ("75", 75)])
def test_bad_stored_value_falls_back(qapp, backend, stored, expected):
    backend.settings.set("widget_opacity", stored)
    assert saved_opacity(backend.settings) == expected


# ---- 앱: 시작 시 적용, 미리보기는 취소하면 되돌린다 --------------------------------------------


def _app(tmp_path, conn):
    return app_module.FlowCalendarApp(conn, tmp_path, tray=FakeTray(), register_hotkey=False)


def test_app_applies_saved_opacity_at_startup(qapp, tmp_path):
    conn = db.connect(":memory:")
    s = SettingsRepository(conn)
    s.set("widget_opacity", "80")
    s.set_bool("widget_mode", True)
    c = _app(tmp_path, conn)
    assert c.window.widget_opacity == 80 and c.window.centralWidget()._opacity == pytest.approx(0.8)
    c.scheduler.stop()


def test_settings_preview_reverts_on_cancel_and_sticks_on_save(qapp, tmp_path, monkeypatch):
    conn = db.connect(":memory:")
    c = _app(tmp_path, conn)
    c.window.set_widget_mode(True, QRect(0, 0, 900, 600))

    def cancel(self):
        self.opacity.setValue(95)
        assert c.window.widget_opacity == 95  # 움직이는 동안 바로 보인다
        self.reject()

    monkeypatch.setattr(SettingsDialog, "exec", cancel)
    c.open_settings()
    assert c.window.widget_opacity == 65  # 닫기: 원래 값으로

    def save(self):
        self.opacity.setValue(90)
        self._on_save()

    monkeypatch.setattr(SettingsDialog, "exec", save)
    c.open_settings()
    assert c.window.widget_opacity == 90 and c.settings.get("widget_opacity") == "90"
    c.scheduler.stop()


# ---- 위젯 모드의 둥근 모서리 / 팝업 투명도 연동 ------------------------------------------------


def _render_widget(widget):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QRegion

    img = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    widget.render(img, QPoint(0, 0), QRegion(), widget.RenderFlag.DrawChildren)
    return img


def test_widget_mode_window_has_rounded_corners_and_normal_mode_does_not(window):
    root = window.centralWidget()
    window.set_widget_mode(True)
    assert root._radius == tokens.WINDOW_RADIUS
    img = _render_widget(root)
    assert img.pixelColor(1, 1).alpha() < 25  # 모서리 바깥은 비어 있다 (바탕이 비친다)
    assert img.pixelColor(root.width() // 2, 2).alpha() > 100  # 변의 중간은 채워져 있다
    window.set_widget_mode(False)
    assert root._radius == 0
    assert _render_widget(root).pixelColor(1, 1).alpha() == 255  # 일반 창은 네모(Windows 가 둥글게 표시)


def test_popups_follow_widget_opacity_only_in_widget_mode(window):
    from PySide6.QtWidgets import QWidget

    from flowcalendar.ui.dialogs import TodoDialog

    assert backdrop.popup_opacity() == 1.0
    window.set_widget_opacity(65)
    assert backdrop.popup_opacity() == 1.0  # 일반 창 모드: 팝업도 불투명
    window.set_widget_mode(True)
    assert backdrop.popup_opacity() == pytest.approx(0.65)

    dialog = TodoDialog(window)
    dialog.show()
    probe = (30, dialog.height() - 20)  # 버튼/입력칸이 없는 아래쪽 여백
    got = _render_widget(dialog).pixelColor(*probe).alpha()
    want = backdrop._render(dialog.size(), 0.65).toImage().pixelColor(*probe).alpha()
    assert 100 < got < 255 and abs(got - want) <= 3

    window.set_widget_mode(False)
    assert backdrop.popup_opacity() == 1.0
    dialog.close()
    assert isinstance(dialog, QWidget)


def test_input_fields_inside_popup_keep_their_own_background(window):
    from flowcalendar.ui.dialogs import TodoDialog

    window.set_widget_opacity(50)
    window.set_widget_mode(True)
    dialog = TodoDialog(window)
    dialog.show()
    img = _render_widget(dialog)
    field = dialog.title_edit
    center = field.mapTo(dialog, field.rect().center())
    assert img.pixelColor(center).alpha() > 200  # 입력칸은 불투명에 가까운 흰색 그대로 (배경 투명도의 영향 없음)
    window.set_widget_mode(False)


def test_slider_preview_changes_open_popup_opacity_live(window, qapp):
    window.set_widget_mode(True)
    window.set_widget_opacity(90)
    assert backdrop.popup_opacity() == pytest.approx(0.9)
    window.set_widget_opacity(50)
    assert backdrop.popup_opacity() == pytest.approx(0.5)
    window.set_widget_mode(False)


def test_new_window_resets_popup_opacity_to_opaque(qapp):
    backdrop.set_popup_opacity(0.5)  # 이전 창이 남긴 값
    conn = db.connect(":memory:")
    MainWindow(ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn))
    assert backdrop.popup_opacity() == 1.0


# ---- 위젯 모드 전환 시 네이티브 창 재생성 / 팝업의 시스템 테두리 해제 ------------------------------


def test_toggling_widget_mode_recreates_native_window(window, monkeypatch):
    """이미 만든 창에 투명 속성만 켜면 모서리가 검게 나온다(실제 화면에서 확인). 전환 때마다 창을 새로 만든다."""
    calls = []
    original = MainWindow.destroy
    monkeypatch.setattr(MainWindow, "destroy", lambda self, *a, **k: calls.append("destroy") or original(self, *a, **k))
    window.set_widget_mode(True)
    window.set_widget_mode(False)
    window.set_widget_mode(False)  # 같은 값은 아무것도 하지 않는다
    assert calls == ["destroy", "destroy"]
    assert window.isVisible()  # 다시 만들어도 보이던 창은 계속 보인다


def test_toggle_keeps_state_after_recreation(window):
    window.move(40, 50)
    before = window.geometry()
    window.set_widget_opacity(70)
    window.set_widget_mode(True, QRect(100, 120, 800, 500))
    assert window.geometry().getRect() == (100, 120, 800, 500)
    assert window.isVisible() and window.header_bar.drag_enabled
    window.set_widget_mode(False)
    assert window.geometry() == before and window.widget_opacity == 70


def test_hidden_window_stays_hidden_after_toggle_recreation(window):
    window.hide()
    window.set_widget_mode(True)
    assert not window.isVisible()


def test_system_chrome_removal_is_noop_when_unsupported():
    from flowcalendar.services import desktop_widget as dw

    assert dw.remove_system_chrome(0x1234) == {}  # offscreen: Win32 를 부르지 않는다
    assert dw.DWMWA_NCRENDERING_POLICY not in dict(dw._CHROME_OFF)  # 투명 합성을 깨뜨려서 쓰지 않는다


def test_every_popup_asks_to_drop_system_chrome_when_shown(window, monkeypatch):
    from flowcalendar.services import desktop_widget as dw
    from flowcalendar.ui.dialogs import AddChooserDialog, TodoDialog

    shown = []
    monkeypatch.setattr(dw, "remove_system_chrome", lambda hwnd: shown.append(hwnd) or {})
    for dialog in (TodoDialog(window), AddChooserDialog(window)):
        dialog.show()
        dialog.close()
    assert len(shown) == 2
