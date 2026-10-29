"""오늘/이번 주 브리핑. 시간 겹침은 코드가 직접 계산하고(틀리면 안 되는 부분), AI 는 요약 문장만 만든다.

AI 에 보내는 것: 대상 기간의 일정·남은 할 일의 제목과 날짜·시간뿐이다. 메모 본문, 완료한 할 일은 보내지 않는다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from flowcalendar.ai.errors import AIError
from flowcalendar.domain.models import Occurrence, Todo

DEFAULT_LENGTH = timedelta(hours=1)  # 종료 시간이 없는 일정이 차지한다고 보는 시간 (일정 팝업의 기본값과 같다)
MAX_LINES = 60
MAX_OVERLAP_LINES = 8  # 일정이 많이 겹치면 쌍의 수가 제곱으로 늘어난다. 보내는 글과 화면 모두 여기서 끊는다
WEEKDAY_SHORT = ("월", "화", "수", "목", "금", "토", "일")

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}


def period_range(period: str, today: date) -> tuple[date, date]:
    if period == "day":
        return today, today
    if period == "week":  # 달력과 같게 일요일에 시작한다
        start = today - timedelta(days=(today.weekday() + 1) % 7)
        return start, start + timedelta(days=6)
    raise ValueError(f"알 수 없는 기간: {period}")


def _span(occ: Occurrence) -> tuple[datetime, datetime]:
    return occ.start_at, occ.end_at or occ.start_at + DEFAULT_LENGTH


def find_overlaps(occurrences: list[Occurrence]) -> list[tuple[Occurrence, Occurrence]]:
    """시간이 겹치는 일정 쌍. 종일 일정은 제외하고, 끝과 시작이 딱 맞닿는 것(10-11시, 11-12시)은 겹침이 아니다."""
    timed = sorted((o for o in occurrences if not o.all_day), key=lambda o: _span(o)[0])
    pairs = []
    for i, a in enumerate(timed):
        a_start, a_end = _span(a)
        for b in timed[i + 1:]:
            b_start, b_end = _span(b)
            if b_start >= a_end:
                break  # 시작 순으로 정렬돼 있어서 이후는 모두 겹치지 않는다
            if a_start < b_end and b_start < a_end:
                pairs.append((a, b))
    return pairs


@dataclass
class BriefingData:
    period: str
    start: date
    end: date
    occurrences: list[Occurrence]
    todos: list[Todo]  # 기간 안의 Daily To-Do 중 아직 안 끝낸 것
    quick_todos: list[Todo] = field(default_factory=list)  # 날짜 없는 To-Do 중 아직 안 끝낸 것
    overlaps: list[tuple[Occurrence, Occurrence]] = field(default_factory=list)

    @property
    def title(self) -> str:
        if self.period == "day":
            return f"오늘 브리핑 · {self.start.month}월 {self.start.day}일 ({WEEKDAY_SHORT[self.start.weekday()]})"
        return f"이번 주 브리핑 · {self.start.month}/{self.start.day} ~ {self.end.month}/{self.end.day}"


def build_data(period: str, today: date, occurrences: list[Occurrence], todos: list[Todo],
               quick_todos: list[Todo]) -> BriefingData:
    start, end = period_range(period, today)
    occs = [o for o in occurrences if o.first_day <= end and o.last_day >= start]  # 여러 날 일정은 기간에 걸치면 포함
    return BriefingData(
        period, start, end, occs,
        [t for t in todos if t.day is not None and start <= t.day <= end and not t.done],
        [t for t in quick_todos if t.day is None and not t.done],
        find_overlaps(occs),
    )


def _when(occ: Occurrence) -> str:
    if occ.is_multiday:
        if occ.all_day:
            return f"{occ.first_day:%m/%d}~{occ.last_day:%m/%d} 종일"
        return f"{occ.start_at:%m/%d %H:%M}~{occ.end_at:%m/%d %H:%M}"
    if occ.all_day:
        return f"{occ.date:%m/%d} 종일"
    start, end = _span(occ)
    return f"{occ.date:%m/%d} {start:%H:%M}~{end:%H:%M}"


def overlap_lines(data: BriefingData, limit: int = MAX_OVERLAP_LINES) -> list[str]:
    """화면에 보여 줄 겹침 안내 (코드가 계산한 값). limit 을 넘으면 마지막 줄에 나머지 개수를 적는다."""
    lines = []
    for a, b in data.overlaps[:limit]:
        (a_s, a_e), (b_s, b_e) = _span(a), _span(b)
        lines.append(f"{a.date:%m/%d} {a_s:%H:%M}~{a_e:%H:%M} {a.title}  ↔  {b_s:%H:%M}~{b_e:%H:%M} {b.title}")
    if len(data.overlaps) > limit:
        lines.append(f"그 밖에 {len(data.overlaps) - limit}쌍")
    return lines


def system_prompt() -> str:
    return (
        "당신은 개인 일정 도우미입니다. 아래 목록을 보고 한국어로 2~4문장으로 짧게 요약해 JSON 으로 답합니다.\n"
        "- 목록에 있는 내용만 말하고, 없는 일정이나 할 일을 지어내지 마세요.\n"
        "- '겹치는 일정' 항목이 있으면 반드시 그 사실을 알려 주세요. 없으면 겹침을 언급하지 마세요.\n"
        "- 일정이 하나도 없으면 여유로운 날(주)이라고 간단히 말해 주세요."
    )


def build_input(data: BriefingData) -> str:
    """AI 로 보내는 글. 제목과 날짜·시간만 들어간다 (메모 본문, 완료한 할 일은 넣지 않는다)."""
    lines = [f"기간: {data.start:%Y-%m-%d} ({WEEKDAY_SHORT[data.start.weekday()]})"
             + ("" if data.start == data.end else f" ~ {data.end:%Y-%m-%d} ({WEEKDAY_SHORT[data.end.weekday()]})")]
    lines.append("[일정]" + ("" if data.occurrences else " 없음"))
    lines += [f"- {_when(o)} {o.title}" for o in data.occurrences[:MAX_LINES]]
    lines.append("[남은 할 일]" + ("" if data.todos else " 없음"))
    lines += [f"- {t.day:%m/%d} {t.title}" for t in data.todos[:MAX_LINES]]
    if data.quick_todos:
        lines.append("[날짜 없는 할 일]")
        lines += [f"- {t.title}" for t in data.quick_todos[:10]]
    lines.append("[겹치는 일정]" + ("" if data.overlaps else " 없음"))
    lines += [f"- {line}" for line in overlap_lines(data)]
    return "\n".join(lines)


def parse_summary(data: dict) -> str:
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        raise AIError("bad_response", "요약이 비어 있음")
    return summary.strip()[:800]


def local_summary(data: BriefingData) -> str:
    """AI 를 못 쓸 때 보여 줄, 코드로 만든 간단한 요약."""
    scope = "오늘" if data.period == "day" else "이번 주"
    text = f"{scope} 일정 {len(data.occurrences)}개, 남은 할 일 {len(data.todos)}개가 있습니다."
    if data.overlaps:
        text += f" 시간이 겹치는 일정이 {len(data.overlaps)}쌍 있습니다."
    return text
