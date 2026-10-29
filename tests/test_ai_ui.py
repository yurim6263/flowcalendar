from datetime import date, datetime

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from flowcalendar import app as app_module
from flowcalendar.ai.errors import AIError
from flowcalendar.data import db
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services.ai_service import AIService
from flowcalendar.services.task_runner import ImmediateRunner
from flowcalendar.ui import main_window as mw
from flowcalendar.ui import tokens
from flowcalendar.ui.ai_dialogs import DraftListDialog, QuickAddDialog
from flowcalendar.ui.briefing_card import BriefingCard
from flowcalendar.ui.dialogs import ScheduleDialog, TodoDialog
from flowcalendar.ui.main_window import MainWindow
from tests.test_ai_service import FakeAdapter, FakeSecrets
from tests.test_app_desktop import FakeTray

TODAY = date(2026, 10, 28)
NOW = datetime(2026, 10, 28, 15, 42)
ITEM = {"kind": "schedule", "title": "팀회의", "date": "2026-10-29", "start_time": None, "end_time": None,
        "all_day": True, "recurrence": "none", "recurrence_until": None, "remind_before_min": None,
        "color": None, "priority": None}
TODO_ITEM = {**ITEM, "kind": "todo", "title": "보고서 제출", "date": "2026-10-30"}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.STYLESHEET)
    return app


class Env:
    """가짜 어댑터/키/실행기로 꾸린 창. 실제 AI 호출은 없다."""

    def __init__(self, keys=None, result=None, error=None):
        self.conn = db.connect(":memory:")
        self.settings = SettingsRepository(self.conn)
        self.secrets = FakeSecrets(keys if keys is not None else {"gemini": "KEY"})
        self.adapters = []
        self.result, self.error = result, error

        def factory(provider, key, model, **kw):
            adapter = FakeAdapter(provider, key, model, self.result, self.error)
            self.adapters.append(adapter)
            return adapter

        self.service = AIService(self.settings, self.secrets, clock=lambda: NOW, adapter_factory=factory)
        self.window = MainWindow(ScheduleRepository(self.conn), TodoRepository(self.conn), MemoRepository(self.conn),
                                 today=TODAY)
        self.window.set_ai(self.service, ImmediateRunner())

    @property
    def calls(self):
        return [c for a in self.adapters for c in a.calls]


@pytest.fixture
def env(qapp):
    return Env(result={"items": [ITEM]})


def all_titles(e):
    start, end = date(2026, 10, 1), date(2026, 12, 31)
    return ([o.title for o in e.window.repo.list_occurrences(start, end)]
            + [t.title for t in e.window.todo_repo.list_daily(start, end)]
            + [t.title for t in e.window.todo_repo.list_quick()])


# ---- 키가 없으면 AI 화면은 모두 숨는다 ----------------------------------------------------


def test_ai_ui_hidden_without_key_and_shown_with_key(qapp):
    e = Env(keys={})
    assert e.window.ai_btn.isHidden() and e.window.memo_card.ai_btn.isHidden() and not e.window.ai_available
    e.secrets.keys["gemini"] = "KEY"
    e.window.refresh_ai()
    assert not e.window.ai_btn.isHidden() and not e.window.memo_card.ai_btn.isHidden() and e.window.ai_available
    e.secrets.keys.clear()
    e.window.refresh_ai()
    assert e.window.ai_btn.isHidden() and e.window.memo_card.ai_btn.isHidden()


def test_without_key_calendar_works_and_ai_entry_points_do_nothing(qapp):
    e = Env(keys={})
    e.window.open_quick_add()
    e.window.convert_memo_selection("29일 팀회의")
    e.window.show_briefing("day")
    assert e.adapters == [] and e.window._briefing_card is None
    e.window.todo_repo.add(Todo("평소처럼", day=TODAY))
    e.window.refresh()  # 다른 기능은 정상


