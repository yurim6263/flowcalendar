from datetime import date, datetime

import pytest

from flowcalendar.data import db
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.domain.models import Schedule

OCT = (date(2026, 10, 1), date(2026, 10, 31))


@pytest.fixture
def repo():
    return ScheduleRepository(db.connect(":memory:"))


def _s(**kw):
    base = dict(title="회의", start_at=datetime(2026, 10, 5, 9, 0), end_at=datetime(2026, 10, 5, 10, 0))
    base.update(kw)
    return Schedule(**base)


def _days(repo, title=None):
    return [o.date.day for o in repo.list_occurrences(*OCT) if title in (None, o.title)]


def test_add_get_roundtrip(repo):
    sid = repo.add(_s(color="pink", remind_before_min=10))
    got = repo.get(sid)
    assert (got.title, got.color, got.remind_before_min) == ("회의", "pink", 10)
    assert got.start_at == datetime(2026, 10, 5, 9, 0)


def test_validation_rejects_blank_title_and_reversed_time(repo):
    with pytest.raises(ValueError):
        repo.add(_s(title="  "))
    with pytest.raises(ValueError):
        repo.add(_s(end_at=datetime(2026, 10, 5, 8, 0)))


def test_update_and_delete(repo):
    sid = repo.add(_s())
    s = repo.get(sid)
    s.title = "수정됨"
    repo.update(s)
    assert repo.get(sid).title == "수정됨"
    repo.delete(sid)
    assert repo.list_occurrences(*OCT) == []


def test_range_excludes_other_months(repo):
    repo.add(_s(start_at=datetime(2026, 11, 2, 9, 0), end_at=None))
    assert repo.list_occurrences(*OCT) == []


def test_recurring_from_earlier_month_appears(repo):
    repo.add(_s(start_at=datetime(2026, 9, 7, 9, 0), end_at=None, recurrence="weekly"))
    assert _days(repo) == [5, 12, 19, 26]


def test_delete_occurrence_only(repo):
    sid = repo.add(_s(recurrence="weekly"))
    repo.delete_occurrence(sid, date(2026, 10, 12))
    assert _days(repo) == [5, 19, 26]


def test_delete_from_truncates_series(repo):
    sid = repo.add(_s(recurrence="weekly"))
    repo.delete_from(sid, date(2026, 10, 19))
    assert _days(repo) == [5, 12]


def test_delete_from_first_occurrence_removes_series(repo):
    sid = repo.add(_s(recurrence="weekly"))
    repo.delete_from(sid, date(2026, 10, 5))
    assert repo.get(sid) is None


def test_update_occurrence_only_creates_one_off(repo):
    sid = repo.add(_s(recurrence="weekly"))
    new = _s(title="이동", start_at=datetime(2026, 10, 13, 15, 0), end_at=None, color="blue")
    repo.update_occurrence(sid, date(2026, 10, 12), new)
    assert _days(repo, "회의") == [5, 19, 26]
    assert _days(repo, "이동") == [13]


def test_update_from_splits_series(repo):
    sid = repo.add(_s(recurrence="weekly"))
    new = _s(title="새 회의", start_at=datetime(2026, 10, 19, 14, 0), end_at=None, recurrence="weekly")
    repo.update_from(sid, date(2026, 10, 19), new)
    assert _days(repo, "회의") == [5, 12]
    assert _days(repo, "새 회의") == [19, 26]


def test_update_from_first_occurrence_updates_in_place(repo):
    sid = repo.add(_s(recurrence="weekly"))
    repo.delete_occurrence(sid, date(2026, 10, 12))
    new = _s(title="바뀜", recurrence="weekly")
    assert repo.update_from(sid, date(2026, 10, 5), new) == sid
    assert _days(repo, "바뀜") == [5, 12, 19, 26]
