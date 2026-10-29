import threading
import time
from datetime import date, datetime

import pytest
from PySide6.QtWidgets import QApplication

from flowcalendar.ai import briefing
from flowcalendar.ai.errors import AIError
from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services.ai_service import AIService, find_duplicates, model_setting_key
from flowcalendar.services.secrets import SecretError
from flowcalendar.services.task_runner import ImmediateRunner, TaskRunner

NOW = datetime(2026, 10, 28, 15, 42)


class FakeSecrets:
    def __init__(self, keys=None, broken=False):
        self.keys, self.broken = dict(keys or {}), broken

    def has(self, p):
        if self.broken:
            raise SecretError("깨짐")
        return p in self.keys

    def get(self, p):
        if self.broken:
            raise SecretError("깨짐")
        return self.keys.get(p)


class FakeAdapter:
    """실제 호출 없이, 받은 것을 기록하고 정해 둔 결과를 돌려주는 가짜 어댑터."""

    def __init__(self, provider, key, model, result=None, error=None):
        self.provider, self.key, self.model, self.result, self.error = provider, key, model, result, error
        self.calls = []

    def complete_json(self, system, user, schema, name="result"):
        self.calls.append({"system": system, "user": user, "schema": schema, "name": name})
        if self.error:
            raise self.error
        return self.result

    def list_models(self):
        return []  # 대신 쓸 모델이 없다 -> 모델 오류는 그대로 사용자에게 보인다


def make_service(keys=None, result=None, error=None, settings=None, broken=False):
    conn = db.connect(":memory:")
    s = SettingsRepository(conn)
    for k, v in (settings or {}).items():
        s.set(k, v)
    created = []

    def factory(provider, key, model, **kwargs):
        adapter = FakeAdapter(provider, key, model, result, error)
        created.append(adapter)
        return adapter

    service = AIService(s, FakeSecrets(keys, broken), clock=lambda: NOW, adapter_factory=factory)
    service.created = created
    service.conn = conn
    return service


ITEM = {"kind": "schedule", "title": "팀회의", "date": "2026-10-29", "start_time": None, "end_time": None,
        "all_day": True, "recurrence": "none", "recurrence_until": None, "remind_before_min": None,
        "color": None, "priority": None}


# ---- 설정/키 --------------------------------------------------------------------------


def test_has_key_follows_selected_provider_and_survives_broken_credential_store():
    assert make_service({"gemini": "k"}).has_key() is True
    assert make_service({}).has_key() is False
    assert make_service({"gemini": "k"}, settings={"ai_provider": "claude"}).has_key() is False
    assert make_service({"claude": "k"}, settings={"ai_provider": "claude"}).has_key() is True
    assert make_service({"gemini": "k"}, broken=True).has_key() is False  # 앱이 죽지 않고 AI 만 숨긴다


def test_provider_and_model_defaults_and_overrides():
    s = make_service({"gemini": "k"})
    assert s.provider() == "gemini" and s.model() == "gemini-2.5-flash"
    s2 = make_service({"openai": "k"}, settings={"ai_provider": "openai", model_setting_key("openai"): "  my-model  "})
    assert s2.model() == "my-model"
    s3 = make_service({"openai": "k"}, settings={"ai_provider": "openai", model_setting_key("openai"): "   "})
    assert s3.model() == "gpt-4o-mini"  # 공백만 있으면 기본값


# ---- 변환 ----------------------------------------------------------------------------------


def test_parse_text_sends_date_context_and_user_text_and_returns_drafts():
    s = make_service({"gemini": "KEY"}, result={"items": [ITEM]})
    drafts = s.parse_text("  29일 팀회의  ")
    call = s.created[0].calls[0]
    assert "2026-10-28" in call["system"] and "수요일" in call["system"]
    assert call["user"] == "29일 팀회의" and call["name"] == "calendar_items"
    assert s.created[0].key == "KEY" and s.created[0].model == "gemini-2.5-flash"
    assert [(d.title, d.day, d.all_day) for d in drafts] == [("팀회의", date(2026, 10, 29), True)]


def test_blank_text_never_calls_ai():
    s = make_service({"gemini": "KEY"}, result={"items": [ITEM]})
    assert s.parse_text("   ") == [] and s.created == []


def test_no_key_raises_no_key_without_creating_adapter():
    s = make_service({})
    with pytest.raises(AIError) as exc:
        s.parse_text("내일 회의")
    assert exc.value.kind == "no_key" and s.created == []


def test_ai_errors_propagate_unchanged_and_bad_items_become_bad_response():
    s = make_service({"gemini": "k"}, error=AIError("quota", "limit"))
    with pytest.raises(AIError) as exc:
        s.parse_text("x")
    assert exc.value.kind == "quota"
    s2 = make_service({"gemini": "k"}, result={"items": [{"kind": "??", "title": "x"}]})
    with pytest.raises(AIError) as exc:
        s2.parse_text("x")
    assert exc.value.kind == "bad_response"