def test_menu_has_ai_items_only_with_key(qapp):
    e = Env(keys={})
    e.window.open_main_menu()
    assert "ai_quick" not in e.window._menu.items and "ai_briefing" not in e.window._menu.items
    e.window._menu.close()
    e.secrets.keys["gemini"] = "KEY"
    e.window.open_main_menu()
    assert {"ai_quick", "ai_briefing"} <= set(e.window._menu.items)
    e.window._menu.close()


# ---- 빠른 추가 팝업 -------------------------------------------------------------------------


def test_quick_add_success_returns_drafts_and_does_not_save_anything(env):
    d = QuickAddDialog(env.window, env.service, ImmediateRunner())
    d.input.setText("29일 팀회의")
    d._convert()
    assert d.outcome == "drafts" and [x.title for x in d.drafts] == ["팀회의"]
    assert d.result() == d.DialogCode.Accepted
    assert all_titles(env) == []  # 확인 전에는 아무것도 저장되지 않는다 (FR-AI-005)


def test_quick_add_empty_input_does_not_call_ai(env):
    d = QuickAddDialog(env.window, env.service, ImmediateRunner())
    d._convert()
    assert "입력하세요" in d.status.text() and env.adapters == [] and d.outcome is None


@pytest.mark.parametrize("kind,needle", [("quota", "한도"), ("network", "인터넷"), ("auth", "키"), ("model", "모델"),
                                         ("bad_response", "이해하지 못했습니다")])
def test_quick_add_errors_are_shown_not_hidden_and_offer_manual_entry(qapp, kind, needle):
    e = Env(error=AIError(kind, "상세"))
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d.input.setText("내일 회의")
    d._convert()
    assert needle in d.status.text() and d.status.objectName() == "error"
    assert d.outcome is None and d.result() != d.DialogCode.Accepted  # 닫히지 않고 안내한다
    assert d.convert_btn.isEnabled() and d.manual_btn.isEnabled() and d.input.isEnabled()
    assert d.manual_btn.text() == "직접 입력으로 전환" and d.convert_btn.text() == "다시 시도"


def test_unexpected_exception_is_also_reported(qapp):
    e = Env(error=RuntimeError("boom"))
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d.input.setText("x")
    d._convert()
    assert "RuntimeError" in d.status.text() and d.convert_btn.isEnabled()


def test_retry_after_error_can_succeed(qapp):
    e = Env(error=AIError("quota"))
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d.input.setText("29일 팀회의")
    d._convert()
    e.error, e.adapters[0].error, e.adapters[0].result = None, None, {"items": [ITEM]}
    e.result = {"items": [ITEM]}
    d._convert()
    assert d.outcome == "drafts"


def test_nothing_found_keeps_dialog_open_with_hint(qapp):
    e = Env(result={"items": []})
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d.input.setText("안녕")
    d._convert()
    assert "찾지 못했어요" in d.status.text() and d.outcome is None and d.convert_btn.isEnabled()


def test_manual_switch_keeps_what_the_user_typed(env):
    d = QuickAddDialog(env.window, env.service, ImmediateRunner())
    d.input.setText("  29일 팀회의  ")
    d._manual()
    assert d.outcome == "manual" and d.manual_text == "29일 팀회의" and env.adapters == []


class DeferredRunner:
    """결과를 나중에 직접 전달해서 '기다리는 동안 창을 닫은' 상황을 만든다."""

    def __init__(self):
        self.jobs = []

    def run(self, fn, ok, err):
        self.jobs.append((fn, ok, err))
        return len(self.jobs)


def test_result_arriving_after_dialog_closed_is_ignored(env):
    runner = DeferredRunner()
    d = QuickAddDialog(env.window, env.service, runner)
    d.input.setText("29일 팀회의")
    d._convert()
    assert not d.convert_btn.isEnabled() and "읽는 중" in d.status.text()  # 기다리는 동안 중복 요청을 막는다
    d._convert()
    assert len(runner.jobs) == 1
    d.reject()
    fn, ok, err = runner.jobs[0]
    ok(fn())  # 늦게 도착
    assert d.outcome is None and d.result() == d.DialogCode.Rejected


