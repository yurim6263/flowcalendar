"""여러 날에 걸친 일정(종료 날짜)."""

from datetime import date, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from flowcalendar.ai.briefing import build_data
from flowcalendar.ai.quick_add import drafts_from_response
from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule
from flowcalendar.domain.recurrence import expand
from flowcalendar.ui import tokens
from flowcalendar.ui.calendar_view import CalendarGrid
from flowcalendar.ui.dialogs import ScheduleDialog
from flowcalendar.ui.main_window import MainWindow

TODAY = date(2026, 10, 28)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


@pytest.fixture
def repo():
    return ScheduleRepository(db.connect(":memory:"))


def trip(**kw):
    base = dict(title="출장", start_at=datetime(2026, 10, 29), end_at=datetime(2026, 11, 2), all_day=True)
    return Schedule(**{**base, **kw})


# ---- 도메인 · 저장소 -----------------------------------------------------------


def test_occurrence_days_for_allday_range(repo):
    repo.add(trip())
    occ = repo.list_occurrences(date(2026, 10, 1), date(2026, 10, 31))[0]
    assert (occ.first_day, occ.last_day, occ.is_multiday) == (date(2026, 10, 29), date(2026, 11, 2), True)


def test_single_day_schedule_is_not_multiday(repo):
    repo.add(Schedule("회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11)))
    repo.add(Schedule("종일", datetime(2026, 10, 30), None, all_day=True))
    assert not any(o.is_multiday for o in repo.list_occurrences(date(2026, 10, 1), date(2026, 10, 31)))


def test_timed_event_ending_at_midnight_ends_the_day_before(repo):
    repo.add(Schedule("야근", datetime(2026, 10, 29, 22), datetime(2026, 10, 30, 0, 0)))
    occ = repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 30))[0]
    assert occ.last_day == date(2026, 10, 29)


def test_range_query_includes_events_that_started_earlier(repo):
    repo.add(trip())
    assert [o.title for o in repo.list_occurrences(date(2026, 11, 1), date(2026, 11, 1))] == ["출장"]
    assert repo.list_occurrences(date(2026, 11, 3), date(2026, 11, 30)) == []
    assert repo.list_occurrences(date(2026, 10, 1), date(2026, 10, 28)) == []
    assert len(repo.list_occurrences(date(2026, 10, 31), date(2026, 10, 31))) == 1  # 가운데 날


def test_end_before_start_is_rejected(repo):
    with pytest.raises(ValueError):
        repo.add(trip(end_at=datetime(2026, 10, 28)))


def test_recurring_multiday_is_found_from_a_later_window(repo):
    # 매주 수요일에 시작하는 3일짜리 일정: 다음 주 월요일(회차가 시작한 지 5일 뒤)에는 안 걸리고, 금요일엔 걸린다.
    repo.add(Schedule("스프린트", datetime(2026, 10, 28), datetime(2026, 10, 30), all_day=True, recurrence="weekly"))
    assert [o.date for o in repo.list_occurrences(date(2026, 10, 30), date(2026, 10, 30))] == [date(2026, 10, 28)]
    assert repo.list_occurrences(date(2026, 11, 2), date(2026, 11, 2)) == []
    assert [o.date for o in repo.list_occurrences(date(2026, 11, 6), date(2026, 11, 6))] == [date(2026, 11, 4)]


def test_recurring_multiday_respects_until_and_deleted_occurrence(repo):
    sid = repo.add(Schedule("스프린트", datetime(2026, 10, 28), datetime(2026, 10, 30), all_day=True,
                            recurrence="weekly", recurrence_until=date(2026, 11, 4)))
    repo.delete_occurrence(sid, date(2026, 10, 28))
    assert repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 30)) == []  # 지운 회차의 뒷날도 사라진다
    assert len(repo.list_occurrences(date(2026, 11, 5), date(2026, 11, 6))) == 1  # until 이후에 끝나도 마지막 회차는 보인다


