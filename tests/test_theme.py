"""테마 선택: 토큰, 설정 저장, 바로 적용."""

from datetime import date, datetime

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from flowcalendar import app as app_module
from flowcalendar.data import db
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.domain.models import Schedule
from flowcalendar.ui import backdrop, tokens
from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog, saved_theme
from tests.test_app_desktop import FakeSecrets, FakeTray


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


@pytest.fixture
def controller(qapp, tmp_path):
    c = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path / "bk", tray=FakeTray(),
                                   register_hotkey=False)
    yield c
    c.scheduler.stop()


def _backend(conn):
    return SettingsBackend(
        settings=SettingsRepository(conn), secrets=FakeSecrets(), autostart_enabled=lambda: False,
        set_autostart=lambda on: None, apply_hotkey=lambda text: (True, ""),
        export_data=lambda path: None, import_data=lambda path: path,
    )


# ---- 토큰 -----------------------------------------------------------------------


def test_requested_themes_exist_in_order():
    assert [label for _, label in tokens.theme_names()] == [
        "분홍", "보라", "노랑", "하늘", "연두", "회색", "흰색", "검정",
        "그라데이션 · 노을", "그라데이션 · 라벤더", "그라데이션 · 민트",
    ]


def test_every_theme_defines_all_colors_used_by_the_stylesheet():
    for key in tokens.THEMES:
        tokens.apply(key)  # 값이 빠졌으면 NameError / KeyError 가 난다
        assert tokens.CURRENT == key
        for name in ("TEXT", "ACCENT", "BG_TOP", "SOLID", "GLASS", "GRID_LINE", "FIELD_BORDER", "EDGE"):
            assert getattr(tokens, name) is not None
        assert set(tokens.CHIP) == {"yellow", "pink", "green", "blue", "purple"}


def test_pink_keeps_the_original_colors():
    tokens.apply("pink")
    assert (tokens.TEXT, tokens.ACCENT, tokens.BG_TOP, tokens.BG_BOTTOM) == ("#4A3238", "#C2506A", "#FDF2F4", "#F7E1E7")
    assert tokens.GLASS == "rgba(255,255,255,0.55)"
    assert tokens.CHIP["yellow"] == "#FFE7A8"


def test_unknown_theme_falls_back_to_pink():
    tokens.apply("black")
    tokens.apply("없는 테마")
    assert tokens.CURRENT == "pink"


def test_switching_back_restores_light_values_after_dark():
    tokens.apply("black")
    assert tokens.DARK and tokens.SOLID != "white"
    tokens.apply("purple")
    assert not tokens.DARK and tokens.SOLID == "white" and tokens.FILL_SCALE == 1.0
    assert tokens.GRID_LINE.startswith("rgba(")  # 어두운 테마의 고정값이 남지 않는다
    assert tokens.GRID_LINE != "rgba(255, 255, 255, 0.07)"


def test_black_is_dark_with_light_text():
    tokens.apply("black")
    lum = lambda c: QColor(c).lightnessF()  # noqa: E731
    assert lum(tokens.TEXT) > 0.8 and lum(tokens.BG_TOP) < 0.2
    assert lum(tokens.CHIP["yellow"]) < 0.4  # 일정 색도 어두운 배경에 맞게 눌러 둔다


def test_gray_is_darker_than_before_and_than_white():
    tokens.apply("gray")
    gray = QColor(tokens.BG_TOP).lightnessF()
    tokens.apply("white")
    assert gray < QColor(tokens.BG_TOP).lightnessF() - 0.1
    assert gray < 0.88  # 처음 안(#F6F6F7, 약 0.96)보다 확실히 어둡다


def test_text_stays_readable_on_every_theme():
    for key in tokens.THEMES:
        tokens.apply(key)
        bg = QColor(tokens.BG_BOTTOM).lightnessF()
        text = QColor(tokens.TEXT).lightnessF()
        assert abs(text - bg) > 0.45, key


# ---- 설정 저장 · 화면 ------------------------------------------------------------


def test_theme_setting_default_and_validation():
    s = SettingsRepository(db.connect(":memory:"))
    assert saved_theme(s) == "pink"
    s.set("theme", "black")
    assert saved_theme(s) == "black"
    s.set("theme", "엉뚱한 값")
    assert saved_theme(s) == "pink"


