from datetime import date, datetime

import pytest

from flowcalendar.ai import briefing as br
from flowcalendar.ai.errors import AIError
from flowcalendar.data import db
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.domain.models import Schedule, Todo

TODAY = date(2026, 10, 28)  # 수요일


def occ(title, start, end=None, all_day=False, day=TODAY):
    h, m = (int(x) for x in start.split(":")) if start else (0, 0)
    s = datetime(day.year, day.month, day.day, h, m)
    e = None
    if end:
        eh, em = (int(x) for x in end.split(":"))
        e = datetime(day.year, day.month, day.day, eh, em)
    sched = Schedule(title, s, e, all_day=all_day)
    from flowcalendar.domain.models import Occurrence
    return Occurrence(sched, day, s, e)


# ---- 기간 -----------------------------------------------------------------------------


def test_day_and_week_ranges_week_starts_on_sunday():
    assert br.period_range("day", TODAY) == (TODAY, TODAY)
    assert br.period_range("week", TODAY) == (date(2026, 10, 25), date(2026, 10, 31))
    assert br.period_range("week", date(2026, 10, 25)) == (date(2026, 10, 25), date(2026, 10, 31))  # 일요일
    assert br.period_range("week", date(2026, 10, 31)) == (date(2026, 10, 25), date(2026, 10, 31))  # 토요일
    with pytest.raises(ValueError):
        br.period_range("year", TODAY)


# ---- 겹침 (코드가 직접 계산) ---------------------------------------------------------------------


def titles(pairs):
    return [(a.title, b.title) for a, b in pairs]


def test_overlap_detection_basic_and_touching_is_not_overlap():
    a, b, c = occ("A", "10:00", "11:00"), occ("B", "10:30", "11:30"), occ("C", "11:00", "12:00")
    assert titles(br.find_overlaps([a, b, c])) == [("A", "B"), ("B", "C")]  # A-C 는 맞닿을 뿐이라 겹침이 아니다


def test_overlap_without_end_time_assumes_one_hour():
    assert titles(br.find_overlaps([occ("A", "10:00"), occ("B", "10:59")])) == [("A", "B")]
    assert br.find_overlaps([occ("A", "10:00"), occ("B", "11:00")]) == []


def test_all_day_events_never_overlap_and_different_days_dont():
    assert br.find_overlaps([occ("종일", None, all_day=True), occ("A", "10:00", "11:00")]) == []
    other = date(2026, 10, 29)
    assert br.find_overlaps([occ("A", "10:00", "11:00"), occ("B", "10:00", "11:00", day=other)]) == []


def test_contained_event_and_identical_times_overlap():
    assert titles(br.find_overlaps([occ("긴 회의", "09:00", "13:00"), occ("짧은 회의", "10:00", "10:30")])) == [("긴 회의", "짧은 회의")]
    assert len(br.find_overlaps([occ("A", "10:00", "11:00"), occ("B", "10:00", "11:00")])) == 1


def test_three_way_overlap_lists_every_pair_and_order_of_input_does_not_matter():
    a, b, c = occ("A", "10:00", "12:00"), occ("B", "10:30", "11:30"), occ("C", "11:00", "13:00")
    assert len(br.find_overlaps([c, a, b])) == 3


def test_overlap_works_for_recurring_expansions():
    repo = ScheduleRepository(db.connect(":memory:"))
    repo.add(Schedule("스탠드업", datetime(2026, 10, 1, 10, 0), datetime(2026, 10, 1, 10, 30), recurrence="daily"))
    repo.add(Schedule("면담", datetime(2026, 10, 28, 10, 15), datetime(2026, 10, 28, 11, 0)))
    occs = repo.list_occurrences(TODAY, TODAY)
    assert titles(br.find_overlaps(occs)) == [("스탠드업", "면담")]


# ---- 데이터 구성 ---------------------------------------------------------------------------