def test_memo_mode_shows_selection_preview_and_starts_automatically(env, qapp):
    text = "29일 팀회의\n내일 우유 사기"
    d = QuickAddDialog(env.window, env.service, ImmediateRunner(), memo_text=text)
    assert d.input is None and "선택한 메모" in d.preview.text() and "29일 팀회의" in d.preview.text()
    d.show()
    for _ in range(5):
        qapp.processEvents()
    assert d.outcome == "drafts" and env.calls[0]["user"] == text
    assert any("선택한 메모 내용뿐" in lab.text() for lab in d.findChildren(type(d.status)))  # 전송 범위 안내


# ---- 후보 목록 -------------------------------------------------------------------------------


def make_items():
    return [Schedule("팀회의", datetime(2026, 10, 29, 0, 0), all_day=True), Todo("보고서 제출", day=TODAY), Todo("우유 사기")]


def test_list_dialog_unchecks_duplicates_and_registers_only_checked(env):
    d = DraftListDialog(env.window, make_items(), [False, True, False], notice="안내", edit_item=lambda i: None)
    assert [c.isChecked() for c in d.checks] == [True, False, True]
    assert d.register_btn.text() == "2개 등록" and [type(i).__name__ for i in d.chosen()] == ["Schedule", "Todo"]
    d.checks[0].setChecked(False)
    d.checks[2].setChecked(False)
    assert d.register_btn.text() == "0개 등록" and not d.register_btn.isEnabled() and d.chosen() == []


def test_list_dialog_edit_replaces_item_and_updates_text(env):
    d = DraftListDialog(env.window, make_items(), [False] * 3, notice="n",
                        edit_item=lambda item: Todo("고친 제목", day=TODAY) if isinstance(item, Todo) and item.day else None)
    assert "보고서 제출" in d.labels[1].text()
    d._edit(1)
    assert "고친 제목" in d.labels[1].text() and d.chosen()[1].title == "고친 제목"
    d._edit(0)  # 수정 취소(None)면 그대로
    assert "팀회의" in d.labels[0].text()


# ---- 저장은 사용자가 확인한 뒤에만 ------------------------------------------------------------------


def test_single_draft_is_saved_only_if_user_saves_the_prefilled_form(env, monkeypatch):
    drafts = env.service.parse_text("29일 팀회의")
    monkeypatch.setattr(env.window, "_edit_candidate", lambda item: None)  # 사용자가 폼을 닫음
    env.window._review_drafts(drafts, single_form=True)
    assert all_titles(env) == []
    monkeypatch.setattr(env.window, "_edit_candidate", lambda item: Schedule("수정한 제목", item.start_at, all_day=True))
    env.window._review_drafts(drafts, single_form=True)
    assert all_titles(env) == ["수정한 제목"]  # 사용자가 고친 내용으로 저장된다


def test_list_review_saves_only_checked_items(env, monkeypatch):
    drafts = env.service.parse_text("x")
    env.result = {"items": [ITEM, TODO_ITEM, {**TODO_ITEM, "title": "우유 사기", "date": None}]}
    env.adapters[0].result = env.result
    drafts = env.service.parse_text("x")

    def fake_exec(self):
        self.checks[1].setChecked(False)  # 사용자가 두 번째를 해제
        return self.DialogCode.Accepted

    monkeypatch.setattr(DraftListDialog, "exec", fake_exec)
    env.window._review_drafts(drafts, single_form=False)
    assert sorted(all_titles(env)) == ["우유 사기", "팀회의"]
    # 취소하면 아무것도 저장되지 않는다
    before = all_titles(env)
    monkeypatch.setattr(DraftListDialog, "exec", lambda self: self.DialogCode.Rejected)
    env.window._review_drafts(drafts, single_form=False)
    assert all_titles(env) == before