def test_expand_keeps_duration_for_each_occurrence():
    s = Schedule("x", datetime(2026, 10, 28, 9), datetime(2026, 10, 30, 18), recurrence="monthly")
    occs = expand(s, date(2026, 10, 1), date(2026, 12, 31))
    assert [(o.start_at, o.end_at) for o in occs[1:2]] == [(datetime(2026, 11, 28, 9), datetime(2026, 11, 30, 18))]


# ---- 달력 ----------------------------------------------------------------------


@pytest.fixture
def window(app):
    conn = db.connect(":memory:")
    w = MainWindow(ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn), today=TODAY)
    w.resize(1280, 820)
    w.show()
    app.processEvents()
    return w


def test_multiday_event_is_one_bar_per_week_and_not_a_chip(window, app):
    window.repo.add(trip(end_at=datetime(2026, 11, 7)))  # 10/29(목) ~ 11/7(토): 두 주에 걸친다
    window.repo.add(Schedule("회식", datetime(2026, 10, 29, 18), datetime(2026, 10, 29, 20)))
    window.refresh()
    app.processEvents()
    segs = window.grid._segments
    assert [(s.week, s.col_start, s.col_end) for s in segs] == [(4, 4, 6)]  # 이번 달 격자는 10/31까지 5주
    assert segs[0].continues_right and not segs[0].continues_left
    cell = next(c for c in window.grid._cells if c.day == date(2026, 10, 29) and not c.isHidden())
    # 하루짜리 회식은 막대 아래 줄에 칩으로 그려진다
    assert [c is not None for c in cell._chips] == [False, True]
    assert cell._chips[1].y() > window.grid.bars()[0].y() - cell.y()


def test_bar_spans_cells_and_shares_one_row(window, app):
    window.repo.add(Schedule("워크숍", datetime(2026, 10, 21, 9), datetime(2026, 10, 23, 18), color="green"))
    window.refresh()
    app.processEvents()
    bar = window.grid.bars()[0]
    first = next(c for c in window.grid._cells if c.day == date(2026, 10, 21) and not c.isHidden())
    last = next(c for c in window.grid._cells if c.day == date(2026, 10, 23) and not c.isHidden())
    assert bar.x() <= first.x() + 6
    assert bar.x() + bar.width() >= last.x() + last.width() - 6
    assert bar.isVisible() and bar.text() == "워크숍"


def test_overlapping_bars_use_different_rows(app):
    days = [date(2026, 10, 25) + timedelta(days=i) for i in range(7)]
    conn = db.connect(":memory:")
    repo = ScheduleRepository(conn)
    repo.add(trip(title="A", start_at=datetime(2026, 10, 26), end_at=datetime(2026, 10, 28)))
    repo.add(trip(title="B", start_at=datetime(2026, 10, 27), end_at=datetime(2026, 10, 29)))
    repo.add(trip(title="C", start_at=datetime(2026, 10, 30), end_at=datetime(2026, 10, 31)))
    occs = repo.list_occurrences(days[0], days[-1])
    slots = {s.occ.title: s.slot for s in CalendarGrid.plan_week(0, days, occs)}
    assert slots["A"] != slots["B"]
    assert slots["C"] == 0  # 앞의 줄이 비면 그 자리를 다시 쓴다


def test_clicking_bar_emits_the_same_occurrence(app, repo):
    repo.add(trip(end_at=datetime(2026, 10, 31)))
    grid = CalendarGrid()  # 창에 붙이면 클릭이 수정 팝업을 열어 버린다
    grid.set_month(2026, 10, repo.list_occurrences(date(2026, 10, 25), date(2026, 10, 31)), TODAY)
    clicked = []
    grid.occurrence_clicked.connect(clicked.append)
    grid.bars()[0].click()
    assert clicked[0].title == "출장" and clicked[0].date == date(2026, 10, 29)


def test_day_in_the_middle_lists_the_event(window):
    window.repo.add(trip())
    occs, _ = window._day_items(date(2026, 10, 31))
    assert [o.title for o in occs] == ["출장"]


# ---- 팝업 ----------------------------------------------------------------------