def test_settings_dialog_lists_all_themes_and_selects_saved_one(qapp):
    conn = db.connect(":memory:")
    SettingsRepository(conn).set("theme", "sky")
    d = SettingsDialog(_backend(conn))
    assert list(d.theme_swatches) == [k for k, _ in tokens.theme_names()]
    assert d.selected_theme() == "sky"
    assert "하늘" in d.theme_name.text()


def test_clicking_a_theme_previews_and_saving_stores_it(qapp):
    conn = db.connect(":memory:")
    d = SettingsDialog(_backend(conn))
    seen = []
    d.theme_preview.connect(seen.append)
    d.theme_swatches["black"].click()
    assert seen == ["black"] and d.selected_theme() == "black"
    assert SettingsRepository(conn).get("theme") == "pink"  # 저장 전에는 그대로
    d._on_save()
    assert SettingsRepository(conn).get("theme") == "black"


def test_swatches_render_for_every_theme(qapp):
    conn = db.connect(":memory:")
    d = SettingsDialog(_backend(conn))
    d.show()
    for swatch in d.theme_swatches.values():
        assert not swatch.grab().isNull()


# ---- 바로 적용 ------------------------------------------------------------------


def test_app_starts_with_saved_theme(qapp, tmp_path):
    conn = db.connect(":memory:")
    SettingsRepository(conn).set("theme", "purple")
    c = app_module.FlowCalendarApp(conn, tmp_path / "bk", tray=FakeTray(), register_hotkey=False)
    try:
        assert tokens.CURRENT == "purple"
        assert tokens.ACCENT in QApplication.instance().styleSheet()
    finally:
        c.scheduler.stop()


def test_apply_theme_updates_stylesheet_calendar_and_backdrop(controller, qapp):
    controller.schedules.add(Schedule("회의", datetime.now().replace(hour=10, minute=0),
                                      datetime.now().replace(hour=11, minute=0), color="yellow"))
    controller.window.show()  # 칸이 실제 크기를 가져야 일정 칩이 만들어진다
    qapp.processEvents()
    controller.window.refresh()
    root = controller.window.centralWidget()
    root._cache = None
    before = backdrop._render(QSize(300, 200)).toImage().pixelColor(5, 5).name()

    controller.apply_theme("black")
    assert QApplication.instance().styleSheet() == tokens.STYLESHEET
    assert tokens.ACCENT in tokens.STYLESHEET
    assert backdrop._render(QSize(300, 200)).toImage().pixelColor(5, 5).name() != before
    assert root._cache is None  # 배경 캐시를 버렸다
    chips = [c for cell in controller.window.grid._cells for c in cell._chips if c is not None]
    assert chips and tokens.CHIP["yellow"] in chips[0].styleSheet()  # 일정 칩이 새 색으로 다시 만들어졌다
    assert tokens.SATURDAY in controller.window.grid._saturday.styleSheet()


def test_closing_settings_without_saving_restores_saved_theme(controller, monkeypatch):
    controller.settings.set("theme", "sky")
    controller.apply_theme("sky")

    def fake_exec(self):
        self.theme_swatches["black"].click()  # 미리보기만 하고 저장 없이 닫는다
        assert tokens.CURRENT == "black"
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    controller.open_settings()
    assert tokens.CURRENT == "sky"


def test_saving_in_settings_keeps_new_theme(controller, monkeypatch):
    def fake_exec(self):
        self.theme_swatches["lime"].click()
        self._on_save()
        return 1

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    controller.open_settings()
    assert tokens.CURRENT == "lime" and controller.settings.get("theme") == "lime"


def test_app_icon_does_not_change_with_theme(qapp):
    from flowcalendar.ui.icons import app_icon

    tokens.apply("pink")
    a = app_icon().pixmap(64, 64).toImage()
    tokens.apply("black")
    assert app_icon().pixmap(64, 64).toImage() == a


# ---- 휠로 값이 바뀌지 않는다 (투명도 슬라이더, 콤보박스) ------------------------------


def _wheel(widget, delta=120):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    return event


