"""빠른 추가의 자동 등록(+되돌리기)과, AI 가 처리하지 못한 입력을 남겨 두는 미처리 목록."""

import sqlite3
from datetime import date, datetime

import pytest

from flowcalendar.ai.errors import AIError
from flowcalendar.ai.quick_add import describe
from flowcalendar.data import db
from flowcalendar.data.ai_inbox_repo import MAX_ITEMS, AIInboxRepository
from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services import backup
from flowcalendar.services.task_runner import ImmediateRunner
from flowcalendar.ui import ai_dialogs
from flowcalendar.ui.ai_dialogs import INBOX_ROW_GAP, INBOX_ROW_HEIGHT, NOTHING_FOUND, QuickAddDialog
from flowcalendar.ui.toast import UndoToast
from tests.test_ai_ui import ITEM, TODAY, TODO_ITEM, Env, all_titles, qapp  # noqa: F401  (qapp 은 fixture)
from tests.test_app_desktop import FakeTray


def make_env(result=None, error=None):
    e = Env(result=result if result is not None else {"items": [ITEM]}, error=error)
    e.inbox = AIInboxRepository(e.conn)
    e.window.ai_inbox = e.inbox
    return e


# ---- 저장소와 마이그레이션 -------------------------------------------------------------------------


def test_inbox_repo_dedupes_same_text_orders_newest_first_and_ignores_blank():
    repo = AIInboxRepository(db.connect(":memory:"))
    repo.add("첫째", "서버가 바쁨")
    repo.add("둘째", "시간 초과")
    repo.add("  ", "무시")
    repo.add("첫째", "한도 초과")  # 같은 글: 한 줄만 유지하고 이유/시각을 갱신
    assert [(i.text, i.reason) for i in repo.list()] == [("첫째", "한도 초과"), ("둘째", "시간 초과")]
    assert repo.count() == 2


def test_inbox_repo_delete_and_cap():
    repo = AIInboxRepository(db.connect(":memory:"))
    for n in range(MAX_ITEMS + 10):
        repo.add(f"입력 {n}", "x")
    assert repo.count() == MAX_ITEMS and repo.list()[0].text == f"입력 {MAX_ITEMS + 9}"  # 오래된 것부터 정리된다
    first = repo.list()[0]
    repo.delete(first.id)
    repo.delete_text("  입력 5  ")
    assert repo.count() == MAX_ITEMS - 1 and all(i.text != "입력 5" for i in repo.list())


def test_upgrading_an_existing_v1_database_adds_the_table_and_keeps_data(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(db.MIGRATIONS[0])  # 예전 버전(마이그레이션 1)까지만 적용된 DB 를 흉내 낸다
    raw.execute("PRAGMA user_version = 1")
    raw.execute("INSERT INTO todos (title) VALUES ('옛 데이터')")
    raw.commit()
    raw.close()
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS) >= 2
    assert conn.execute("SELECT title FROM todos").fetchall()[0][0] == "옛 데이터"
    AIInboxRepository(conn).add("새 기능", "x")
    assert AIInboxRepository(conn).count() == 1


def test_inbox_is_part_of_json_backup_roundtrip(tmp_path):
    src = db.connect(":memory:")
    AIInboxRepository(src).add("못 한 입력", "서버가 바쁨")
    file = tmp_path / "b.json"
    backup.export_to_file(src, file)
    dst = db.connect(":memory:")
    AIInboxRepository(dst).add("지워질 기존 입력", "x")
    backup.import_from_file(dst, file, tmp_path / "bk")
    assert [(i.text, i.reason) for i in AIInboxRepository(dst).list()] == [("못 한 입력", "서버가 바쁨")]


def test_old_backup_files_without_inbox_still_import(tmp_path):
    src = db.connect(":memory:")
    data = backup.export_data(src)
    del data["ai_inbox"]  # 이 기능이 생기기 전에 만든 파일
    import json

    file = tmp_path / "old.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    backup.import_from_file(db.connect(":memory:"), file, tmp_path / "bk")


# ---- 팝업: 실패한 입력은 목록에 남는다 ----------------------------------------------------------------


def dialog_for(e, auto=True):
    d = QuickAddDialog(e.window, e.service, ImmediateRunner(), inbox=e.inbox, auto_register=auto)
    d.show()
    return d


def convert(d, text):
    d.input.setText(text)
    d._convert()


@pytest.mark.parametrize("kind,label", [("server", "서버가 바쁨"), ("timeout", "시간 초과"), ("quota", "한도 초과"),
                                        ("model", "모델 오류"), ("auth", "API 키 오류"), ("network", "연결 실패"),
                                        ("bad_response", "응답을 이해하지 못함")])
