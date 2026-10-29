"""자연어 -> 일정/To-Do 후보 변환. 빠른 추가(한 문장)와 메모 선택 변환(여러 줄)이 같이 쓴다.

AI 는 후보(Draft)를 만들 뿐이다. 저장은 항상 사용자가 미리보기를 확인한 뒤에 앱이 한다 (FR-AI-005).
AI 에 보내는 것: 사용자가 입력하거나 선택한 글, 그리고 현재 날짜·요일·시각뿐이다.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from flowcalendar.ai.errors import AIError
from flowcalendar.domain.models import (
    COLORS,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    Schedule,
    Todo,
)
from flowcalendar.services.reminders import REMINDER_CHOICES

MAX_INPUT_CHARS = 2000
MAX_ITEMS = 10
WEEKDAYS_KO = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
_PRIORITIES = {"low": PRIORITY_LOW, "normal": PRIORITY_NORMAL, "high": PRIORITY_HIGH}
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$")

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["schedule", "todo"]},
        "title": {"type": "string"},
        "date": {"type": "string", "nullable": True},
        "end_date": {"type": "string", "nullable": True},
        "start_time": {"type": "string", "nullable": True},
        "end_time": {"type": "string", "nullable": True},
        "all_day": {"type": "boolean"},
        "recurrence": {"type": "string", "enum": ["none", "daily", "weekly", "monthly"]},
        "recurrence_until": {"type": "string", "nullable": True},
        "remind_before_min": {"type": "integer", "nullable": True},
        "color": {"type": "string", "enum": list(COLORS), "nullable": True},
        "priority": {"type": "string", "enum": ["low", "normal", "high"], "nullable": True},
    },
    "required": ["kind", "title", "all_day", "recurrence"],
}
SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}}, "required": ["items"]}


def system_prompt(now: datetime) -> str:
    weekday = WEEKDAYS_KO[now.weekday()]
    return (
        "당신은 캘린더 입력 도우미입니다. 사용자의 글에서 일정(schedule)과 할 일(todo)을 찾아 JSON 으로만 답합니다.\n"
        f"현재 시각: {now:%Y-%m-%d} ({weekday}) {now:%H:%M}\n"
        "규칙:\n"
        "- 날짜는 YYYY-MM-DD, 시간은 24시간 HH:MM 으로 씁니다. '내일', '모레', '다음 주 월요일', '이번 주 금요일' 같은 "
        "말은 위의 현재 시각을 기준으로 계산합니다.\n"
        "- 월이 없고 일(日)만 있으면(예: '29일') 오늘 이후로 가장 가까운 그 날짜로 합니다.\n"
        "- '오후 3시'는 15:00 입니다. '1시간', '30분' 같은 길이가 있으면 end_time 을 계산합니다. 길이가 없으면 end_time 은 null 입니다.\n"
        "- 정해진 날짜(와 시간)에 하는 모임·약속·행사는 schedule 입니다. 시간이 없으면 all_day 를 true 로 합니다.\n"
        "- 여러 날에 걸친 일정(예: '29일부터 31일까지 출장')은 date 에 시작일, end_date 에 마지막 날을 넣습니다. 하루짜리면 end_date 는 null 입니다.\n"
        "- 시각이 정해지지 않은 해야 할 일(사기, 제출하기, 정리하기 등)은 todo 입니다. 날짜가 없으면 date 는 null 입니다.\n"
        "- 사용자가 '데일리 투두', '투두', '할 일', 'to-do'라고 말하면 todo 로, '일정', '스케줄', '약속'이라고 말하면 schedule 로 합니다. "
        "todo 라도 날짜를 말했으면 date 에 그 날짜를 넣습니다 (날짜가 있는 todo 는 그 날의 Daily To-Do 가 됩니다).\n"
        "- '등록해줘', '추가해줘', '데일리투두 등록' 같은 요청하는 말은 title 에 넣지 않습니다. title 에는 일정이나 할 일의 내용만 짧게 씁니다.\n"
        "- '매일', '매주', '매월'이 있으면 recurrence 를 daily/weekly/monthly 로 하고, 없으면 none 입니다.\n"
        "- '10분 전에 알려줘'처럼 알림 요청이 있을 때만 remind_before_min 을 정합니다 (5, 10, 30, 60 중 가까운 값). 없으면 null 입니다.\n"
        "- color 는 사용자가 색을 말했을 때만 정하고, 아니면 null 입니다. 급하다는 말이 있으면 priority 를 high 로 합니다.\n"
        "- 글에 없는 내용을 지어내지 마세요. 일정이나 할 일이 없으면 items 를 빈 배열로 돌려줍니다.\n"
        f"- 한 번에 최대 {MAX_ITEMS}개까지 돌려줍니다."
    )


def user_prompt(text: str) -> str:
    return text.strip()[:MAX_INPUT_CHARS]


@dataclass
class Draft:
    kind: str  # "schedule" | "todo"
    title: str
    day: date | None
    start: time | None = None
    end: time | None = None
    all_day: bool = False
    recurrence: str | None = None
    until: date | None = None
    remind: int | None = None
    color: str = "yellow"
    priority: int = PRIORITY_NORMAL
    end_day: date | None = None  # 여러 날에 걸친 일정의 마지막 날 (하루짜리면 None)

    @property
    def is_schedule(self) -> bool:
        return self.kind == "schedule"

    def to_schedule(self) -> Schedule:
        day = self.day or date.today()
        start_at = datetime.combine(day, self.start or time(0, 0))
        last = self.end_day if self.end_day and self.end_day > day else day
        end_at = None
        if self.all_day:
            if last > day:
                end_at = datetime.combine(last, time(0, 0))
        else:
            end_at = datetime.combine(last, self.end) if self.end else min(
                start_at + timedelta(hours=1), datetime.combine(day, time(23, 59)))
        return Schedule(
            title=self.title, start_at=start_at, end_at=end_at, all_day=self.all_day, color=self.color,
            recurrence=self.recurrence, recurrence_until=self.until,
            remind_before_min=None if self.all_day else self.remind,
        )

    def to_todo(self) -> Todo:
        return Todo(title=self.title, day=self.day, priority=self.priority)

    def summary(self) -> str:
        """후보 목록에 보여 줄 한 줄 설명."""
        return describe(self.to_schedule() if self.is_schedule else self.to_todo())


def describe(item: Schedule | Todo) -> str:
    """저장될 일정/할 일을 한 줄로 설명한다 (후보 목록, 수정한 뒤의 모습)."""
    if isinstance(item, Todo):
        return f"할 일 · {item.day:%m/%d} · {item.title}" if item.day else f"할 일(날짜 없음) · {item.title}"
    when = f"{item.start_at:%m/%d}"
    if item.end_at and item.end_at.date() > item.start_at.date():
        when += f"~{item.end_at:%m/%d}"
    if item.all_day:
        when += " 종일"
    else:
        when += f" {item.start_at:%H:%M}" + (f"~{item.end_at:%H:%M}" if item.end_at else "")
    if item.recurrence:
        when += {"daily": " · 매일", "weekly": " · 매주", "monthly": " · 매월"}[item.recurrence]
    return f"일정 · {when} · {item.title}"


_COMMAND_TAIL = re.compile(
    r"\s*(?:데일리\s*투두|데일리\s*to-?do|투두|to-?do|할\s*일|일정|스케줄)\s*(?:으로|로)?\s*"
    r"(?:등록|추가|저장|넣어)\s*(?:해\s*줘|해줘|해주세요|해|하기|요)?\s*[.!]?\s*$",
    re.IGNORECASE,
)


def _clean_title(title: str) -> str:
    """제목 끝에 붙은 '데일리투두 등록' 같은 요청 말을 지운다. AI 가 지시를 놓쳤을 때를 대비한 안전장치다.
    '서류 등록'처럼 종류 단어 없이 '등록'만 있는 제목은 진짜 내용일 수 있어 건드리지 않고, 다 지워져 비면 원래대로 둔다."""
    return _COMMAND_TAIL.sub("", title).strip() or title


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f"날짜를 읽을 수 없음: {value}") from None


def _parse_time(value) -> time | None:
    if value in (None, ""):
        return None
    m = _TIME.match(str(value))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"시간을 읽을 수 없음: {value}")
    return time(int(m.group(1)), int(m.group(2)))


def _nearest_reminder(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return min(REMINDER_CHOICES, key=lambda choice: abs(choice - value))


def _draft_from_item(item: dict, today: date) -> Draft:
    kind = item.get("kind")
    if kind not in ("schedule", "todo"):
        raise ValueError(f"종류를 알 수 없음: {kind}")
    title = _clean_title(str(item.get("title") or "").strip())[:100]
    if not title:
        raise ValueError("제목이 비어 있음")
    day = _parse_date(item.get("date"))
    color = item.get("color") if item.get("color") in COLORS else "yellow"
    priority = _PRIORITIES.get(item.get("priority") or "normal", PRIORITY_NORMAL)

    if kind == "todo":
        return Draft("todo", title, day, color=color, priority=priority)

    start, end = _parse_time(item.get("start_time")), _parse_time(item.get("end_time"))
    all_day = bool(item.get("all_day")) or start is None  # 시간이 없는 일정은 종일로
    if all_day:
        start = end = None
    elif end is not None and end <= start:
        end = None  # 앞뒤가 맞지 않으면 버리고 기본 길이(1시간)로 미리보기에서 보여 준다
    day = day or today
    end_day = _parse_date(item.get("end_date"))
    if end_day is not None and end_day <= day:
        end_day = None
    recurrence = item.get("recurrence") if item.get("recurrence") in ("daily", "weekly", "monthly") else None
    until = _parse_date(item.get("recurrence_until")) if recurrence else None
    if until is not None and until < day:
        until = None
    return Draft("schedule", title, day, start, end, all_day, recurrence, until,
                 None if all_day else _nearest_reminder(item.get("remind_before_min")), color, priority, end_day)


def drafts_from_response(data: dict, today: date) -> list[Draft]:
    """AI 응답(dict)을 후보 목록으로. 항목 하나가 이상해도 나머지는 살리고, 전부 이상하면 오류로 알린다."""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise AIError("bad_response", "items 목록이 없음")
    drafts, problems = [], []
    for item in items[:MAX_ITEMS]:
        try:
            drafts.append(_draft_from_item(item, today))
        except (ValueError, AttributeError, TypeError) as exc:
            problems.append(str(exc))
    if items and not drafts:
        raise AIError("bad_response", problems[0] if problems else "")
    return drafts