def test_wheel_does_not_change_opacity_or_ai_provider(qapp):
    d = SettingsDialog(_backend(db.connect(":memory:")))
    d.show()
    opacity, provider = d.opacity.value(), d.provider.currentIndex()
    assert not _wheel(d.opacity).isAccepted() and not _wheel(d.opacity, -120).isAccepted()
    assert not _wheel(d.provider).isAccepted() and not _wheel(d.provider, -120).isAccepted()
    assert (d.opacity.value(), d.provider.currentIndex()) == (opacity, provider)


def test_mouse_and_keys_still_change_opacity_and_provider(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    d = SettingsDialog(_backend(db.connect(":memory:")))
    d.show()
    d.opacity.setFocus()
    before = d.opacity.value()
    QTest.keyClick(d.opacity, Qt.Key.Key_Right)
    assert d.opacity.value() > before
    d.provider.setCurrentIndex(1)  # 목록에서 고르는 것과 같은 경로
    assert d.provider.currentIndex() == 1


# ---- 머리글 버튼: 순서와 높이 ---------------------------------------------------------


def test_header_order_and_equal_heights(qapp):
    from tests.test_ai_auto import make_env

    w = make_env().window
    w.resize(1100, 300)
    w.show()
    w.ai_btn.show()
    qapp.processEvents()
    left = sorted([w.prev_btn, w.today_btn, w.next_btn], key=lambda b: b.x())
    assert left == [w.prev_btn, w.today_btn, w.next_btn]  # < 오늘 > 순서
    buttons = [w.prev_btn, w.today_btn, w.next_btn, w.ai_btn, w.view_btn, w.menu_btn]
    assert len({b.height() for b in buttons}) == 1 and len({b.y() for b in buttons}) == 1


def test_month_arrows_are_vertically_centered(qapp):
    from tests.test_ai_auto import make_env

    w = make_env().window
    w.show()
    qapp.processEvents()
    for button in (w.prev_btn, w.next_btn):
        img = button.grab().toImage()
        rows = [y for y in range(img.height()) for x in range(img.width())
                if img.pixelColor(x, y).lightnessF() < 0.45]
        assert abs(min(rows) - (img.height() - 1 - max(rows))) <= 1


def test_month_buttons_still_change_month(qapp):
    from tests.test_ai_auto import make_env

    w = make_env().window
    month = (w.year, w.month)
    w.next_btn.click()
    assert (w.year, w.month) != month
    w.prev_btn.click()
    assert (w.year, w.month) == month


# ---- 포커스 표시: 키보드(Tab)로만 ---------------------------------------------------------


def test_buttons_take_focus_from_keyboard_only_and_stylesheet_shows_it(qapp):
    from PySide6.QtCore import Qt as QtNS

    from tests.test_ai_auto import make_env

    w = make_env().window
    w.show()
    qapp.processEvents()
    for button in (w.prev_btn, w.today_btn, w.next_btn, w.search_btn, w.menu_btn, w.view_btn):
        assert button.focusPolicy() == QtNS.FocusPolicy.TabFocus  # 클릭만으로는 포커스 표시가 남지 않는다
    assert "QPushButton:focus" in tokens.STYLESHEET
    d = SettingsDialog(_backend(db.connect(":memory:")))
    d.show()
    assert d.models_btn.focusPolicy() == QtNS.FocusPolicy.TabFocus


def test_calendar_chips_and_cell_buttons_are_skipped_by_tab(qapp):
    from datetime import datetime as dt

    from tests.test_ai_auto import make_env

    e = make_env()
    e.window.repo.add(Schedule("회의", dt(2026, 10, 27, 10), dt(2026, 10, 27, 11)))
    e.window.show()
    e.window.refresh()
    qapp.processEvents()
    cell = next(c for c in e.window.grid._cells if c.day == date(2026, 10, 27) and not c.isHidden())
    assert all(c.focusPolicy().name == "NoFocus" for c in cell._chips if c is not None)
    assert cell.plus.focusPolicy().name == "NoFocus" and cell.more.focusPolicy().name == "NoFocus"


def test_first_button_does_not_show_focus_ring_at_startup(qapp):
    from tests.test_ai_auto import make_env

    w = make_env().window
    w.show()
    w.activateWindow()
    qapp.processEvents()
    assert not w.prev_btn.hasFocus()  # 처음부터 이전 달 버튼에 포커스 표시가 붙어 있지 않다