def test_failed_input_is_kept_in_the_list_with_a_short_reason(qapp, kind, label):
    e = make_env(error=AIError(kind, "상세"))
    d = dialog_for(e)
    convert(d, "29일 이력서 준비")
    assert [(i.text, i.reason) for i in e.inbox.list()] == [("29일 이력서 준비", label)]
    assert len(d.inbox_rows) == 1 and "처리하지 못한 입력 (1)" in d.inbox_title.text()
    assert not d.inbox_area.isHidden() and "상세" in d.status.text() or kind == "network"  # 전체 오류도 그대로 보인다


def test_nothing_found_is_also_kept(qapp):
    e = make_env(result={"items": []})
    d = dialog_for(e)
    convert(d, "안녕하세요")
    assert [(i.text, i.reason) for i in e.inbox.list()] == [("안녕하세요", NOTHING_FOUND)]


def test_same_failed_text_stays_one_row_and_success_removes_it(qapp):
    e = make_env(error=AIError("server", "high demand"))
    d = dialog_for(e)
    convert(d, "29일 이력서 준비")
    convert(d, "29일 이력서 준비")
    assert e.inbox.count() == 1 and len(d.inbox_rows) == 1
    e.adapters[-1].error, e.adapters[-1].result = None, {"items": [TODO_ITEM]}
    e.error, e.result = None, {"items": [TODO_ITEM]}
    convert(d, "29일 이력서 준비")
    assert d.outcome == "drafts" and e.inbox.count() == 0 and d.source_text == "29일 이력서 준비"


def test_success_does_not_touch_other_items(qapp):
    e = make_env()
    e.inbox.add("다른 입력", "시간 초과")
    d = dialog_for(e)
    convert(d, "29일 팀회의")
    assert d.outcome == "drafts" and [i.text for i in e.inbox.list()] == ["다른 입력"]


def test_memo_mode_never_uses_the_list(qapp):
    e = make_env(error=AIError("server", "x"))
    e.inbox.add("기존", "x")
    d = QuickAddDialog(e.window, e.service, ImmediateRunner(), memo_text="29일 팀회의", inbox=e.inbox)
    d.show()
    d._convert()
    assert [i.text for i in e.inbox.list()] == ["기존"] and d.inbox_area.isHidden() and d.inbox is None


def test_dialog_without_inbox_still_works(qapp):
    e = make_env(error=AIError("server", "x"))
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d.show()
    convert(d, "x")
    assert d.inbox_area.isHidden() and d.status.text()


# ---- 목록 모양: 3개만 보이고 나머지는 스크롤 ----------------------------------------------------------------


def three_rows_height():
    return 3 * INBOX_ROW_HEIGHT + 2 * INBOX_ROW_GAP + 4


def test_list_shows_at_most_three_rows_and_scrolls_beyond_that(qapp):
    e = make_env()
    for n in range(8):
        e.inbox.add(f"못 한 입력 {n}", "서버가 바쁨")
    d = dialog_for(e)
    qapp.processEvents()
    assert len(d.inbox_rows) == 8 and d.inbox_area.height() == three_rows_height()
    assert d.inbox_area.verticalScrollBar().maximum() > 0  # 나머지는 스크롤로 본다
    assert "(8)" in d.inbox_title.text()


@pytest.mark.parametrize("count,rows", [(1, 1), (2, 2), (3, 3), (4, 3), (50, 3)])
def test_list_height_grows_only_up_to_three_rows(qapp, count, rows):
    e = make_env()
    for n in range(count):
        e.inbox.add(f"입력 {n}", "x")
    d = dialog_for(e)
    assert d.inbox_area.height() == rows * INBOX_ROW_HEIGHT + (rows - 1) * INBOX_ROW_GAP + 4


def test_dialog_height_does_not_depend_on_how_many_items_are_waiting(qapp):
    e3, e30 = make_env(), make_env()
    for n in range(3):
        e3.inbox.add(f"입력 {n}", "x")
    for n in range(30):
        e30.inbox.add(f"입력 {n}", "x")
    d3, d30 = dialog_for(e3), dialog_for(e30)
    qapp.processEvents()
    assert abs(d3.height() - d30.height()) <= 2  # 팝업이 길어지지 않는다


def test_empty_list_and_empty_status_take_no_space(qapp):
    e = make_env()
    d = dialog_for(e)
    assert d.inbox_title.isHidden() and d.inbox_area.isHidden() and d.status.isHidden()  # 입력창 아래가 휑하지 않다
    d._set_status("안내")
    assert not d.status.isHidden()
    d._set_status("")
    assert d.status.isHidden()


