from datetime import date, datetime, time

import pytest

from flowcalendar.ai import quick_add as qa
from flowcalendar.ai.errors import AIError
from flowcalendar.domain.models import PRIORITY_HIGH, validate, validate_todo

NOW = datetime(2026, 10, 28, 15, 42)  # 수요일
TODAY = NOW.date()


def item(**kw):
    base = {"kind": "schedule", "title": "팀 미팅", "date": "2026-10-29", "start_time": "15:00", "end_time": "16:00",
            "all_day": False, "recurrence": "none", "recurrence_until": None, "remind_before_min": None,
            "color": None, "priority": None}
    base.update(kw)
    return base


def parse(*items):
    return qa.drafts_from_response({"items": list(items)}, TODAY)


# ---- 프롬프트 --------------------------------------------------------------------


def test_system_prompt_contains_current_date_weekday_and_time():
    p = qa.system_prompt(NOW)
    assert "2026-10-28" in p and "수요일" in p and "15:42" in p


def test_system_prompt_tells_ai_to_resolve_day_only_dates_and_not_to_invent():
    p = qa.system_prompt(NOW)
    assert "가장 가까운" in p and "지어내지" in p and "빈 배열" in p


def test_user_prompt_is_trimmed_and_capped():
    assert qa.user_prompt("  내일 회의  ") == "내일 회의"
    assert len(qa.user_prompt("가" * 5000)) == qa.MAX_INPUT_CHARS


def test_schema_roots_are_objects_so_every_provider_accepts_them():
    assert qa.SCHEMA["type"] == "object" and qa.SCHEMA["properties"]["items"]["type"] == "array"


# ---- 일정 ------------------------------------------------------------------------------


def test_timed_schedule_roundtrip_and_conversion():
    d = parse(item())[0]
    assert (d.kind, d.title, d.day, d.start, d.end, d.all_day) == ("schedule", "팀 미팅", date(2026, 10, 29), time(15, 0), time(16, 0), False)
    s = d.to_schedule()
    assert s.start_at == datetime(2026, 10, 29, 15, 0) and s.end_at == datetime(2026, 10, 29, 16, 0)
    validate(s)


def test_missing_start_time_becomes_all_day_event():
    """'29일 팀회의'처럼 시간이 없는 일정은 종일로 만든다."""
    d = parse(item(start_time=None, end_time=None, all_day=False))[0]
    assert d.all_day and d.start is None and d.end is None
    s = d.to_schedule()
    assert s.all_day and s.end_at is None and s.remind_before_min is None
    validate(s)


def test_missing_end_time_defaults_to_one_hour_in_conversion():
    d = parse(item(end_time=None))[0]
    assert d.end is None
    assert d.to_schedule().end_at == datetime(2026, 10, 29, 16, 0)


def test_default_end_never_crosses_midnight():
    d = parse(item(start_time="23:30", end_time=None))[0]
    assert d.to_schedule().end_at == datetime(2026, 10, 29, 23, 59)


def test_end_before_start_is_dropped_not_kept():
    d = parse(item(start_time="15:00", end_time="14:00"))[0]
    assert d.end is None


def test_schedule_without_date_defaults_to_today():
    assert parse(item(date=None))[0].day == TODAY


def test_recurrence_until_and_reminder_rules():
    d = parse(item(recurrence="weekly", recurrence_until="2026-12-31", remind_before_min=12))[0]
    assert (d.recurrence, d.until, d.remind) == ("weekly", date(2026, 12, 31), 10)  # 12분 -> 가까운 값 10분
    assert parse(item(recurrence="weekly", recurrence_until="2026-10-01"))[0].until is None  # 시작일보다 이르면 버린다
    assert parse(item(recurrence="none", recurrence_until="2026-12-31"))[0].until is None
    assert parse(item(recurrence="yearly"))[0].recurrence is None  # 지원하지 않는 반복
    validate(parse(item(recurrence="daily", recurrence_until="2026-11-30"))[0].to_schedule())


@pytest.mark.parametrize("given,expected", [(3, 5), (5, 5), (8, 10), (20, 10), (25, 30), (45, 30), (50, 60), (500, 60), (0, None), (-5, None), (None, None), ("10", None), (True, None)])
def test_reminder_is_snapped_to_supported_values(given, expected):
    assert parse(item(remind_before_min=given))[0].remind == expected


def test_all_day_event_drops_reminder():
    assert parse(item(all_day=True, remind_before_min=10))[0].remind is None


def test_color_must_be_known():
    assert parse(item(color="pink"))[0].color == "pink"
    assert parse(item(color="neon"))[0].color == "yellow" and parse(item(color=None))[0].color == "yellow"


