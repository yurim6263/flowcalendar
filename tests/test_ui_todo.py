from datetime import date, datetime

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import PRIORITY_HIGH, Schedule, Todo
from flowcalendar.ui import main_window, tokens
from flowcalendar.ui.main_window import MainWindow
from flowcalendar.ui.side_panel import BULLET_INDENT, MemoEdit
from flowcalendar.ui.todo_row import TodoRow

TODAY = date(2026, 10, 27)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


@pytest.fixture
def window(app):
    conn = db.connect(":memory:")
    w = MainWindow(ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn), today=TODAY)
    w.resize(1280, 820)
    w.show()
    return w


def _cell(window, day):
    return next(c for c in window.grid._cells if c.day == day and not c.isHidden())


def _titles(rows):
    return [r.todo.title for r in rows if not r.isHidden()]


# ---- 날짜 셀 ---------------------------------------------------------------


def test_daily_todo_is_shown_below_schedule(window):
    window.repo.add(Schedule("팀 회의", datetime(2026, 10, 27, 10, 0), datetime(2026, 10, 27, 11, 0)))
    window.todo_repo.add(Todo("회의자료 준비", day=TODAY))
    window.refresh()
    cell = _cell(window, TODAY)
    chip, row = cell._chips[0], cell._rows[0]
    assert row.todo.title == "회의자료 준비"
    assert row.y() > chip.y()


def test_overflow_counts_schedules_and_todos_together(window):
    day = date(2026, 10, 28)
    for i in range(3):
        window.repo.add(Schedule(f"일정{i}", datetime(2026, 10, 28, 9 + i, 0)))
    for i in range(6):
        window.todo_repo.add(Todo(f"할일{i}", day=day))
    window.refresh()
    window.resize(900, 600)
    cell = _cell(window, day)
    visible = [w for w in (*cell._chips, *cell._rows) if w is not None and not w.isHidden()]
    assert len(visible) < 9 and not cell.more.isHidden()
    assert cell.more.text() == f"+{9 - len(visible)}개"


def test_check_marks_done_and_persists(window):
    tid = window.todo_repo.add(Todo("블로그 글", day=TODAY))
    window.refresh()
    _cell(window, TODAY)._rows[0].check.click()
    assert window.todo_repo.get(tid).done is True
    assert _cell(window, TODAY)._rows[0].check.isChecked()


def test_click_to_edit_commits_new_title(window):
    tid = window.todo_repo.add(Todo("옛 제목", day=TODAY))
    window.refresh()
    row = _cell(window, TODAY)._rows[0]
    row.title_btn.click()
    assert not row.edit.isHidden() and row.edit.text() == "옛 제목"
    row.edit.setText("새 제목")
    row.edit.editingFinished.emit()
    assert window.todo_repo.get(tid).title == "새 제목"


def test_edit_with_blank_text_changes_nothing(window):
    tid = window.todo_repo.add(Todo("그대로", day=TODAY))
    window.refresh()
    row = _cell(window, TODAY)._rows[0]
    row.start_edit()
    row.edit.setText("   ")
    row.edit.editingFinished.emit()
    assert window.todo_repo.get(tid).title == "그대로"


def test_escape_cancels_edit(window):
    tid = window.todo_repo.add(Todo("원본", day=TODAY))
    window.refresh()
    row = _cell(window, TODAY)._rows[0]
    row.start_edit()
    row.edit.setText("바꾸다 말기")
    row.edit.cancelled.emit()
    assert row.edit.isHidden() and not row.title_btn.isHidden()
    assert window.todo_repo.get(tid).title == "원본"


def test_priority_from_context_menu(window):
    tid = window.todo_repo.add(Todo("중요", day=TODAY))
    window.refresh()
    row = _cell(window, TODAY)._rows[0]
    menu = row.build_menu()
    high = next(a for a in menu.actions() if "높음" in a.text())
    high.trigger()
    assert window.todo_repo.get(tid).priority == PRIORITY_HIGH


def test_daily_menu_has_no_move_but_quick_menu_does(window):
    window.todo_repo.add(Todo("데일리", day=TODAY))
    window.todo_repo.add(Todo("퀵"))
    window.refresh()
    daily = _cell(window, TODAY)._rows[0].build_menu()
    quick = window.quick_card.rows()[0].build_menu()
    assert not any("날짜로" in a.text() for a in daily.actions())
    assert any("날짜로" in a.text() for a in quick.actions())


# ---- 삭제 + Undo -------------------------------------------------------------


def test_delete_is_immediate_and_undo_restores(window):
    tid = window.todo_repo.add(Todo("지울 것", day=TODAY))
    window.refresh()
    _cell(window, TODAY)._rows[0].delete_btn.click()
    assert window.todo_repo.get(tid) is None
    assert _cell(window, TODAY)._rows == []
    toast = window._toast
    assert toast is not None and toast.timer.interval() == 5000 and toast.timer.isActive()
    toast.undo()
    assert window.todo_repo.get(tid).title == "지울 것"
    assert [r.todo.title for r in _cell(window, TODAY)._rows] == ["지울 것"]


def test_toast_disappears_after_timeout_and_delete_stays(window):
    tid = window.todo_repo.add(Todo("영영", day=TODAY))
    window.refresh()
    _cell(window, TODAY)._rows[0].delete_btn.click()
    window._toast.timer.timeout.emit()
    assert window.todo_repo.get(tid) is None
    assert window._toast.isHidden()


# ---- Quick To-Do ---------------------------------------------------------------