def test_long_inputs_are_elided_in_the_row_but_complete_in_the_tooltip(qapp):
    e = make_env()
    long_text = "아주 긴 입력 " * 20
    e.inbox.add(long_text, "x")
    d = dialog_for(e)
    label = d.inbox_rows[0].findChildren(type(d.status))[0]
    assert len(label.text()) <= 34 and label.toolTip() == long_text.strip()


# ---- 목록의 동작 ------------------------------------------------------------------------------------------------


def test_row_retry_runs_the_conversion_with_that_text_and_clears_it_on_success(qapp):
    e = make_env(result={"items": [TODO_ITEM]})
    e.inbox.add("29일 이력서 준비", "서버가 바쁨")
    d = dialog_for(e)
    d.inbox_rows[0].retry_btn.click()
    assert e.calls[-1]["user"] == "29일 이력서 준비"
    assert d.outcome == "drafts" and d.source_text == "29일 이력서 준비" and e.inbox.count() == 0


def test_row_retry_that_fails_again_keeps_the_row_with_the_new_reason(qapp):
    e = make_env(error=AIError("timeout", "30초"))
    e.inbox.add("29일 이력서 준비", "서버가 바쁨")
    d = dialog_for(e)
    d.inbox_rows[0].retry_btn.click()
    assert [(i.text, i.reason) for i in e.inbox.list()] == [("29일 이력서 준비", "시간 초과")] and len(d.inbox_rows) == 1


def test_row_manual_hands_the_text_to_manual_entry_and_removes_it(qapp):
    e = make_env()
    e.inbox.add("29일 이력서 준비", "x")
    d = dialog_for(e)
    d.inbox_rows[0].manual_btn.click()
    assert d.outcome == "manual" and d.manual_text == "29일 이력서 준비" and e.inbox.count() == 0


def test_row_delete_removes_only_that_row(qapp):
    e = make_env()
    e.inbox.add("남길 것", "x")
    e.inbox.add("지울 것", "x")
    d = dialog_for(e)
    row = next(r for r in d.inbox_rows if r.item.text == "지울 것")
    row.delete_btn.click()
    assert [i.text for i in e.inbox.list()] == ["남길 것"] and len(d.inbox_rows) == 1 and d.outcome is None


def test_retry_buttons_are_disabled_while_waiting(qapp):
    e = make_env()
    e.inbox.add("입력", "x")
    d = dialog_for(e)
    d._set_busy(True)
    assert not d.inbox_rows[0].retry_btn.isEnabled()
    d._set_busy(False)
    assert d.inbox_rows[0].retry_btn.isEnabled()


def test_note_tells_whether_results_are_registered_immediately(qapp):
    e = make_env()
    notes = lambda d: " ".join(lab.text() for lab in d.findChildren(type(d.status)))  # noqa: E731
    assert "바로 등록되고" in notes(dialog_for(e, auto=True)) and "되돌릴 수 있습니다" in notes(dialog_for(e, auto=True))
    assert "확인한 뒤에만 저장" in notes(dialog_for(e, auto=False))


# ---- 자동 등록 + 되돌리기 -------------------------------------------------------------------------------------------


def fake_dialog(monkeypatch, e, text="29일 팀회의", outcome="drafts"):
    def fake_exec(self):
        self.outcome, self.source_text = outcome, text
        self.drafts = e.service.parse_text(text) if outcome == "drafts" else []

    monkeypatch.setattr(QuickAddDialog, "exec", fake_exec)


def test_auto_register_is_on_by_default_and_saves_without_any_confirmation_form(qapp, monkeypatch):
    e = make_env(result={"items": [ITEM, TODO_ITEM]})
    assert e.window.auto_register_enabled() is True
    forms = []
    monkeypatch.setattr(e.window, "_edit_candidate", lambda item: forms.append(item))
    fake_dialog(monkeypatch, e)
    got = []
    e.window.ai_registered.connect(got.append)
    e.window.open_quick_add()
    assert forms == []  # 확인 폼이 열리지 않았다
    assert sorted(all_titles(e)) == ["보고서 제출", "팀회의"]
    assert got and "AI가 2개를 등록했어요" in got[0] and "외" in got[0]
    toast = e.window._toast
    assert isinstance(toast, UndoToast) and toast.timer.interval() == 5000 and toast.timer.isActive()


def test_undo_removes_everything_the_ai_just_registered(qapp, monkeypatch):
    e = make_env(result={"items": [ITEM, TODO_ITEM]})
    e.window.todo_repo.add(Todo("원래 있던 할 일", day=TODAY))
    fake_dialog(monkeypatch, e)
    e.window.open_quick_add()
    assert len(all_titles(e)) == 3
    e.window._toast.undo()
    assert all_titles(e) == ["원래 있던 할 일"]  # AI 가 만든 것만 사라지고 원래 데이터는 그대로


