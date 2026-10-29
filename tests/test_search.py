"""검색: 저장소 · 서비스 · 팝업 · 결과로 이동."""

from datetime import date, datetime

import pytest
from PySide6.QtWidgets import QApplication

from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services.search import search_all
from flowcalendar.ui import tokens
from flowcalendar.ui.main_window import MainWindow
from flowcalendar.ui.search_dialog import HINT, NOTHING, SearchDialog

TODAY = date(2026, 10, 28)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


@pytest.fixture
def repos():
    conn = db.connect(":memory:")
    s, t, m = ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn)
    s.add(Schedule("팀 회의", datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11)))
    s.add(Schedule("분기 회의", datetime(2027, 3, 2), None, all_day=True))
    s.add(Schedule("치과", datetime(2026, 10, 30, 14), datetime(2026, 10, 30, 15)))
    t.add(Todo("회의 자료 준비", day=date(2026, 10, 29)))
    t.add(Todo("회의록 정리"))
    done = t.add(Todo("회의실 예약"))
    todo = t.get(done)
    todo.done = True
    t.update(todo)
    m.set("claude skill\n회의 때 말할 것\nmonorepo")
    return s, t, m


# ---- 저장소 · 서비스 -------------------------------------------------------------------


def test_search_finds_schedules_todos_and_memo(repos):
    r = search_all(*repos, "회의", TODAY)
    assert [s.title for s in r.schedules] == ["팀 회의", "분기 회의"]  # 오늘에서 가까운 날짜 먼저
    assert [t.title for t in r.todos] == ["회의 자료 준비", "회의록 정리", "회의실 예약"]  # 안 끝낸 것 먼저, 완료는 맨 뒤
    assert r.memo_lines == ["회의 때 말할 것"]
    assert r.total == 6


def test_search_is_case_insensitive_for_letters_and_ignores_blank(repos):
    assert search_all(*repos, "MONOREPO", TODAY).memo_lines == ["monorepo"]
    assert search_all(*repos, "   ", TODAY).total == 0
    assert search_all(*repos, "", TODAY).total == 0


def test_search_treats_percent_and_underscore_literally(repos):
    s, t, m = repos
    s.add(Schedule("할인 50% 행사", datetime(2026, 11, 1), None, all_day=True))
    s.add(Schedule("a_b 파일", datetime(2026, 11, 2), None, all_day=True))
    assert [x.title for x in search_all(s, t, m, "50%", TODAY).schedules] == ["할인 50% 행사"]
    assert [x.title for x in search_all(s, t, m, "a_b", TODAY).schedules] == ["a_b 파일"]
    assert search_all(s, t, m, "%", TODAY).schedules[0].title == "할인 50% 행사"  # % 가 모든 것에 맞지 않는다
    assert len(search_all(s, t, m, "%", TODAY).schedules) == 1
    assert search_all(s, t, m, "a\\", TODAY).total == 0  # 역슬래시도 그냥 글자


def test_recurring_schedule_appears_once(repos):
    s, t, m = repos
    s.add(Schedule("스탠드업", datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 9, 15), recurrence="daily"))
    assert len(search_all(s, t, m, "스탠드업", TODAY).schedules) == 1


def test_limit_caps_each_kind(repos):
    s, t, m = repos
    for i in range(40):
        s.add(Schedule(f"반복 점검 {i}", datetime(2026, 11, 1), None, all_day=True))
    assert len(search_all(s, t, m, "반복 점검", TODAY, limit=30).schedules) == 30


# ---- 팝업 ------------------------------------------------------------------------------


def _dialog(repos, qapp):
    d = SearchDialog(None, lambda q: search_all(*repos, q, TODAY))
    d.show()
    qapp.processEvents()
    return d


def test_dialog_shows_hint_then_results_then_nothing(repos, qapp):
    d = _dialog(repos, qapp)
    assert d.status.text() == HINT and d._buttons == []
    d.input.setText("회의")
    assert len(d._buttons) == 6 and "일정 2" in d.status.text() and "메모 1" in d.status.text()
    d.input.setText("없는말없는말")
    assert d.status.text() == NOTHING and d._buttons == []
    d.input.setText("")
    assert d.status.text() == HINT


def test_clicking_result_selects_it_and_closes(repos, qapp):
    d = _dialog(repos, qapp)
    d.input.setText("치과")
    d._buttons[0].click()
    assert d.selected[0] == "schedule" and d.selected[1].title == "치과"
    assert d.result() == d.DialogCode.Accepted


def test_enter_picks_first_result_in_order_schedule_todo_memo(repos, qapp):
    d = _dialog(repos, qapp)
    d.input.setText("회의")
    d._pick_first()
    assert d.selected[0] == "schedule" and d.selected[1].title == "팀 회의"
    d2 = _dialog(repos, qapp)
    d2.input.setText("자료 준비")
    d2._pick_first()
    assert d2.selected[0] == "todo"
    d3 = _dialog(repos, qapp)
    d3.input.setText("말할")
    d3._pick_first()
    assert d3.selected == ("memo", "회의 때 말할 것")


# ---- 결과로 이동 -----------------------------------------------------------------------


@pytest.fixture
def window(repos, qapp):
    s, t, m = repos
    w = MainWindow(s, t, m, today=TODAY)
    w.resize(1100, 700)
    w.show()
    w.memo_card.edit.set_content(m.get())
    qapp.processEvents()
    return w


def test_header_has_search_button_with_equal_height_and_shortcut(window):
    assert window.search_btn.height() == window.menu_btn.height() == window.today_btn.height()
    assert "Ctrl+F" in window.search_btn.toolTip()


def test_open_schedule_result_moves_to_that_month_and_opens_edit(window, monkeypatch):
    opened = []
    monkeypatch.setattr(MainWindow, "on_edit", lambda self, occ: opened.append(occ))
    far = Schedule("먼 훗날 일정", datetime(2027, 3, 2), None, all_day=True)
    far.id = window.repo.add(far)
    window.open_search_result("schedule", window.repo.get(far.id))
    assert (window.year, window.month) == (2027, 3)
    assert opened[0].title == "먼 훗날 일정" and opened[0].date == date(2027, 3, 2)


def test_open_todo_result_opens_that_days_list_and_quick_todo_gives_hint(window, monkeypatch):
    days = []
    monkeypatch.setattr(MainWindow, "on_overflow", lambda self, day: days.append(day))
    daily = window.todo_repo.search("자료 준비", TODAY)[0]
    window.open_search_result("todo", daily)
    assert days == [date(2026, 10, 29)]
    quick = window.todo_repo.search("회의록", TODAY)[0]
    window.open_search_result("todo", quick)
    assert days == [date(2026, 10, 29)]  # Quick 은 날짜가 없어 목록을 열지 않고 안내만


def test_open_memo_result_selects_the_found_text(window):
    window.open_search_result("memo", "말할 것")
    assert window.memo_card.edit.selected_text() == "말할 것"


def test_search_button_opens_dialog(window, monkeypatch):
    shown = []
    monkeypatch.setattr(SearchDialog, "exec", lambda self: shown.append(self) or 0)
    window.search_btn.click()
    assert len(shown) == 1