@pytest.mark.parametrize("start", ["9:05", "09:05", "09:05:30"])
def test_time_formats(start):
    assert parse(item(start_time=start, end_time=None))[0].start == time(9, 5)


# ---- 할 일 ------------------------------------------------------------------------------


def test_todo_with_date_is_daily_and_without_is_quick():
    daily = parse(item(kind="todo", title="보고서 제출", date="2026-10-30", priority="high"))[0]
    quick = parse(item(kind="todo", title="우유 사기", date=None))[0]
    assert daily.to_todo().day == date(2026, 10, 30) and daily.to_todo().priority == PRIORITY_HIGH
    assert quick.to_todo().day is None
    validate_todo(daily.to_todo()), validate_todo(quick.to_todo())


def test_todo_ignores_time_and_recurrence_fields():
    d = parse(item(kind="todo", title="전화", start_time="10:00", recurrence="daily"))[0]
    assert d.start is None and d.recurrence is None


# ---- 이상한 응답 --------------------------------------------------------------------------


def test_empty_items_is_a_valid_answer_meaning_nothing_found():
    assert parse() == []


def test_one_bad_item_does_not_throw_away_the_good_ones():
    drafts = parse(item(title="좋은 항목"), item(kind="event"), item(title="  "), item(date="내일"))
    assert [d.title for d in drafts] == ["좋은 항목"]


@pytest.mark.parametrize("bad", [item(kind="x"), item(title=""), item(date="nope"), item(start_time="25:00")])
def test_all_items_bad_is_a_bad_response_error(bad):
    with pytest.raises(AIError) as exc:
        parse(bad)
    assert exc.value.kind == "bad_response"


@pytest.mark.parametrize("data", [None, [], "x", {}, {"items": "x"}, {"items": None}])
def test_response_without_items_list_is_bad_response(data):
    with pytest.raises(AIError):
        qa.drafts_from_response(data, TODAY)


def test_item_count_is_capped():
    assert len(parse(*[item(title=f"일정{i}") for i in range(30)])) == qa.MAX_ITEMS


def test_long_title_is_trimmed():
    assert len(parse(item(title="가" * 500))[0].title) == 100


# ---- 목록 표시용 한 줄 설명 ---------------------------------------------------------------------


def test_summary_lines():
    assert parse(item())[0].summary() == "일정 · 10/29 15:00~16:00 · 팀 미팅"
    assert parse(item(start_time=None))[0].summary() == "일정 · 10/29 종일 · 팀 미팅"
    assert parse(item(end_time=None))[0].summary() == "일정 · 10/29 15:00~16:00 · 팀 미팅"  # 저장될 기본 길이(1시간)까지 보여 준다
    assert parse(item(recurrence="weekly"))[0].summary().endswith("매주 · 팀 미팅")
    assert parse(item(kind="todo", date=None, title="우유"))[0].summary() == "할 일(날짜 없음) · 우유"
    assert parse(item(kind="todo", title="우유"))[0].summary() == "할 일 · 10/29 · 우유"


# ---- 명령 단어("데일리투두 등록")는 제목에 남지 않는다 ----------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("이력서 준비 데일리투두 등록", "이력서 준비"),
    ("이력서 준비 데일리 투두 등록해줘", "이력서 준비"),
    ("이력서 준비 투두로 추가해줘", "이력서 준비"),
    ("보고서 제출 to-do 등록", "보고서 제출"),
    ("팀 회의 일정 추가", "팀 회의"),
    ("서류 등록", "서류 등록"),          # 종류 단어 없이 '등록'만 있으면 진짜 내용일 수 있다
    ("일정 등록", "일정 등록"),          # 전부 지워져 비게 되면 원래대로
    ("할 일 정리", "할 일 정리"),        # 중간에 있는 단어는 건드리지 않는다
    ("이력서 준비", "이력서 준비"),
])
def test_command_words_are_stripped_from_the_title_end(raw, expected):
    assert parse(item(kind="todo", title=raw))[0].title == expected


def test_prompt_explains_kind_words_and_command_words():
    p = qa.system_prompt(NOW)
    assert "데일리 투두" in p and "요청하는 말은 title 에 넣지 않습니다" in p and "Daily To-Do" in p


def test_the_users_example_becomes_a_daily_todo_on_the_29th():
    d = parse(item(kind="todo", title="이력서 준비", date="2026-10-29", start_time=None, end_time=None, all_day=False))[0]
    assert (d.kind, d.title, d.day) == ("todo", "이력서 준비", date(2026, 10, 29))
    assert d.to_todo().day == date(2026, 10, 29)  # 날짜가 있으니 그 날의 Daily To-Do