def test_toast_reports_the_registered_item(qapp, monkeypatch):
    e = make_env(result={"items": [TODO_ITEM]})
    fake_dialog(monkeypatch, e)
    got = []
    e.window.ai_registered.connect(got.append)
    e.window.open_quick_add()
    assert got == ["AI가 1개를 등록했어요 · 할 일 · 10/30 · 보고서 제출"]


def test_duplicates_are_skipped_and_reported(qapp, monkeypatch):
    e = make_env(result={"items": [ITEM, TODO_ITEM]})
    e.window.repo.add(Schedule("팀회의", datetime(2026, 10, 29, 0, 0), all_day=True))
    fake_dialog(monkeypatch, e)
    got = []
    e.window.ai_registered.connect(got.append)
    e.window.open_quick_add()
    assert sorted(all_titles(e)) == ["보고서 제출", "팀회의"] and all_titles(e).count("팀회의") == 1  # 중복 안 만듦
    assert "이미 있는 1개는 건너뜀" in got[0] and "1개를 등록했어요" in got[0]


def test_all_duplicates_registers_nothing_and_offers_no_undo(qapp, monkeypatch):
    e = make_env(result={"items": [TODO_ITEM]})
    e.window.todo_repo.add(Todo("보고서 제출", day=date(2026, 10, 30)))
    fake_dialog(monkeypatch, e)
    got = []
    e.window.ai_registered.connect(got.append)
    e.window.open_quick_add()
    assert got == ["이미 같은 항목이 있어 등록하지 않았어요"] and all_titles(e).count("보고서 제출") == 1
    assert e.window._toast._on_undo is None  # 되돌릴 것이 없으니 되돌리기 버튼도 없다


def test_a_failed_item_is_kept_in_the_list_and_the_rest_are_still_registered(qapp, monkeypatch):
    e = make_env(result={"items": [ITEM, TODO_ITEM]})
    real_add = e.window.repo.add

    def failing_add(schedule):
        raise ValueError("종료 시간이 시작 시간보다 빠릅니다.")

    monkeypatch.setattr(e.window.repo, "add", failing_add)
    fake_dialog(monkeypatch, e, text="29일 팀회의와 보고서")
    got = []
    e.window.ai_registered.connect(got.append)
    e.window.open_quick_add()
    assert all_titles(e) == ["보고서 제출"]  # 할 일은 등록되고
    assert [(i.text, i.reason) for i in e.inbox.list()] == [("29일 팀회의와 보고서", "등록하지 못함: 종료 시간이 시작 시간보다 빠릅니다.")]
    assert "1개를 등록했어요" in got[0] and "1개는 등록하지 못함" in got[0]
    monkeypatch.setattr(e.window.repo, "add", real_add)


def test_turning_auto_register_off_restores_confirmation_flow(qapp, monkeypatch):
    e = make_env(result={"items": [ITEM]})
    e.settings.set_bool("ai_auto_register", False)
    shown = []
    monkeypatch.setattr(e.window, "_review_drafts", lambda drafts, single_form: shown.append((len(drafts), single_form)))
    fake_dialog(monkeypatch, e)
    e.window.open_quick_add()
    assert shown == [(1, True)] and all_titles(e) == []  # 확인 전에는 저장되지 않는다


def test_memo_conversion_always_keeps_the_confirmation_list(qapp, monkeypatch):
    e = make_env(result={"items": [ITEM]})
    assert e.window.auto_register_enabled()  # 자동 등록이 켜져 있어도
    shown = []
    monkeypatch.setattr(e.window, "_review_drafts", lambda drafts, single_form: shown.append(single_form))
    monkeypatch.setattr(QuickAddDialog, "exec", lambda self: setattr(self, "outcome", "drafts") or setattr(
        self, "drafts", e.service.parse_text("x")))
    e.window.convert_memo_selection("29일 팀회의")
    assert shown == [False] and all_titles(e) == []  # 메모 변환은 목록으로 확인한다


def test_registered_toast_message_is_clipped_for_long_titles(qapp, monkeypatch):
    long_item = {**TODO_ITEM, "title": "아주 긴 제목 " * 15}
    e = make_env(result={"items": [long_item]})
    fake_dialog(monkeypatch, e)
    got = []
    e.window.ai_registered.connect(got.append)
    e.window.open_quick_add()
    assert len(got[0]) < 90 and "…" in got[0]