def test_dialog_defaults_to_single_day(app):
    d = ScheduleDialog(day=date(2026, 10, 29))
    d.title_edit.setText("회의")
    s = d.schedule()
    assert not d.has_end_date.isChecked() and not d.end_date_edit.isEnabled()
    assert s.end_at.date() == s.start_at.date()


def test_dialog_end_date_makes_multiday_schedule(app):
    d = ScheduleDialog(day=date(2026, 10, 29))
    d.title_edit.setText("출장")
    d.all_day.setChecked(True)
    d.has_end_date.setChecked(True)
    assert d.end_date_edit.isEnabled()
    d.end_date_edit.setDate(d.end_date_edit.date().addDays(3))
    s = d.schedule()
    assert (s.start_at, s.end_at) == (datetime(2026, 10, 29), datetime(2026, 11, 1))
    assert s.all_day


def test_dialog_timed_multiday_uses_end_time_on_end_date(app):
    d = ScheduleDialog(day=date(2026, 10, 29))
    d.title_edit.setText("워크숍")
    d.has_end_date.setChecked(True)
    d.end_date_edit.setDate(d.end_date_edit.date().addDays(1))
    s = d.schedule()
    assert (s.start_at, s.end_at) == (datetime(2026, 10, 29, 9), datetime(2026, 10, 30, 10))


def test_dialog_end_date_follows_start_date(app):
    d = ScheduleDialog(day=date(2026, 10, 29))
    d.has_end_date.setChecked(True)
    d.end_date_edit.setDate(d.end_date_edit.date().addDays(1))
    d.date_edit.setDate(d.date_edit.date().addDays(5))  # 시작일을 종료일보다 뒤로
    assert d.end_date_edit.date() == d.date_edit.date()
    assert d.end_date_edit.minimumDate() == d.date_edit.date()


def test_dialog_unchecking_end_date_returns_to_single_day(app):
    d = ScheduleDialog(day=date(2026, 10, 29))
    d.title_edit.setText("x")
    d.has_end_date.setChecked(True)
    d.end_date_edit.setDate(d.end_date_edit.date().addDays(2))
    d.has_end_date.setChecked(False)
    assert d.schedule().end_at.date() == date(2026, 10, 29)


def test_dialog_loads_existing_multiday_occurrence(app, repo):
    repo.add(trip())
    occ = repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 29))[0]
    d = ScheduleDialog(occurrence=occ)
    assert d.has_end_date.isChecked()
    assert d.end_date_edit.date().toPython() == date(2026, 11, 2)
    s = d.schedule()
    assert (s.start_at, s.end_at) == (datetime(2026, 10, 29), datetime(2026, 11, 2))


def test_dialog_loads_single_day_without_end_date(app, repo):
    repo.add(Schedule("회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11)))
    occ = repo.list_occurrences(date(2026, 10, 29), date(2026, 10, 29))[0]
    assert not ScheduleDialog(occurrence=occ).has_end_date.isChecked()


# ---- AI · 브리핑 ---------------------------------------------------------------


def test_ai_draft_with_end_date_becomes_multiday_schedule():
    item = {"kind": "schedule", "title": "출장", "date": "2026-10-29", "end_date": "2026-10-31",
            "all_day": True, "recurrence": "none"}
    draft = drafts_from_response({"items": [item]}, TODAY)[0]
    s = draft.to_schedule()
    assert (s.start_at, s.end_at, s.all_day) == (datetime(2026, 10, 29), datetime(2026, 10, 31), True)
    assert "10/29~10/31" in draft.summary()


def test_ai_draft_ignores_end_date_not_after_start():
    item = {"kind": "schedule", "title": "출장", "date": "2026-10-29", "end_date": "2026-10-28",
            "all_day": True, "recurrence": "none"}
    assert drafts_from_response({"items": [item]}, TODAY)[0].to_schedule().end_at is None


def test_briefing_includes_event_that_started_before_the_period(repo):
    repo.add(trip(start_at=datetime(2026, 10, 25), end_at=datetime(2026, 10, 30)))
    occs = repo.list_occurrences(date(2026, 10, 25), date(2026, 10, 31))
    data = build_data("day", TODAY, occs, [], [])
    assert [o.title for o in data.occurrences] == ["출장"]
