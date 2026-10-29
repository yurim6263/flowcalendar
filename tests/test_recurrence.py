from datetime import date, datetime

from flowcalendar.domain.models import Schedule
from flowcalendar.domain.recurrence import expand


def _s(**kw):
    base = dict(title="회의", start_at=datetime(2026, 10, 5, 9, 0), end_at=datetime(2026, 10, 5, 10, 0))
    base.update(kw)
    return Schedule(**base)


def test_one_off_only_on_its_day():
    occ = expand(_s(), date(2026, 10, 1), date(2026, 10, 31))
    assert [o.date for o in occ] == [date(2026, 10, 5)]


def test_weekly_repeats_on_same_weekday_and_keeps_duration():
    occ = expand(_s(recurrence="weekly"), date(2026, 10, 1), date(2026, 10, 31))
    assert [o.date.day for o in occ] == [5, 12, 19, 26]
    assert occ[1].end_at - occ[1].start_at == _s().end_at - _s().start_at


def test_until_is_inclusive():
    occ = expand(_s(recurrence="daily", recurrence_until=date(2026, 10, 7)),
                 date(2026, 10, 1), date(2026, 10, 31))
    assert [o.date.day for o in occ] == [5, 6, 7]


def test_monthly_31st_clamps_to_last_day():
    s = _s(start_at=datetime(2026, 1, 31, 9, 0), end_at=None, recurrence="monthly")
    feb = expand(s, date(2026, 2, 1), date(2026, 2, 28))
    assert [o.date for o in feb] == [date(2026, 2, 28)]


def test_deleted_dates_are_skipped():
    occ = expand(_s(recurrence="daily"), date(2026, 10, 5), date(2026, 10, 7), {date(2026, 10, 6)})
    assert [o.date.day for o in occ] == [5, 7]