def test_memo_conversion_never_changes_the_memo_text(env, monkeypatch):
    env.window.memo_card.edit.set_content("29일 팀회의\n내일 우유 사기")
    before = env.window.memo_card.edit.content()
    monkeypatch.setattr(QuickAddDialog, "exec", lambda self: self.done(1) or None)
    monkeypatch.setattr(DraftListDialog, "exec", lambda self: self.DialogCode.Accepted)
    env.window.convert_memo_selection("29일 팀회의")
    assert env.window.memo_card.edit.content() == before and env.window.memo_repo.get() == ""  # 저장도 새로 안 됨


def test_prefilled_forms_for_candidates_are_unsaved_drafts_with_notice(env):
    sched = ScheduleDialog(env.window, draft=Schedule("팀회의", datetime(2026, 10, 29, 14, 0), datetime(2026, 10, 29, 15, 0),
                                                      remind_before_min=10, recurrence="weekly", color="pink"),
                           notice=MainWindow.AI_DRAFT_NOTICE)
    assert sched.occurrence is None  # 저장된 일정이 아니라 새 일정으로 저장된다
    s = sched.schedule()
    assert (s.id, s.title, s.remind_before_min, s.recurrence, s.color) == (None, "팀회의", 10, "weekly", "pink")
    assert s.start_at == datetime(2026, 10, 29, 14, 0) and s.end_at == datetime(2026, 10, 29, 15, 0)
    assert any("AI가 만든 초안" in lab.text() for lab in sched.findChildren(type(sched.error)))
    todo = TodoDialog(env.window, day=date(2026, 10, 30), todo=Todo("보고서", priority=2, day=date(2026, 10, 30)))
    assert todo.todo().title == "보고서" and todo.todo().priority == 2 and todo.todo().day == date(2026, 10, 30)


def test_initial_title_prefills_manual_entry_forms(env):
    assert ScheduleDialog(env.window, day=TODAY, initial_title="29일 팀회의").title_edit.text() == "29일 팀회의"
    assert TodoDialog(env.window, day=None, initial_title="우유").title_edit.text() == "우유"


# ---- 열기/수동 전환 연결 ----------------------------------------------------------------------------


def test_open_quick_add_routes_outcomes(env, monkeypatch):
    env.settings.set_bool("ai_auto_register", False)  # 확인 후 저장하는 방식 (자동 등록은 test_ai_auto.py)
    seen = {}
    monkeypatch.setattr(env.window, "_review_drafts", lambda drafts, single_form: seen.update(r=(len(drafts), single_form)))
    monkeypatch.setattr(env.window, "on_add", lambda day, initial_title="": seen.update(m=(day, initial_title)))

    def run_dialog(outcome):
        def fake_exec(self):
            self.outcome, self.drafts, self.manual_text = outcome, env.service.parse_text("x"), "직접 쓴 글"
        monkeypatch.setattr(QuickAddDialog, "exec", fake_exec)
        env.window.open_quick_add()

    run_dialog("drafts")
    assert seen["r"] == (1, True)
    run_dialog("manual")
    assert seen["m"] == (TODAY, "직접 쓴 글")
    seen.clear()
    run_dialog(None)  # 취소
    assert seen == {}


def test_hotkey_opens_quick_add_only_with_key(qapp, tmp_path, monkeypatch):
    opened = []
    c = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path, tray=FakeTray(), register_hotkey=False)
    monkeypatch.setattr(c.window, "open_quick_add", lambda: opened.append(1))
    c.hotkey.triggered.emit()
    assert opened == [] and c.window.isVisible()  # 키가 없으면 창만 앞으로
    monkeypatch.setattr(type(c.window), "ai_available", property(lambda self: True))
    c.hotkey.triggered.emit()
    assert opened == [1]
    c.scheduler.stop()


# ---- 메모의 AI 버튼 (선택한 부분만) ------------------------------------------------------------------


def select_lines(edit, first, last=None):
    """메모의 first~last 줄(0부터)을 선택한다."""
    from PySide6.QtGui import QTextCursor

    doc = edit.document()
    cursor = QTextCursor(doc.findBlockByNumber(first))
    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
    end_block = doc.findBlockByNumber(first if last is None else last)
    cursor.setPosition(end_block.position() + end_block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cursor)


