"""일정 시작 전 알림 시각 계산. Qt도 DB도 모르는 순수 로직이라 단위 테스트로 검증한다."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from flowcalendar.domain.models import Occurrence

REMINDER_CHOICES = (5, 10, 30, 60)  # FR-SCH-006
MAX_REMINDER_MIN = max(REMINDER_CHOICES)


@dataclass(frozen=True)
class Reminder:
    occurrence: Occurrence
    fire_at: datetime

    @property
    def minutes_before(self) -> int:
        return self.occurrence.schedule.remind_before_min

    def message(self) -> str:
        start = self.occurrence.start_at.strftime("%H:%M")
        return f"{self.minutes_before}분 후 {start} 시작"


def lookup_range(after: datetime, until: datetime) -> tuple[date, date]:
    """알림 후보 일정을 읽어 올 날짜 범위. 자정을 넘겨 미리 울리는 경우(다음 날 00:30 일정 등)까지 포함한다."""
    days_ahead = MAX_REMINDER_MIN // (24 * 60) + 1
    return after.date(), until.date() + timedelta(days=days_ahead)


def due_reminders(
    occurrences: list[Occurrence], after: datetime, until: datetime
) -> list[Reminder]:
    """알림 시각이 (after, until] 에 드는 일정의 알림을 시각 순으로 돌려준다.

    - 종일 일정과 알림 없음(None)은 건너뛴다.
    - 이미 시작한 일정은 울리지 않는다 (절전 복귀 후 오래된 알림이 한꺼번에 뜨는 것을 막는다).
    - 같은 구간을 두 번 넘기지 않으면 한 알림은 정확히 한 번만 나온다. 반복 일정도 회차마다 따로 센다.
    """
    result = []
    for occ in occurrences:
        minutes = occ.schedule.remind_before_min
        if minutes is None or occ.all_day:
            continue
        fire_at = occ.start_at - timedelta(minutes=minutes)
        if after < fire_at <= until and until < occ.start_at:
            result.append(Reminder(occ, fire_at))
    result.sort(key=lambda r: (r.fire_at, r.occurrence.title))
    return result