def test_quick_panel_lists_only_quick_todos(window):
    window.todo_repo.add(Todo("퀵1"))
    window.todo_repo.add(Todo("데일리", day=TODAY))
    window.refresh()
    assert _titles(window.quick_card.rows()) == ["퀵1"]
    assert window.quick_card.empty.isHidden()


def test_quick_panel_empty_hint(window):
    assert not window.quick_card.empty.isHidden()


def test_quick_check_rename_delete(window):
    tid = window.todo_repo.add(Todo("우유 사기"))
    window.refresh()
    window.quick_card.rows()[0].check.click()
    assert window.todo_repo.get(tid).done
    window.quick_card.rows()[0].action.emit("rename", window.quick_card.rows()[0].todo, "두유 사기")
    assert window.todo_repo.get(tid).title == "두유 사기"
    window.quick_card.rows()[0].delete_btn.click()
    assert window.todo_repo.list_quick() == []


def test_move_quick_to_daily(window, monkeypatch):
    class FakePicker:
        DialogCode = main_window.DatePickDialog.DialogCode

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def day(self):
            return date(2026, 10, 30)

    monkeypatch.setattr(main_window, "DatePickDialog", FakePicker)
    tid = window.todo_repo.add(Todo("택배 보내기"))
    window.refresh()
    window.quick_card.rows()[0].action.emit("move", window.quick_card.rows()[0].todo, None)
    assert window.todo_repo.get(tid).day == date(2026, 10, 30)
    assert window.quick_card.rows() == []
    assert [r.todo.title for r in _cell(window, date(2026, 10, 30))._rows] == ["택배 보내기"]


# ---- 날짜 목록 팝업 --------------------------------------------------------------


def test_day_list_dialog_shows_todos_and_follows_refresh(window):
    day = date(2026, 10, 28)
    window.todo_repo.add(Todo("가", day=day))
    window.todo_repo.add(Todo("나", day=day))
    window.refresh()

    from flowcalendar.ui.dialogs import DayListDialog

    dialog = DayListDialog(window, day, *window._day_items(day))
    dialog.todo_action.connect(window.on_todo_action)
    window._day_dialog = dialog
    rows = [dialog._layout.itemAt(i).widget() for i in range(dialog._layout.count())]
    assert [r.todo.title for r in rows if isinstance(r, TodoRow)] == ["가", "나"]

    rows[0].check.click()  # 팝업 안에서 완료 -> 저장소 갱신 + 팝업 목록 갱신(완료는 아래로)
    rows = [dialog._layout.itemAt(i).widget() for i in range(dialog._layout.count())]
    assert [r.todo.title for r in rows if isinstance(r, TodoRow)] == ["나", "가"]
    window._day_dialog = None


# ---- Quick Memo ----------------------------------------------------------------


def test_memo_loads_saved_content_with_bullets_but_no_bullet_chars(window):
    window.memo_repo.set("회의 때 말할 것\n보고서 제출")
    edit = MemoEdit()
    edit.set_content(window.memo_repo.get())
    assert edit.toPlainText() == "회의 때 말할 것\n보고서 제출"
    blocks = [edit.document().findBlockByNumber(i) for i in range(edit.document().blockCount())]
    assert all(b.blockFormat().leftMargin() == BULLET_INDENT for b in blocks)
    assert all(edit.has_bullet(b) for b in blocks)


def test_memo_autosave_emits_once_after_typing(app):
    edit = MemoEdit(delay_ms=10_000)
    saved = []
    edit.changed.connect(saved.append)
    edit.setPlainText("첫 줄")
    edit.moveCursor(edit.textCursor().MoveOperation.End)
    edit.insertPlainText("\n둘째 줄")
    assert saved == []  # 아직 대기 중
    edit.flush()
    assert saved == ["첫 줄\n둘째 줄"]
    edit.flush()
    assert saved == ["첫 줄\n둘째 줄"]  # 바뀐 게 없으면 다시 저장하지 않는다


def test_memo_load_does_not_trigger_save(app):
    edit = MemoEdit()
    saved = []
    edit.changed.connect(saved.append)
    edit.set_content("불러온 내용")
    edit.flush()
    assert saved == []


def test_memo_rebullets_after_clear(app):
    edit = MemoEdit()
    edit.set_content("a\nb")
    edit.clear()
    edit.insertPlainText("새 줄")
    assert edit.document().begin().blockFormat().leftMargin() == BULLET_INDENT


def test_memo_has_no_bullet_when_empty(app):
    edit = MemoEdit()
    edit.set_content("a")
    edit.selectAll()
    edit.textCursor().removeSelectedText()
    assert edit.toPlainText() == ""
    assert not edit.has_bullet(edit.document().begin())  # 다 지우면 동그라미도 사라진다
    edit.insertPlainText("x")
    assert edit.has_bullet(edit.document().begin())


def test_memo_backspace_on_empty_line_removes_that_line(app):
    edit = MemoEdit()
    edit.set_content("a\nb\n")
    edit.moveCursor(edit.textCursor().MoveOperation.End)
    assert edit.document().blockCount() == 3
    QTest.keyClick(edit, Qt.Key.Key_Backspace)
    assert edit.toPlainText() == "a\nb"
    for _ in range(5):  # 계속 눌러도 남은 줄의 서식이 깨지지 않는다
        QTest.keyClick(edit, Qt.Key.Key_Backspace)
    assert edit.toPlainText() == ""
    assert edit.document().begin().blockFormat().leftMargin() == BULLET_INDENT
    assert not edit.has_bullet(edit.document().begin())


def test_memo_wired_to_repo_and_flushed_on_close(window):
    window.memo_card.edit.setPlainText("저장될 메모")
    window.close()
    assert window.memo_repo.get() == "저장될 메모"
