from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

COLORS = ("yellow", "pink", "green", "blue", "purple")
RECURRENCES = ("daily", "weekly", "monthly")

PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH = 0, 1, 2
PRIORITIES = (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH)
PRIORITY_LABELS = {PRIORITY_HIGH: "높음", PRIORITY_NORMAL: "보통", PRIORITY_LOW: "낮음"}


@dataclass
class Schedule:
    title: str
    start_at: datetime
    end_at: datetime | None = None
    all_day: bool = False
    color: str = "yellow"
    recurrence: str | None = None
    recurrence_until: date | None = None
    remind_before_min: int | None = None
    id: int | None = None


@dataclass
class Todo:
    """day가 None이면 Quick To-Do, 날짜가 있으면 Daily To-Do."""

    title: str
    day: date | None = None
    done: bool = False
    priority: int = PRIORITY_NORMAL
    sort_order: int = 0
    id: int | None = None

    @property
    def is_daily(self) -> bool:
        return self.day is not None


@dataclass(frozen=True)
class Occurrence:
    """반복 일정을 특정 날짜로 전개한 한 건. 반복이 아니면 일정 자체와 1:1."""

    schedule: Schedule
    date: date
    start_at: datetime
    end_at: datetime | None

    @property
    def title(self) -> str:
        return self.schedule.title

    @property
    def color(self) -> str:
        return self.schedule.color

    @property
    def all_day(self) -> bool:
        return self.schedule.all_day

    @property
    def first_day(self) -> date:
        return self.start_at.date()

    @property
    def last_day(self) -> date:
        """달력에서 이 일정이 끝나는 날. 종일 일정의 종료일은 그날을 포함하고,
        시간이 있는 일정이 다음 날 00:00에 끝나면 전날까지로 본다."""
        if self.end_at is None:
            return self.first_day
        last = self.end_at.date()
        if not self.all_day and self.end_at.time() == time.min and self.end_at > self.start_at:
            last -= timedelta(days=1)
        return max(last, self.first_day)

    @property
    def is_multiday(self) -> bool:
        return self.last_day > self.first_day


def validate_todo(todo: Todo) -> None:
    if not todo.title.strip():
        raise ValueError("내용을 입력하세요.")
    if todo.priority not in PRIORITIES:
        raise ValueError(f"지원하지 않는 우선순위입니다: {todo.priority}")


def validate(schedule: Schedule) -> None:
    if not schedule.title.strip():
        raise ValueError("제목을 입력하세요.")
    if schedule.color not in COLORS:
        raise ValueError(f"지원하지 않는 색상입니다: {schedule.color}")
    if schedule.end_at is not None and schedule.end_at < schedule.start_at:
        raise ValueError("종료 시간이 시작 시간보다 빠릅니다.")
    if schedule.recurrence is not None and schedule.recurrence not in RECURRENCES:
        raise ValueError(f"지원하지 않는 반복입니다: {schedule.recurrence}")
    if schedule.recurrence_until is not None:
        if schedule.recurrence is None:
            raise ValueError("반복이 없는 일정에는 종료일을 지정할 수 없습니다.")
        if schedule.recurrence_until < schedule.start_at.date():
            raise ValueError("반복 종료일이 시작일보다 빠릅니다.")