# ---- 요약 + 전송 원칙 -----------------------------------------------------------------------------


def test_summarize_sends_only_titles_and_times_never_memo():
    s = make_service({"gemini": "k"}, result={"summary": "오늘은 회의가 있습니다."})
    MemoRepository(s.conn).set("절대 보내면 안 되는 비밀 메모")
    sched = ScheduleRepository(s.conn)
    sched.add(Schedule("팀 회의", datetime(2026, 10, 28, 10, 0), datetime(2026, 10, 28, 11, 0)))
    todos = TodoRepository(s.conn)
    todos.add(Todo("보고서", day=date(2026, 10, 28)))
    done = todos.add(Todo("끝낸 일", day=date(2026, 10, 28)))
    t = todos.get(done)
    t.done = True
    todos.update(t)
    data = briefing.build_data("day", date(2026, 10, 28), sched.list_occurrences(date(2026, 10, 28), date(2026, 10, 28)),
                               todos.list_daily(date(2026, 10, 28), date(2026, 10, 28)), todos.list_quick())
    assert s.summarize(data) == "오늘은 회의가 있습니다."
    sent = s.created[0].calls[0]
    everything = sent["system"] + sent["user"] + str(sent["schema"])
    assert "팀 회의" in everything and "보고서" in everything
    assert "비밀 메모" not in everything and "끝낸 일" not in everything


def test_api_key_is_never_part_of_the_prompt():
    s = make_service({"gemini": "TOPSECRETKEY"}, result={"items": []})
    s.parse_text("내일 회의")
    c = s.created[0].calls[0]
    assert "TOPSECRETKEY" not in c["system"] + c["user"] + str(c["schema"])


# ---- 중복 후보 ---------------------------------------------------------------------------------------


def test_find_duplicates_for_schedule_todo_and_quick_todo():
    conn = db.connect(":memory:")
    sched, todos = ScheduleRepository(conn), TodoRepository(conn)
    sched.add(Schedule("팀회의", datetime(2026, 10, 29, 0, 0), all_day=True))
    todos.add(Todo("보고서 제출", day=date(2026, 10, 30)))
    todos.add(Todo("우유 사기"))
    s = make_service({"gemini": "k"}, result={"items": [
        ITEM,
        {**ITEM, "title": " 팀회의 ", "date": "2026-10-30"},            # 날짜가 다르면 중복이 아니다
        {**ITEM, "kind": "todo", "title": "보고서 제출", "date": "2026-10-30"},
        {**ITEM, "kind": "todo", "title": "우유 사기", "date": None},
        {**ITEM, "kind": "todo", "title": "빵 사기", "date": None},
    ]})
    drafts = s.parse_text("여러 줄")
    assert find_duplicates(drafts, sched, todos) == [True, False, True, True, False]


def test_duplicate_title_match_ignores_case_and_spaces():
    conn = db.connect(":memory:")
    sched, todos = ScheduleRepository(conn), TodoRepository(conn)
    sched.add(Schedule("Team Meeting", datetime(2026, 10, 29, 0, 0), all_day=True))
    s = make_service({"gemini": "k"}, result={"items": [{**ITEM, "title": "  team meeting "}]})
    assert find_duplicates(s.parse_text("x"), sched, todos) == [True]


# ---- 비동기 실행 -------------------------------------------------------------------------------------------


def test_immediate_runner_calls_success_or_error():
    got = []
    ImmediateRunner().run(lambda: 3, got.append, lambda e: got.append(("err", e)))
    ImmediateRunner().run(lambda: 1 / 0, got.append, lambda e: got.append(("err", type(e).__name__)))
    assert got == [3, ("err", "ZeroDivisionError")]


def test_task_runner_works_off_main_thread_and_calls_back_on_main_thread():
    app = QApplication.instance() or QApplication([])
    runner = TaskRunner()
    main = threading.get_ident()
    seen = {}

    def work():
        seen["work_thread"] = threading.get_ident()
        time.sleep(0.05)
        return "결과"

    runner.run(work, lambda r: seen.update(ok=r, cb_thread=threading.get_ident()), lambda e: seen.update(err=e))
    runner.run(lambda: (_ for _ in ()).throw(AIError("quota")), lambda r: seen.update(bad=r),
               lambda e: seen.update(err_kind=e.kind, err_thread=threading.get_ident()))
    deadline = time.time() + 5
    while time.time() < deadline and not ({"ok", "err_kind"} <= set(seen)):
        app.processEvents()
        time.sleep(0.01)
    assert seen["ok"] == "결과" and seen["err_kind"] == "quota"
    assert seen["work_thread"] != main  # 화면이 멈추지 않도록 작업은 다른 스레드에서
    assert seen["cb_thread"] == main and seen["err_thread"] == main  # 결과는 화면 스레드에서 받는다
    assert "bad" not in seen and runner._callbacks == {}
