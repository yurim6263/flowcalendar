"""일정을 끌어서 다른 날로 옮기기 / Ctrl 로 복사하기 / 수정 팝업의 복제."""

import json
from datetime import date, datetime

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDrag, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule
from flowcalendar.ui import tokens
from flowcalendar.ui.calendar_view import OCCURRENCE_MIME, CalendarGrid
from flowcalendar.ui.dialogs import ScheduleDialog
from flowcalendar.ui.main_window import MainWindow

TODAY = date(2026, 10, 28)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


@pytest.fixture
def window(qapp):
    conn = db.connect(":memory:")
    w = MainWindow(ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn), today=TODAY)
    w.resize(1280, 820)
    w.show()
    qapp.processEvents()
    return w


def _add(window, title, start, end=None, **kw):
    schedule = Schedule(title, start, end, **kw)
    schedule.id = window.repo.add(schedule)
    window.refresh()
    return schedule.id


def _cell(window, day):
    return next(c for c in window.grid._cells if c.day == day and not c.isHidden())


def _titles_on(window, day):
    return [o.title for o in window.repo.list_occurrences(day, day)]


def _clicks(window):
    """칩 클릭을 수정 팝업 대신 목록에 모은다 (진짜 팝업은 모달이라 테스트가 멈춘다)."""
    window.grid.occurrence_clicked.disconnect(window.on_edit)
    clicked = []
    window.grid.occurrence_clicked.connect(clicked.append)
    return clicked


def _drop(grid, payload, target_cell, copy=False):
    """grid 에 끌어다 놓는 동작을 그대로 보낸다."""
    mime = QMimeData()
    mime.setData(OCCURRENCE_MIME, json.dumps(payload).encode("utf-8"))
    pos = QPointF(target_cell.geometry().center())
    action = Qt.DropAction.CopyAction if copy else Qt.DropAction.MoveAction
    event = QDropEvent(pos, action, mime, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.ControlModifier if copy else Qt.KeyboardModifier.NoModifier)
    grid.dropEvent(event)
    return event


# ---- 끌기 시작 -------------------------------------------------------------------------


def test_dragging_a_chip_starts_a_drag_with_id_date_and_grabbed_day(window, monkeypatch):
    sid = _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    chip = next(c for c in _cell(window, date(2026, 10, 29))._chips if c is not None)
    seen = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: seen.append(json.loads(
        bytes(self.mimeData().data(OCCURRENCE_MIME)).decode("utf-8"))) or Qt.DropAction.IgnoreAction)
    clicked = _clicks(window)
    QTest.mousePress(chip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 8))
    QTest.mouseMove(chip, QPoint(40, 40))
    QTest.mouseRelease(chip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 40))
    assert seen == [{"id": sid, "date": "2026-10-29", "press": "2026-10-29"}]
    assert clicked == []  # 끌었다 놓은 것은 클릭(수정 팝업 열기)이 아니다


def test_plain_click_still_opens(window):
    _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    chip = next(c for c in _cell(window, date(2026, 10, 29))._chips if c is not None)
    clicked = _clicks(window)
    chip.click()
    assert len(clicked) == 1


def test_dragging_a_multiday_bar_records_which_day_was_grabbed(window, monkeypatch):
    sid = _add(window, "출장", datetime(2026, 10, 26), datetime(2026, 10, 28), all_day=True)
    bar = window.grid.bars()[0]
    seen = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: seen.append(json.loads(
        bytes(self.mimeData().data(OCCURRENCE_MIME)).decode("utf-8"))) or Qt.DropAction.IgnoreAction)
    cell28 = _cell(window, date(2026, 10, 28))
    grab = QPoint(cell28.x() + cell28.width() // 2 - bar.x(), 8)  # 28일 칸 안쪽을 잡는다
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grab)
    QTest.mouseMove(bar, grab + QPoint(30, 30))
    assert seen == [{"id": sid, "date": "2026-10-26", "press": "2026-10-28"}]


# ---- 놓기 ------------------------------------------------------------------------------


def test_drop_emits_days_moved_and_copy_flag(window):
    sid = _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    got = []
    window.grid.occurrence_dropped.connect(lambda *a: got.append(a))
    event = _drop(window.grid, {"id": sid, "date": "2026-10-29", "press": "2026-10-29"}, _cell(window, date(2026, 10, 31)))
    assert got == [(sid, date(2026, 10, 29), 2, False)] and event.isAccepted()
    _drop(window.grid, {"id": sid, "date": "2026-10-29", "press": "2026-10-29"}, _cell(window, date(2026, 10, 27)), copy=True)
    assert got[-1] == (sid, date(2026, 10, 29), -2, True)


def test_drop_ignores_garbage_payload(window):
    got = []
    window.grid.occurrence_dropped.connect(lambda *a: got.append(a))
    _drop(window.grid, {"id": "x", "date": "엉터리", "press": None}, _cell(window, date(2026, 10, 31)))
    assert got == []


def test_drag_highlights_the_target_day_and_clears(window):
    cell = _cell(window, date(2026, 10, 30))
    window.grid._highlight_drop(cell)
    assert cell.property("hover") is True
    window.grid._highlight_drop(None)
    assert cell.property("hover") is False


# ---- 옮기기 · 복사 · 되돌리기 ----------------------------------------------------------------


def test_move_changes_date_keeps_time_and_length_and_can_be_undone(window):
    sid = _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11, 30), color="pink")
    window.on_occurrence_dropped(sid, date(2026, 10, 29), 2, False)
    moved = window.repo.get(sid)
    assert (moved.start_at, moved.end_at, moved.color) == (
        datetime(2026, 10, 31, 10), datetime(2026, 10, 31, 11, 30), "pink")
    assert _titles_on(window, date(2026, 10, 29)) == []
    _press_undo(window)
    assert window.repo.get(sid).start_at == datetime(2026, 10, 29, 10)  # 되돌리면 원래 자리