def test_memo_ai_button_enabled_only_with_selection_and_emits_selected_text(env):
    card = env.window.memo_card
    card.edit.set_content("29일 팀회의\n내일 우유 사기\n비밀 메모 줄")
    got = []
    card.convert_requested.disconnect(env.window.convert_memo_selection)  # 진짜 모달 팝업이 열리지 않게 끊는다
    card.convert_requested.connect(got.append)
    assert not card.ai_btn.isEnabled() and "먼저 선택" in card.ai_btn.toolTip()
    card.ai_btn.click()
    assert got == []
    select_lines(card.edit, 0, 1)
    assert card.ai_btn.isEnabled()
    card.ai_btn.click()
    assert got == ["29일 팀회의\n내일 우유 사기"]  # 선택한 두 줄만, 줄바꿈은 그대로


def test_only_selected_memo_lines_reach_the_ai_provider(env, monkeypatch):
    """전송 원칙: 메모의 나머지(비밀 메모 줄)는 AI 제공사로 가지 않는다."""
    card = env.window.memo_card
    card.edit.set_content("29일 팀회의\n내일 우유 사기\n비밀 메모 줄")
    select_lines(card.edit, 0)
    monkeypatch.setattr(QuickAddDialog, "exec", lambda self: self._convert())  # 모달 대신 바로 변환을 실행
    monkeypatch.setattr(DraftListDialog, "exec", lambda self: self.DialogCode.Rejected)
    card.ai_btn.click()
    sent = " ".join(c["system"] + c["user"] + str(c["schema"]) for c in env.calls)
    assert "29일 팀회의" in sent
    assert "비밀 메모" not in sent and "우유 사기" not in sent


