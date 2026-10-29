from datetime import date

import pytest

from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import PRIORITY_HIGH, PRIORITY_LOW, Todo

D = date(2026, 10, 27)


@pytest.fixture
def repo():
    return TodoRepository(db.connect(":memory:"))


def test_add_and_get_roundtrip(repo):
    tid = repo.add(Todo("우유 사기", day=D, priority=PRIORITY_HIGH))
    got = repo.get(tid)
    assert (got.title, got.day, got.done, got.priority) == ("우유 사기", D, False, PRIORITY_HIGH)
    assert got.is_daily


def test_blank_title_and_bad_priority_rejected(repo):
    with pytest.raises(ValueError):
        repo.add(Todo("  "))
    with pytest.raises(ValueError):
        repo.add(Todo("x", priority=7))


def test_quick_and_daily_are_separated(repo):
    repo.add(Todo("퀵"))
    repo.add(Todo("데일리", day=D))
    assert [t.title for t in repo.list_quick()] == ["퀵"]
    assert [t.title for t in repo.list_daily(D, D)] == ["데일리"]
    assert repo.list_daily(date(2026, 10, 28), date(2026, 10, 30)) == []


def test_update_title_done_priority(repo):
    tid = repo.add(Todo("a", day=D))
    todo = repo.get(tid)
    todo.title, todo.done, todo.priority = " b ", True, PRIORITY_LOW
    repo.update(todo)
    got = repo.get(tid)
    assert (got.title, got.done, got.priority) == ("b", True, PRIORITY_LOW)


def test_order_done_last_then_priority_then_input(repo):
    repo.add(Todo("보통1", day=D))
    done_id = repo.add(Todo("완료", day=D))
    repo.add(Todo("높음", day=D, priority=PRIORITY_HIGH))
    repo.add(Todo("보통2", day=D))
    done = repo.get(done_id)
    done.done = True
    repo.update(done)
    assert [t.title for t in repo.list_daily(D, D)] == ["높음", "보통1", "보통2", "완료"]


def test_move_quick_to_daily_goes_to_end(repo):
    repo.add(Todo("기존", day=D))
    tid = repo.add(Todo("퀵"))
    repo.move_to_date(tid, D)
    assert repo.list_quick() == []
    assert [t.title for t in repo.list_daily(D, D)] == ["기존", "퀵"]


def test_delete_returns_snapshot_and_restore_brings_it_back(repo):
    repo.add(Todo("앞", day=D))
    tid = repo.add(Todo("지울 것", day=D))
    repo.add(Todo("뒤", day=D))
    snapshot = repo.delete(tid)
    assert repo.get(tid) is None
    repo.restore(snapshot)
    restored = repo.get(tid)
    assert (restored.title, restored.sort_order) == ("지울 것", snapshot.sort_order)
    assert [t.title for t in repo.list_daily(D, D)] == ["앞", "지울 것", "뒤"]


def test_delete_missing_returns_none(repo):
    assert repo.delete(999) is None


def test_memo_is_single_row_and_persists():
    conn = db.connect(":memory:")
    memos = MemoRepository(conn)
    assert memos.get() == ""
    memos.set("회의 때 말할 것")
    memos.set("회의 때 말할 것\n보고서 제출")
    assert memos.get() == "회의 때 말할 것\n보고서 제출"
    assert conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 1
