"""AI 오류가 길어도 팝업이 잘리지 않고, 모델/키 오류에는 '설정 열기'가 바로 보이는지."""

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from flowcalendar.ai import adapters
from flowcalendar.ai.errors import AIError
from flowcalendar.services.task_runner import ImmediateRunner
from flowcalendar.ui.ai_dialogs import QuickAddDialog
from tests.test_ai_adapters import KEY, FakeTransport
from tests.test_ai_ui import Env, qapp  # noqa: F401  (qapp 은 fixture)

LONG_REASON = ("This model models/gemini-2.5-flash is no longer available to new users. "
               "Please update your code to use a newer model for the latest features and improvements.")


def failing_dialog(qapp, error):
    e = Env(error=error)
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d.show()
    qapp.processEvents()
    d.input.setText("29일 이력서 준비 데일리투두 등록")
    d._convert()
    qapp.processEvents()
    return e, d


def note_label(d):
    return next(lab for lab in d.findChildren(QLabel) if lab.objectName() == "note")


def test_long_server_reason_is_shown_in_full_and_dialog_grows_instead_of_overlapping(qapp):
    e, d = failing_dialog(qapp, AIError("model", LONG_REASON))
    assert "no longer available to new users" in d.status.text()
    assert "latest features and improvements" in d.status.text()  # 끝까지 보인다 (잘리지 않는다)
    assert d.status.geometry().bottom() < note_label(d).geometry().top()  # 아래 안내 글과 겹치지 않는다
    layout = d.layout()
    assert d.height() >= layout.totalHeightForWidth(d.width())  # 내용이 들어갈 만큼 커졌다


def test_dialog_does_not_shrink_back_when_a_short_message_replaces_a_long_one(qapp):
    e, d = failing_dialog(qapp, AIError("model", LONG_REASON))
    tall = d.height()
    d._set_status("문장을 입력하세요.", error=True)
    assert d.height() == tall  # 줄었다 늘었다 하며 흔들리지 않는다


def test_status_text_can_be_selected_so_the_user_can_copy_the_server_message(qapp):
    e, d = failing_dialog(qapp, AIError("model", LONG_REASON))
    assert d.status.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


@pytest.mark.parametrize("kind", ["model", "auth", "no_key"])
def test_settings_button_is_the_primary_action_for_model_and_key_errors(qapp, kind):
    e, d = failing_dialog(qapp, AIError(kind, "상세"))
    assert not d.settings_btn.isHidden() and d.settings_btn.objectName() == "primary"
    assert d.manual_btn.objectName() == "" and d.manual_btn.isEnabled() and d.convert_btn.isEnabled()


@pytest.mark.parametrize("kind", ["server", "network", "quota"])
def test_temporary_errors_make_retry_the_primary_action(qapp, kind):
    e, d = failing_dialog(qapp, AIError(kind, "상세"))
    assert d.convert_btn.objectName() == "primary" and d.convert_btn.isDefault()  # Enter 로도 다시 시도
    assert d.manual_btn.objectName() == "" and d.settings_btn.objectName() == ""


def test_server_overload_also_offers_choosing_another_model_but_other_temporary_errors_do_not(qapp):
    assert not failing_dialog(qapp, AIError("server", "high demand"))[1].settings_btn.isHidden()
    assert failing_dialog(qapp, AIError("network"))[1].settings_btn.isHidden()
    assert failing_dialog(qapp, AIError("quota"))[1].settings_btn.isHidden()


@pytest.mark.parametrize("kind", ["bad_response", "bad_request"])
def test_unclear_errors_keep_manual_entry_as_the_primary_action(qapp, kind):
    e, d = failing_dialog(qapp, AIError(kind, "상세"))
    assert d.settings_btn.isHidden() and d.manual_btn.objectName() == "primary" and d.manual_btn.isDefault()


def test_button_emphasis_follows_the_latest_error(qapp):
    e, d = failing_dialog(qapp, AIError("model", "x"))
    assert not d.settings_btn.isHidden() and d.settings_btn.isDefault()
    d._on_error(AIError("quota"))
    assert d.settings_btn.isHidden() and d.convert_btn.objectName() == "primary" and not d.settings_btn.isDefault()
    d._on_error(AIError("bad_response"))
    assert d.manual_btn.objectName() == "primary" and d.convert_btn.objectName() == ""


def test_clicking_settings_closes_the_dialog_with_settings_outcome(qapp):
    e, d = failing_dialog(qapp, AIError("auth", "bad key"))
    d.settings_btn.click()
    assert d.outcome == "settings" and d.result() == d.DialogCode.Accepted
    assert e.window.ai_service is not None  # (창 쪽 처리는 아래 테스트)


def test_main_window_opens_settings_when_dialog_asks_for_it(qapp, monkeypatch):
    e = Env()
    opened = []
    e.window.settings_requested.connect(lambda: opened.append(1))

    def fake_exec(self):
        self.outcome = "settings"

    monkeypatch.setattr(QuickAddDialog, "exec", fake_exec)
    e.window.open_quick_add()
    assert opened == [1]
    opened.clear()
    e.window.convert_memo_selection("29일 팀회의")  # 메모에서 변환할 때도 같다
    assert opened == [1]


def test_settings_button_is_disabled_while_waiting_for_the_ai(qapp):
    e = Env()
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d._set_busy(True)
    assert not d.settings_btn.isEnabled()
    d._set_busy(False)
    assert d.settings_btn.isEnabled()


# ---- 서버 메시지는 충분히 길게 가져온다 -------------------------------------------------------------------------


def test_adapter_keeps_up_to_500_chars_of_the_servers_reason():
    reason = "가" * 450
    t = FakeTransport(404, {"error": {"message": reason}})
    with pytest.raises(AIError) as exc:
        adapters.GeminiAdapter(KEY, "m", t).complete_json("s", "u", {"type": "object", "properties": {}})
    assert exc.value.kind == "model" and exc.value.detail == reason
    t2 = FakeTransport(404, {"error": {"message": "나" * 900}})
    with pytest.raises(AIError) as exc2:
        adapters.GeminiAdapter(KEY, "m", t2).complete_json("s", "u", {"type": "object", "properties": {}})
    assert len(exc2.value.detail) == 500


def test_the_real_gemini_retired_model_message_maps_to_model_error():
    body = {"error": {"code": 404, "message": LONG_REASON, "status": "NOT_FOUND"}}
    with pytest.raises(AIError) as exc:
        adapters.GeminiAdapter(KEY, "gemini-2.5-flash", FakeTransport(404, json.dumps(body))).complete_json(
            "s", "u", {"type": "object", "properties": {}})
    assert exc.value.kind == "model" and "newer model" in exc.value.user_message