def test_memo_manual_fallback_uses_first_selected_line_as_title(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(env.window, "on_add", lambda day, initial_title="": seen.update(t=initial_title))

    def fake_exec(self):
        self.outcome = "manual"

    monkeypatch.setattr(QuickAddDialog, "exec", fake_exec)
    env.window.convert_memo_selection("\n  29일 팀회의  \n내일 우유")
    assert seen["t"] == "29일 팀회의"


def test_blank_memo_selection_is_ignored(env):
    env.window.convert_memo_selection("   \n ")
    assert env.adapters == []


# ---- 브리핑 카드 ---------------------------------------------------------------------------------------


def add_overlapping_events(e):
    sched = e.window.repo
    sched.add(Schedule("팀 회의", datetime(2026, 10, 28, 10, 0), datetime(2026, 10, 28, 11, 0)))
    sched.add(Schedule("면담", datetime(2026, 10, 28, 10, 30), datetime(2026, 10, 28, 11, 30)))


def test_briefing_shows_ai_summary_and_locally_computed_overlaps(qapp):
    e = Env(result={"summary": "오늘은 회의가 2개이고 시간이 겹칩니다."})
    add_overlapping_events(e)
    e.window.show_briefing("day")
    card = e.window._briefing_card
    assert card.isVisible() and card.summary.text() == "오늘은 회의가 2개이고 시간이 겹칩니다."
    assert card.heading.text() == "오늘 브리핑 · 10월 28일 (수)" and "일정 2개" in card.counts.text()
    assert not card.overlap_title.isHidden() and "팀 회의  ↔" in card.overlap_text.text()  # 겹침은 코드가 계산해서 보여 준다
    assert not card.notice.isVisible() and card.day_btn.isChecked() and not card.week_btn.isChecked()
    card.close()


def test_briefing_without_overlap_hides_overlap_section(qapp):
    e = Env(result={"summary": "여유로운 날입니다."})
    e.window.show_briefing("day")
    assert e.window._briefing_card.overlap_title.isHidden()
    e.window._briefing_card.close()


def test_briefing_error_shows_local_summary_and_the_reason(qapp):
    e = Env(error=AIError("quota"))
    add_overlapping_events(e)
    e.window.show_briefing("day")
    card = e.window._briefing_card
    assert "일정 2개" in card.summary.text() and "겹치는 일정이 1쌍" in card.summary.text()  # AI 없이도 유용한 요약
    assert card.notice.isVisible() and "한도" in card.notice.text()  # 실패 이유는 숨기지 않는다
    assert "팀 회의" in card.overlap_text.text()
    card.close()


def test_week_period_and_stale_results_are_dropped(qapp):
    e = Env(result={"summary": "요약"})
    runner = DeferredRunner()
    e.window.task_runner = runner
    e.window.show_briefing("day")
    e.window.show_briefing("week")  # 사용자가 곧바로 이번 주로 바꿈
    card = e.window._briefing_card
    (fn1, ok1, _), (fn2, ok2, _) = runner.jobs
    ok1("오늘 요약(늦게 도착)")
    assert card.summary.text() == "AI가 요약하는 중입니다…"  # 낡은 결과는 버린다
    ok2("이번 주 요약")
    assert card.summary.text() == "이번 주 요약" and card.week_btn.isChecked() and card.heading.text().startswith("이번 주")
    card.close()
    ok2("닫은 뒤 도착")  # 닫힌 카드는 건드리지 않는다
    assert card.summary.text() == "이번 주 요약"


def test_briefing_card_buttons_request_period_and_timer_pauses_on_hover(qapp):
    card = BriefingCard(auto_close_ms=500)
    got = []
    card.period_requested.connect(got.append)
    card.week_btn.click()
    card.day_btn.click()
    assert got == ["week", "day"]
    card.show()
    assert card._timer.isActive() and card._timer.interval() == 500
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QEnterEvent
    card.enterEvent(QEnterEvent(card.rect().center(), card.rect().center(), card.rect().center()))
    assert not card._timer.isActive()  # 읽는 중에는 닫히지 않는다
    card.leaveEvent(QEvent(QEvent.Type.Leave))
    assert card._timer.isActive()
    card.hide()
    assert not card._timer.isActive()


def test_briefing_card_does_not_steal_focus_and_is_placed_on_screen(qapp):
    from PySide6.QtCore import Qt

    card = BriefingCard()
    assert card.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) and not card.isModal()
    card.show_loading(__import__("flowcalendar.ai.briefing", fromlist=["x"]).build_data("day", TODAY, [], [], []))
    area = qapp.primaryScreen().availableGeometry()
    assert area.contains(card.geometry().topLeft()) and card.geometry().right() <= area.right()
    card.close()


# ---- 시작 시 브리핑 / 설정 ------------------------------------------------------------------------------


def test_startup_briefing_respects_key_and_setting(qapp, tmp_path, monkeypatch):
    conn = db.connect(":memory:")
    c = app_module.FlowCalendarApp(conn, tmp_path, tray=FakeTray(), register_hotkey=False)
    shown = []
    monkeypatch.setattr(c.window, "show_briefing", lambda period="day": shown.append(period))
    assert c.maybe_show_briefing() is False  # 키 없음
    monkeypatch.setattr(type(c.window), "ai_available", property(lambda self: True))
    assert c.maybe_show_briefing() is True and shown == ["day"]
    c.settings.set_bool("ai_briefing", False)  # 설정에서 끔
    assert c.maybe_show_briefing() is False and shown == ["day"]
    c.scheduler.stop()


def test_briefing_is_scheduled_only_when_requested(qapp, tmp_path):
    c = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path, tray=FakeTray(), register_hotkey=False)
    assert c.ai is not None and c.window.ai_service is c.ai
    c.scheduler.stop()