def test_build_data_filters_period_and_excludes_done_todos():
    occs = [occ("오늘", "10:00", "11:00"), occ("내일", "10:00", "11:00", day=date(2026, 10, 29))]
    todos = [Todo("할일", day=TODAY), Todo("끝낸 일", day=TODAY, done=True), Todo("내일 할 일", day=date(2026, 10, 29))]
    quick = [Todo("우유"), Todo("끝낸 퀵", done=True)]
    day = br.build_data("day", TODAY, occs, todos, quick)
    assert [o.title for o in day.occurrences] == ["오늘"] and [t.title for t in day.todos] == ["할일"]
    assert [t.title for t in day.quick_todos] == ["우유"]
    week = br.build_data("week", TODAY, occs, todos, quick)
    assert len(week.occurrences) == 2 and [t.title for t in week.todos] == ["할일", "내일 할 일"]


def test_titles():
    assert br.build_data("day", TODAY, [], [], []).title == "오늘 브리핑 · 10월 28일 (수)"
    assert br.build_data("week", TODAY, [], [], []).title == "이번 주 브리핑 · 10/25 ~ 10/31"


# ---- AI 로 보내는 내용 (전송 원칙) ------------------------------------------------------------------


def test_input_has_only_titles_dates_times_and_no_memo_or_done_todos():
    occs = [occ("팀 회의", "10:00", "11:00"), occ("면담", "10:30", "11:00"), occ("워크숍", None, all_day=True)]
    data = br.build_data("day", TODAY, occs, [Todo("보고서 작성", day=TODAY), Todo("끝낸 비밀 할일", day=TODAY, done=True)],
                         [Todo("우유 사기")])
    text = br.build_input(data)
    for expected in ("팀 회의", "10/28 10:00~11:00", "워크숍", "10/28 종일", "보고서 작성", "우유 사기", "[겹치는 일정]",
                     "10:00~11:00 팀 회의  ↔  10:30~11:00 면담"):
        assert expected in text, expected
    assert "끝낸 비밀 할일" not in text


def test_input_never_contains_memo_text_even_if_it_exists_in_the_database():
    conn = db.connect(":memory:")
    from flowcalendar.data.memo_repo import MemoRepository
    MemoRepository(conn).set("비밀 메모 내용 123")
    data = br.build_data("day", TODAY, [], [], [])
    assert "비밀 메모" not in br.build_input(data) and "비밀 메모" not in br.system_prompt()


def test_input_for_empty_day_says_none_and_caps_long_lists():
    text = br.build_input(br.build_data("day", TODAY, [], [], []))
    assert "[일정] 없음" in text and "[남은 할 일] 없음" in text and "[겹치는 일정] 없음" in text
    many = [occ(f"일정{i}", "08:00", "08:10") for i in range(200)]
    text = br.build_input(br.build_data("day", TODAY, many, [], []))
    # 일정 목록(60) + 겹침 목록(8 + '그 밖에' 1줄). 겹치는 쌍이 2만 개여도 보내는 글은 일정한 크기를 넘지 않는다
    assert text.count("\n- ") <= br.MAX_LINES + br.MAX_OVERLAP_LINES + 1
    assert "그 밖에 19892쌍" in text and len(text) < 8000


def test_system_prompt_forbids_inventing_and_demands_overlap_mention():
    p = br.system_prompt()
    assert "지어내지" in p and "겹치는 일정" in p


# ---- 응답/로컬 요약 ------------------------------------------------------------------------------


def test_parse_summary():
    assert br.parse_summary({"summary": "  오늘은 회의가 2개입니다.  "}) == "오늘은 회의가 2개입니다."
    assert len(br.parse_summary({"summary": "가" * 5000})) == 800
    for bad in (None, {}, {"summary": ""}, {"summary": "   "}, {"summary": 3}, [], "x"):
        with pytest.raises(AIError) as exc:
            br.parse_summary(bad)
        assert exc.value.kind == "bad_response"


def test_local_summary_and_overlap_lines():
    data = br.build_data("day", TODAY, [occ("A", "10:00", "11:00"), occ("B", "10:30", "11:30")], [Todo("x", day=TODAY)], [])
    assert br.local_summary(data) == "오늘 일정 2개, 남은 할 일 1개가 있습니다. 시간이 겹치는 일정이 1쌍 있습니다."
    assert br.overlap_lines(data) == ["10/28 10:00~11:00 A  ↔  10:30~11:30 B"]
    week = br.build_data("week", TODAY, [], [], [])
    assert br.local_summary(week).startswith("이번 주")
