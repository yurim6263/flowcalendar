from datetime import date, datetime

import pytest
from PySide6.QtWidgets import QApplication

from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule
from flowcalendar.ui import tokens
from flowcalendar.ui.calendar_view import CalendarGrid
from flowcalendar.ui.main_window import MainWindow

TODAY = date(2026, 10, 27)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


@pytest.fixture
def window(app):
    conn = db.connect(":memory:")
    repo = ScheduleRepository(conn)
    repo.add(Schedule("팀 회의", datetime(2026, 10, 27, 10, 0), datetime(2026, 10, 27, 11, 0)))
    w = MainWindow(repo, TodoRepository(conn), MemoRepository(conn), today=TODAY)
    w.show()
    return w


def _cell(window, day):
    return next(c for c in window.grid._cells if c.day == day and not c.isHidden())


def test_visible_range_is_whole_weeks_starting_sunday():
    start, end = CalendarGrid.visible_range(2026, 10)
    assert start.weekday() == 6 and (end - start).days + 1 in (35, 42)
    assert start <= date(2026, 10, 1) and end >= date(2026, 10, 31)


def test_title_and_schedule_chip_shown(window):
    assert window.title.text() == "2026년 10월"
    cell = _cell(window, TODAY)
    assert [c.text() for c in cell._chips if c is not None and not c.isHidden()] == ["팀 회의"]


def test_month_navigation_wraps_year(window):
    window.shift_month(3)
    assert (window.year, window.month) == (2027, 1)
    window.go_today()
    assert (window.year, window.month) == (2026, 10)


def test_overflow_collapses_to_more_button(window):
    for i in range(8):
        window.repo.add(Schedule(f"일정{i}", datetime(2026, 10, 28, 9 + i % 8, 0)))
    window.refresh()
    window.resize(900, 600)
    cell = _cell(window, date(2026, 10, 28))
    visible = [c for c in cell._chips if c is not None and not c.isHidden()]
    assert len(visible) < 8 and not cell.more.isHidden()
    assert cell.more.text() == f"+{8 - len(visible)}개"


def test_only_visible_items_get_widgets_and_more_button_counts_the_rest(window):
    """접힌('+N개') 일정까지 위젯을 다 만들면 월을 넘길 때 느려진다. 보이는 줄만 만들고, 칸이 커지면 그때 만든다."""
    app = QApplication.instance()
    for i in range(12):
        window.repo.add(Schedule(f"일정{i}", datetime(2026, 10, 28, 8 + i % 10, i)))
    window.resize(900, 600)
    window.refresh()
    app.processEvents()
    cell = _cell(window, date(2026, 10, 28))
    small = len([c for c in cell._chips if c is not None])
    shown = cell.visible_rows()
    assert small == shown < 12  # 접힌 일정의 위젯은 만들지 않았다
    assert cell.more.text() == f"+{12 - shown}개"
    window.resize(1500, 1100)
    app.processEvents()
    cell = _cell(window, date(2026, 10, 28))
    assert len([c for c in cell._chips if c is not None]) == cell.visible_rows() > small