def test_settings_dialog_saves_model_per_provider_and_briefing_toggle(qapp):
    from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog

    conn = db.connect(":memory:")
    backend = SettingsBackend(SettingsRepository(conn), FakeSecrets(), lambda: False, lambda v: None,
                              lambda t: (True, ""), lambda p: None, lambda p: p)
    d = SettingsDialog(backend)
    assert d.model.text() == "" and "gemini-2.5-flash" in d.model.placeholderText() and d.briefing.isChecked()
    d.model.setText("  gemini-custom  ")
    d.briefing.setChecked(False)
    d._on_save()
    s = backend.settings
    assert s.get("ai_model_gemini") == "gemini-custom" and s.get_bool("ai_briefing") is False
    d2 = SettingsDialog(backend)
    assert d2.model.text() == "gemini-custom" and not d2.briefing.isChecked()
    d2.provider.setCurrentIndex(d2.provider.findData("claude"))  # 제공사를 바꾸면 그 제공사의 모델/기본값을 보여 준다
    assert d2.model.text() == "" and "claude-haiku-5-5" in d2.model.placeholderText()
    d2.model.setText("claude-x")
    d2._on_save()
    assert s.get("ai_model_claude") == "claude-x" and s.get("ai_model_gemini") == "gemini-custom"


def test_settings_still_carries_free_tier_notice(qapp):
    from flowcalendar.ai.providers import FREE_TIER_NOTICE
    from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog

    conn = db.connect(":memory:")
    d = SettingsDialog(SettingsBackend(SettingsRepository(conn), FakeSecrets(), lambda: False, lambda v: None,
                                       lambda t: (True, ""), lambda p: None, lambda p: p))
    assert any(lab.text() == FREE_TIER_NOTICE for lab in d.findChildren(type(d.message)))


# ---- 진짜 스레드 실행기 + SQLite 설정 (같은 스레드 가짜 실행기로는 잡히지 않던 오류) -----------------------


def pump_until(qapp, condition, seconds=8):
    import time

    end = time.time() + seconds
    while time.time() < end and not condition():
        qapp.processEvents()
        time.sleep(0.01)
    return condition()


def test_quick_add_works_with_the_real_worker_thread_and_sqlite_settings(qapp):
    """별도 스레드에서 SQLite 설정을 읽으면 ProgrammingError 가 난다. 설정/키 읽기는 화면 스레드에서 끝내야 한다."""
    from flowcalendar.services.task_runner import TaskRunner

    e = Env(result={"items": [TODO_ITEM]})
    runner = TaskRunner()
    d = QuickAddDialog(e.window, e.service, runner)
    d.input.setText("29일 이력서 준비 데일리투두 등록")
    d._convert()
    assert pump_until(qapp, lambda: d.outcome is not None or "오류" in d.status.text()), d.status.text()
    assert d.outcome == "drafts", d.status.text()
    assert "ProgrammingError" not in d.status.text()
    assert e.calls[0]["user"] == "29일 이력서 준비 데일리투두 등록"


def test_briefing_works_with_the_real_worker_thread_and_sqlite_settings(qapp):
    from flowcalendar.services.task_runner import TaskRunner

    e = Env(result={"summary": "오늘은 여유로운 날입니다."})
    e.window.task_runner = TaskRunner()
    e.window.show_briefing("day")
    card = e.window._briefing_card
    assert pump_until(qapp, lambda: card.summary.text() == "오늘은 여유로운 날입니다."), card.summary.text()
    assert not card.notice.isVisible()
    card.close()


def test_missing_key_is_reported_in_the_dialog_without_starting_a_thread(qapp):
    e = Env(keys={"gemini": "k"})
    d = QuickAddDialog(e.window, e.service, DeferredRunner())
    e.secrets.keys.clear()  # 팝업을 연 뒤 키를 지운 경우
    d.input.setText("내일 회의")
    d._convert()
    assert "키" in d.status.text() and d.status.objectName() == "error" and d.convert_btn.isEnabled()
    assert d.runner.jobs == []


def test_ai_call_object_hides_the_key_in_repr(qapp):
    e = Env(keys={"gemini": "SUPERSECRET"})
    assert "SUPERSECRET" not in repr(e.service.prepare())