def test_move_multiday_event_shifts_the_whole_span(window):
    sid = _add(window, "출장", datetime(2026, 10, 26), datetime(2026, 10, 28), all_day=True)
    window.on_occurrence_dropped(sid, date(2026, 10, 26), 3, False)
    moved = window.repo.get(sid)
    assert (moved.start_at, moved.end_at) == (datetime(2026, 10, 29), datetime(2026, 10, 31))


def test_copy_creates_new_schedule_and_keeps_original(window):
    sid = _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    window.on_occurrence_dropped(sid, date(2026, 10, 29), 1, True)
    assert _titles_on(window, date(2026, 10, 29)) == ["회의"]
    assert _titles_on(window, date(2026, 10, 30)) == ["회의"]
    assert window.repo.get(sid).start_at == datetime(2026, 10, 29, 10)


def test_moving_one_occurrence_of_a_recurring_event_leaves_the_rest(window):
    sid = _add(window, "스탠드업", datetime(2026, 10, 26, 9), datetime(2026, 10, 26, 9, 15), recurrence="daily")
    window.on_occurrence_dropped(sid, date(2026, 10, 28), 2, False)  # 28일 회차를 30일로
    assert _titles_on(window, date(2026, 10, 28)) == []
    assert _titles_on(window, date(2026, 10, 30)) == ["스탠드업", "스탠드업"]  # 원래 30일 회차 + 옮겨 온 것
    assert _titles_on(window, date(2026, 10, 27)) == ["스탠드업"]
    assert window.repo.get(sid).recurrence == "daily"


def test_undo_of_recurring_move_restores_the_original_occurrence(window):
    sid = _add(window, "스탠드업", datetime(2026, 10, 26, 9), datetime(2026, 10, 26, 9, 15), recurrence="daily")
    window.on_occurrence_dropped(sid, date(2026, 10, 28), 2, False)
    _press_undo(window)
    assert _titles_on(window, date(2026, 10, 28)) == ["스탠드업"]
    assert _titles_on(window, date(2026, 10, 30)) == ["스탠드업"]


def _press_undo(window):
    undo = next(b for b in window._toast.findChildren(QPushButton) if b.objectName() == "undo")
    undo.click()


def test_undo_of_plain_move_and_copy(window):
    sid = _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    window.on_occurrence_dropped(sid, date(2026, 10, 29), 2, False)
    _press_undo(window)
    assert window.repo.get(sid).start_at == datetime(2026, 10, 29, 10)
    window.on_occurrence_dropped(sid, date(2026, 10, 29), 1, True)
    assert len(window.repo.list_occurrences(date(2026, 10, 1), date(2026, 10, 31))) == 2
    _press_undo(window)
    assert len(window.repo.list_occurrences(date(2026, 10, 1), date(2026, 10, 31))) == 1


def test_dropping_on_same_day_does_nothing(window):
    sid = _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    window.on_occurrence_dropped(sid, date(2026, 10, 29), 0, False)
    assert window.repo.get(sid).start_at == datetime(2026, 10, 29, 10)
    window.on_occurrence_dropped(99999, date(2026, 10, 29), 1, False)  # 그 사이 지워진 일정


# ---- 복제 버튼 -------------------------------------------------------------------------


def test_edit_dialog_has_duplicate_button_only_when_editing(window):
    _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    occ = window.repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 29))[0]
    editing = ScheduleDialog(window, occurrence=occ)
    assert any(b.text() == "복제" for b in editing.findChildren(type(editing.close_btn)))
    adding = ScheduleDialog(window, day=date(2026, 10, 29))
    assert not any(b.text() == "복제" for b in adding.findChildren(type(adding.close_btn)))


def test_duplicate_opens_prefilled_new_schedule_and_saves_copy(window, monkeypatch):
    sid = _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11), color="green",
               remind_before_min=10)
    occ = window.repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 29))[0]
    seen = {}

    def fake_exec(self):
        seen["title"], seen["editing"] = self.title_edit.text(), self.occurrence is not None
        self.date_edit.setDate(self.date_edit.date().addDays(7))  # 사용자가 날짜를 고른다
        self.action = "save"
        return self.DialogCode.Accepted

    monkeypatch.setattr(ScheduleDialog, "exec", fake_exec)
    window._duplicate_schedule(occ)
    assert seen == {"title": "회의", "editing": False}  # 새 일정 팝업이고 내용이 채워져 있다
    copies = window.repo.list_occurrences(date(2026, 11, 5), date(2026, 11, 5))
    assert [(o.title, o.color, o.schedule.remind_before_min) for o in copies] == [("회의", "green", 10)]
    assert window.repo.get(sid).start_at == datetime(2026, 10, 29, 10)  # 원본은 그대로


def test_duplicate_cancel_adds_nothing(window, monkeypatch):
    _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    occ = window.repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 29))[0]
    monkeypatch.setattr(ScheduleDialog, "exec", lambda self: self.DialogCode.Rejected)
    window._duplicate_schedule(occ)
    assert len(window.repo.list_occurrences(date(2026, 10, 1), date(2026, 12, 31))) == 1


def test_on_edit_routes_duplicate_action(window, monkeypatch):
    _add(window, "회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11))
    occ = window.repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 29))[0]
    called = []

    def fake_exec(self):
        self.action = "duplicate"
        return self.DialogCode.Accepted

    monkeypatch.setattr(ScheduleDialog, "exec", fake_exec)
    monkeypatch.setattr(MainWindow, "_duplicate_schedule", lambda self, o: called.append(o))
    window.on_edit(occ)
    assert called == [occ]
