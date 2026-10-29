import calendar
from datetime import date, datetime, timedelta

from flowcalendar.domain.models import Occurrence, Schedule


def occurs_on(schedule: Schedule, day: date) -> bool:
    first = schedule.start_at.date()
    if day < first:
        return False
    if schedule.recurrence_until is not None and day > schedule.recurrence_until:
        return False
    if schedule.recurrence is None:
        return day == first
    if schedule.recurrence == "daily":
        return True
    if schedule.recurrence == "weekly":
        return (day - first).days % 7 == 0
    if schedule.recurrence == "monthly":
        # 31일 일정은 30일/28일까지만 있는 달에서 그 달의 마지막 날로 보정한다.
        last_day = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(first.day, last_day)
    return False


def expand(
    schedule: Schedule, start: date, end: date, deleted: set[date] = frozenset()
) -> list[Occurrence]:
    """[start, end] 범위(양끝 포함)에 걸치는 일정의 Occurrence를 만든다.

    Occurrence.date 는 그 회차가 시작하는 날이다. 여러 날짜에 걸친 일정은 한 건으로 돌려주고,
    범위보다 먼저 시작했어도 범위 안으로 이어지면 포함한다.
    """
    duration = schedule.end_at - schedule.start_at if schedule.end_at else None
    lookback = span_days(schedule)
    result = []
    day = max(start - timedelta(days=lookback), schedule.start_at.date())
    while day <= end:
        if occurs_on(schedule, day) and day not in deleted:
            start_at = datetime.combine(day, schedule.start_at.time())
            end_at = start_at + duration if duration is not None else None
            occ = Occurrence(schedule, day, start_at, end_at)
            if occ.last_day >= start:
                result.append(occ)
        day += timedelta(days=1)
    return result


def span_days(schedule: Schedule) -> int:
    """일정이 시작한 날 이후로 며칠 더 이어지는지."""
    if schedule.end_at is None:
        return 0
    return max((schedule.end_at.date() - schedule.start_at.date()).days, 0)


def sort_key(occ: Occurrence):
    """종일 일정이 먼저, 이후 시작 시간 순."""
    return (not occ.all_day, occ.start_at.time(), occ.title)
