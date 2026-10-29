from datetime import date, datetime

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule
from flowcalendar.ui import main_window, tokens
from flowcalendar.ui.dialogs import (
    AddChooserDialog,
    DatePickDialog,
    DayListDialog,
    ScheduleDialog,
    TodoDialog,
)
from flowcalendar.ui.main_window import MainWindow
from flowcalendar.ui.message_dialog import ChoiceDialog, confirm
from flowcalendar.ui.widgets import RoseComboBox, RoseDateEdit

TODAY = date(2026, 10, 27)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


def _all_dialogs(window):
    return [
        AddChooserDialog(window),
        TodoDialog(window, day=TODAY),
        TodoDialog(window),
        DatePickDialog(window, start=TODAY),
        ScheduleDialog(window, day=TODAY),
        DayListDialog(window, TODAY, [], []),
        ChoiceDialog(window, "제목", "본문", [("ok", "확인", "primary")]),
    ]


@pytest.fixture
def window(app):
    conn = db.connect(":memory:")
    w = MainWindow(ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn), today=TODAY)
    w.show()
    return w


# ---- 테두리 없는 팝업 -------------------------------------------------------------


def test_every_popup_is_frameless_and_translucent_for_rounded_corners(window):
    for dialog in _all_dialogs(window):
        assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint, type(dialog).__name__
        assert dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_close_button_rejects_and_sits_in_top_right_corner(window):
    for dialog in _all_dialogs(window):
        dialog.show()
        btn = dialog.close_btn
        assert btn.x() + btn.width() <= dialog.width() and btn.y() < 20
        btn.click()
        assert dialog.result() == dialog.DialogCode.Rejected
        assert not dialog.isVisible()


def test_popups_carry_their_own_heading_since_title_bar_is_gone(window):
    from PySide6.QtWidgets import QLabel

    def headings(d):
        return [w.text() for w in d.findChildren(QLabel) if w.objectName() == "dialogTitle"]

    assert headings(AddChooserDialog(window)) == ["무엇을 추가할까요?"]
    assert headings(ScheduleDialog(window, day=TODAY)) == ["일정 추가"]
    assert headings(DayListDialog(window, TODAY, [], [])) == ["10월 27일 (화)"]
    assert headings(TodoDialog(window, day=TODAY)) == ["Daily To-Do"]
    assert headings(TodoDialog(window)) == ["Quick To-Do"]


def test_schedule_dialog_edit_heading_and_save_still_work(window):
    sid = window.repo.add(Schedule("회의", datetime(2026, 10, 27, 10, 0), datetime(2026, 10, 27, 11, 0)))
    occ = window.repo.list_occurrences(TODAY, TODAY)[0]
    dialog = ScheduleDialog(window, occurrence=occ)
    dialog.title_edit.setText("수정된 회의")
    dialog._on_save()
    assert dialog.action == "save" and dialog.schedule().title == "수정된 회의" and sid


# ---- 날짜 목록 팝업: 제목이 생겨도 항목 영역은 그대로 --------------------------------------


def test_day_list_items_layout_is_separate_from_heading(window):
    d = DayListDialog(window, TODAY, [], [])
    assert d._layout.count() == 1  # "항목이 없습니다"만 있다 (제목은 별도)
    d.set_items([], [])
    assert d._layout.count() == 1


def _spin_option(edit):
    from PySide6.QtWidgets import QStyleOptionSpinBox

    option = QStyleOptionSpinBox()
    option.initFrom(edit)
    return option


# ---- 시간/드롭다운 입력칸 ------------------------------------------------------------


def test_time_edits_have_no_arrows_but_text_stays_visible_and_keys_still_work(window):
    d = ScheduleDialog(window, day=TODAY)
    d.show()
    for edit in (d.start_edit, d.end_edit):
        # 스타일시트와 NoButtons 를 같이 쓰면 글자 영역이 1px 로 줄어드는 문제가 있었다 (회귀 방지)
        assert edit.lineEdit().width() >= edit.width() - 20, edit.lineEdit().width()
        assert edit.lineEdit().text() and "휠" in edit.toolTip()
        assert edit.style().subControlRect(
            edit.style().ComplexControl.CC_SpinBox, _spin_option(edit), edit.style().SubControl.SC_SpinBoxUp, edit
        ).width() == 0
    before = d.start_edit.time()
    d.start_edit.stepBy(1)  # ↑ 키와 휠이 부르는 동작
    assert d.start_edit.time() != before


def test_dropdowns_use_custom_painted_widgets(window):
    d = ScheduleDialog(window, day=TODAY)
    assert isinstance(d.reminder, RoseComboBox) and isinstance(d.recurrence, RoseComboBox)
    assert isinstance(d.date_edit, RoseDateEdit) and d.date_edit.calendarPopup()
    assert isinstance(TodoDialog(window).priority, RoseComboBox)


def test_dropdown_paints_chevron_pixels_at_right_edge(window):
    combo = RoseComboBox()
    combo.addItem("보통")
    combo.resize(200, 36)
    combo.show()
    image = combo.grab().toImage()
    # 오른쪽 끝 30px 영역에 글자/배경과 다른 어두운 선(화살표)이 있어야 한다
    dark = [
        (x, y) for x in range(image.width() - 30, image.width()) for y in range(image.height())
        if image.pixelColor(x, y).lightness() < 190
    ]
    assert dark, "화살표가 그려지지 않았다"
    assert all(x < image.width() - 4 for x, _ in dark)  # 오른쪽 가장자리까지 번지지 않는다


# ---- 확인/선택 팝업 (QMessageBox 대체) -------------------------------------------------


def test_choice_dialog_returns_clicked_key_and_none_when_closed(window):
    d = ChoiceDialog(window, "t", "b", [("a", "A", "normal"), ("b", "B", "primary")])
    d.buttons["b"].click()
    assert d.choice == "b" and d.result() == d.DialogCode.Accepted
    d2 = ChoiceDialog(window, "t", "b", [("a", "A", "normal")])
    d2.show()
    d2.close_btn.click()
    assert d2.choice is None


def test_primary_button_is_default_so_enter_confirms(window):
    d = ChoiceDialog(window, "t", "b", [("no", "취소", "normal"), ("yes", "삭제", "primary")])
    assert d.buttons["yes"].isDefault() and not d.buttons["no"].isDefault()


def test_confirm_helper(window, monkeypatch):
    seen = {}

    def fake_exec(self):
        seen["buttons"] = list(self.buttons)
        self.buttons["yes"].click()

    monkeypatch.setattr(ChoiceDialog, "exec", fake_exec)
    assert confirm(window, "제목", "본문", yes="삭제", danger=True) is True
    assert seen["buttons"] == ["no", "yes"]


def test_dangerous_confirm_has_no_default_button(window):
    d = ChoiceDialog(window, "t", "b", [("no", "취소", "normal"), ("yes", "삭제", "danger")])
    assert not any(b.isDefault() for b in d.buttons.values())  # Enter 로 실수로 삭제되지 않게


@pytest.mark.parametrize("picked,expected", [("this", "this"), ("following", "following"),
                                             ("cancel", None), (None, None)])
def test_scope_question_maps_choices(window, monkeypatch, picked, expected):
    monkeypatch.setattr(main_window, "ask_choice", lambda *a, **k: picked)
    assert window._ask_scope("삭제") == expected


def test_delete_confirmation_uses_custom_dialog(window, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window, "confirm", lambda *a, **k: calls.append((a, k)) or True)
    assert window._confirm_delete("회의") is True
    assert "회의" in calls[0][0][2] and calls[0][1]["danger"] is True