# ---- 앱 연결(창이 가려졌을 때 알림) 과 설정 ---------------------------------------------------------------------------


def test_app_shows_a_tray_notification_only_when_the_window_is_not_active(qapp, tmp_path):
    from flowcalendar import app as app_module

    c = app_module.FlowCalendarApp(db.connect(":memory:"), tmp_path, tray=FakeTray(), register_hotkey=False)
    assert c.window.ai_inbox is not None  # 앱이 미처리 목록 저장소를 연결해 준다
    c.window.ai_registered.emit("AI가 1개를 등록했어요")
    assert ("Flow Calendar", "AI가 1개를 등록했어요") in c.tray.messages  # 보이는 창이 없으니 알림으로
    c.tray.messages.clear()
    c.window.isActiveWindow = lambda: True
    c.window.ai_registered.emit("보이는 중")
    assert c.tray.messages == []
    c.scheduler.stop()


def test_settings_dialog_has_the_auto_register_toggle_default_on(qapp):
    from flowcalendar.data.settings_repo import SettingsRepository
    from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog
    from tests.test_ai_service import FakeSecrets

    conn = db.connect(":memory:")
    backend = SettingsBackend(SettingsRepository(conn), FakeSecrets(), lambda: False, lambda v: None,
                              lambda t: (True, ""), lambda p: None, lambda p: p)
    d = SettingsDialog(backend)
    assert d.auto_register.isChecked() and "되돌릴 수 있음" in d.auto_register.text()
    d.auto_register.setChecked(False)
    d._on_save()
    assert backend.settings.get_bool("ai_auto_register") is False
    assert SettingsDialog(backend).auto_register.isChecked() is False


def test_undo_toast_without_undo_has_hidden_button_and_ignores_clicks(qapp):
    from PySide6.QtWidgets import QPushButton, QWidget

    host = QWidget()
    host.resize(400, 200)
    host.show()
    toast = UndoToast(host, "안내만 있는 토스트", None)
    button = toast.findChild(QPushButton)
    assert button.isHidden()
    toast.undo()
    assert toast.undone is False
    toast.dismiss()


# ---- 표시 중에 목록을 다시 만들어도 줄이 포개지지 않는다 (실제 화면에서 겪은 문제) ----------------------------


def row_tops(d):
    return sorted(r.geometry().top() for r in d.inbox_rows)


def test_rebuilding_the_list_while_the_dialog_is_open_keeps_rows_apart(qapp):
    e = make_env(error=AIError("server", "high demand"))
    for n in range(5):
        e.inbox.add(f"입력 {n}", "서버가 바쁨")
    d = dialog_for(e)
    qapp.processEvents()
    convert(d, "새 입력")  # 실패 -> 목록을 다시 만든다 (표시 중)
    qapp.processEvents()
    tops = row_tops(d)
    assert len(tops) == 6
    steps = [b - a for a, b in zip(tops, tops[1:])]
    assert all(step == INBOX_ROW_HEIGHT + INBOX_ROW_GAP for step in steps), steps  # 54 + 6 = 60 간격
    assert all(r.height() == INBOX_ROW_HEIGHT for r in d.inbox_rows)


def test_old_rows_are_removed_from_the_layout_not_just_hidden(qapp):
    e = make_env(error=AIError("server", "x"))
    e.inbox.add("하나", "x")
    d = dialog_for(e)
    for n in range(4):
        convert(d, f"입력 {n}")  # 실패할 때마다 다시 만든다
    assert len(d.inbox_rows) == 5
    assert d._inbox_layout.count() == len(d.inbox_rows) + 1  # 줄들 + 맨 끝의 stretch 하나. 숨은 줄이 남아 쌓이지 않는다


def test_deleting_rows_shrinks_the_list_without_overlap(qapp):
    e = make_env()
    for n in range(6):
        e.inbox.add(f"입력 {n}", "x")
    d = dialog_for(e)
    qapp.processEvents()
    d.inbox_rows[0].delete_btn.click()
    d.inbox_rows[0].delete_btn.click()
    qapp.processEvents()
    steps = [b - a for a, b in zip(row_tops(d), row_tops(d)[1:])]
    assert len(d.inbox_rows) == 4 and all(s == INBOX_ROW_HEIGHT + INBOX_ROW_GAP for s in steps)
    assert d.inbox_area.height() == three_rows_height()


def test_last_row_deleted_hides_the_whole_section(qapp):
    e = make_env()
    e.inbox.add("마지막", "x")
    d = dialog_for(e)
    d.inbox_rows[0].delete_btn.click()
    assert d.inbox_area.isHidden() and d.inbox_title.isHidden() and d.inbox_rows == []
