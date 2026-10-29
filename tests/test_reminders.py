from datetime import date, datetime, timedelta

from flowcalendar.data import db
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.domain.models import Schedule
from flowcalendar.services.reminders import due_reminders, lookup_range


def _due(repo, after, until):
    start, end = lookup_range(after, until)
    return due_reminders(repo.list_occurrences(start, end), after, until)


def _repo():
    return ScheduleRepository(db.connect(":memory:"))


def test_fires_once_at_exact_time():
    repo = _repo()
    repo.add(Schedule("회의", datetime(2026, 10, 27, 10, 0), remind_before_min=10))
    assert _due(repo, datetime(2026, 10, 27, 9, 49), datetime(2026, 10, 27, 9, 50))[0].message() == "10분 후 10:00 시작"
    # 직전 구간이 (9:49, 9:50] 이었으니 다음 구간에서는 다시 나오지 않는다 (after 는 미포함).
    assert _due(repo, datetime(2026, 10, 27, 9, 50), datetime(2026, 10, 27, 9, 51)) == []
    assert _due(repo, datetime(2026, 10, 27, 9, 0), datetime(2026, 10, 27, 9, 49)) == []


def test_each_reminder_choice():
    repo = _repo()
    for minutes in (5, 10, 30, 60):
        repo.add(Schedule(f"{minutes}분", datetime(2026, 10, 27, 12, 0), remind_before_min=minutes))
    got = _due(repo, datetime(2026, 10, 27, 10, 59), datetime(2026, 10, 27, 11, 56))
    assert [r.minutes_before for r in got] == [60, 30, 10, 5]


def test_no_reminder_and_all_day_are_skipped():
    repo = _repo()
    repo.add(Schedule("알림 없음", datetime(2026, 10, 27, 10, 0)))
    repo.add(Schedule("종일", datetime(2026, 10, 27, 0, 0), all_day=True, remind_before_min=10))
    assert _due(repo, datetime(2026, 10, 26, 0, 0), datetime(2026, 10, 27, 23, 0)) == []


def test_reminder_crosses_midnight():
    repo = _repo()
    repo.add(Schedule("새벽 일정", datetime(2026, 10, 28, 0, 30), remind_before_min=60))
    got = _due(repo, datetime(2026, 10, 27, 23, 29), datetime(2026, 10, 27, 23, 30))
    assert [r.occurrence.title for r in got] == ["새벽 일정"]


def test_recurring_schedule_fires_for_each_occurrence():
    repo = _repo()
    repo.add(Schedule("스탠드업", datetime(2026, 10, 1, 9, 30), recurrence="daily", remind_before_min=5))
    for day in (5, 6, 20):
        got = _due(repo, datetime(2026, 10, day, 9, 24), datetime(2026, 10, day, 9, 25))
        assert [r.occurrence.date for r in got] == [date(2026, 10, day)]
    assert _due(repo, datetime(2026, 10, 5, 9, 25), datetime(2026, 10, 5, 9, 26)) == []


def test_weekly_and_monthly_only_on_their_days():
    repo = _repo()
    repo.add(Schedule("주간", datetime(2026, 10, 5, 14, 0), recurrence="weekly", remind_before_min=10))
    repo.add(Schedule("월간", datetime(2026, 9, 29, 14, 0), recurrence="monthly", remind_before_min=10))
    hits = lambda d: [r.occurrence.title for r in _due(  # noqa: E731
        repo, datetime(2026, 10, d, 13, 49), datetime(2026, 10, d, 13, 50))]
    assert hits(12) == ["주간"]
    assert hits(13) == []
    assert hits(29) == ["월간"]


def test_deleted_occurrence_does_not_fire():
    repo = _repo()
    sid = repo.add(Schedule("스탠드업", datetime(2026, 10, 1, 9, 30), recurrence="daily", remind_before_min=5))
    repo.delete_occurrence(sid, date(2026, 10, 6))
    assert _due(repo, datetime(2026, 10, 6, 9, 24), datetime(2026, 10, 6, 9, 25)) == []
    assert len(_due(repo, datetime(2026, 10, 7, 9, 24), datetime(2026, 10, 7, 9, 25))) == 1


def test_already_started_event_is_not_announced_after_long_gap():
    repo = _repo()
    repo.add(Schedule("지난 일정", datetime(2026, 10, 27, 10, 0), remind_before_min=10))
    # 절전에서 11시에 깨어났다: 9:50 알림은 구간에 들지만 이미 시작했으니 울리지 않는다.
    assert _due(repo, datetime(2026, 10, 27, 9, 0), datetime(2026, 10, 27, 11, 0)) == []


def test_window_split_never_duplicates_or_drops():
    repo = _repo()
    repo.add(Schedule("연속", datetime(2026, 10, 27, 10, 0), remind_before_min=30))
    tick = datetime(2026, 10, 27, 9, 0)
    count = 0
    while tick < datetime(2026, 10, 27, 10, 0):
        nxt = tick + timedelta(seconds=30)
        count += len(_due(repo, tick, nxt))
        tick = nxt
    assert count == 1
