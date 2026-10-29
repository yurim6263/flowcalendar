"""설정 화면의 '사용 가능한 모델 불러오기' (모델 이름이 틀렸다는 오류가 났을 때 직접 고를 수 있게 하는 기능)."""

import json

import pytest

from flowcalendar.ai import adapters
from flowcalendar.ai.errors import AIError
from flowcalendar.data import db
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.services.ai_service import AIService
from flowcalendar.services.task_runner import ImmediateRunner
from tests.test_ai_adapters import KEY, FakeTransport, _Handler, local_server  # noqa: F401  (local_server 는 fixture)
from tests.test_ai_service import FakeSecrets
from tests.test_ai_ui import DeferredRunner, pump_until, qapp  # noqa: F401  (qapp 은 fixture)


class FakeGet:
    def __init__(self, status=200, body=None):
        self.status, self.body, self.calls = status, body, []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.status, (self.body if isinstance(self.body, str) else json.dumps(self.body))


def gemini(get):
    return adapters.GeminiAdapter(KEY, "m", FakeTransport(), get_transport=get)


# ---- 제공사별 목록 읽기 ---------------------------------------------------------------------------------


def test_gemini_list_keeps_only_generate_content_models_gemini_first_without_duplicates():
    body = {"models": [
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent", "countTokens"]},
        {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemma-3-27b-it", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
    ]}
    get = FakeGet(body=body)
    assert gemini(get).list_models() == ["gemini-2.5-flash", "gemini-3-flash", "gemma-3-27b-it"]
    url, headers, _ = get.calls[0]
    assert url.startswith("https://generativelanguage.googleapis.com/v1beta/models") and KEY not in url
    assert headers == {"x-goog-api-key": KEY}  # 키는 헤더로만 보내고, 사용자 데이터는 보내지 않는다


def test_claude_and_openai_lists():
    claude = adapters.ClaudeAdapter(KEY, "m", FakeTransport(), get_transport=FakeGet(
        body={"data": [{"id": "claude-b"}, {"id": "claude-a"}, {"id": "claude-a"}, {}]}))
    assert claude.list_models() == ["claude-a", "claude-b"]
    assert claude._get.calls[0][1] == {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
    openai = adapters.OpenAIAdapter(KEY, "m", FakeTransport(), get_transport=FakeGet(body={"data": [
        {"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "o3-mini"},
        {"id": "gpt-4o-audio-preview"}, {"id": "dall-e-3"}, {"id": "gpt-4o"}]}))
    assert openai.list_models() == ["gpt-4o", "gpt-4o-mini", "o3-mini"]
    assert openai._get.calls[0][1] == {"Authorization": f"Bearer {KEY}"}


def test_openai_list_falls_back_to_all_when_nothing_looks_like_chat():
    o = adapters.OpenAIAdapter(KEY, "m", FakeTransport(), get_transport=FakeGet(body={"data": [{"id": "new-model-x"}]}))
    assert o.list_models() == ["new-model-x"]


@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (429, "quota"), (500, "server"), (400, "bad_request")])
def test_list_errors_use_the_same_mapping_and_show_the_servers_reason(status, kind):
    with pytest.raises(AIError) as exc:
        gemini(FakeGet(status, {"error": {"message": "서버가 한 말"}})).list_models()
    assert exc.value.kind == kind and "서버가 한 말" in exc.value.user_message


@pytest.mark.parametrize("bad", ["JSON 아님", "[1, 2]", json.dumps({"models": "x"})])
def test_list_with_unexpected_shape_is_bad_response(bad):
    with pytest.raises(AIError) as exc:
        gemini(FakeGet(body=bad)).list_models()
    assert exc.value.kind == "bad_response"


def test_entries_without_usable_names_give_an_empty_list_not_a_crash():
    assert gemini(FakeGet(body={"models": [{"nope": 1}]})).list_models() == []
    assert gemini(FakeGet(body={})).list_models() == []


def test_key_echoed_by_the_server_is_scrubbed():
    with pytest.raises(AIError) as exc:
        gemini(FakeGet(401, {"error": {"message": f"bad key {KEY}"}})).list_models()
    assert KEY not in exc.value.user_message


def test_error_messages_show_the_servers_reason_so_the_user_can_act_on_it():
    msg = AIError("model", "models/gemini-2.5-flash is not found for API version v1beta").user_message
    assert "gemini-2.5-flash is not found" in msg and "모델 불러오기" in msg
    assert "서버 메시지" not in AIError("bad_response", "형식 문제").user_message  # 우리 쪽 사유를 서버가 한 말처럼 쓰지 않는다
    assert "원인: ConnectionRefusedError" in AIError("network", "ConnectionRefusedError").user_message  # 진단할 수 있게 원인을 보여 준다


def test_urllib_get_returns_status_and_body_and_reports_network_errors(local_server):
    from flowcalendar.ai.http import urllib_get

    def do_get(self):
        payload = b'{"models": []}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    _Handler.do_GET = do_get
    status, text = urllib_get(local_server + "/models", {"x-test": "1"}, 5)
    assert status == 200 and json.loads(text) == {"models": []}
    with pytest.raises(AIError) as exc:
        urllib_get("http://127.0.0.1:1/", {}, 2)
    assert exc.value.kind in ("network", "timeout")


# ---- 서비스 ---------------------------------------------------------------------------------------------


def test_list_models_for_uses_given_key_no_model_and_never_touches_the_database():
    seen = {}

    class ListingAdapter:
        def __init__(self, provider, key, model, **kwargs):
            seen.update(provider=provider, key=key, model=model, kwargs=kwargs)

        def list_models(self):
            return ["m1", "m2"]

    conn = db.connect(":memory:")
    service = AIService(SettingsRepository(conn), FakeSecrets(), transport="T", get_transport="G",
                        adapter_factory=ListingAdapter)
    conn.close()  # DB 를 쓰지 않으므로 연결이 닫혀 있어도(= 다른 스레드에서도) 동작해야 한다
    assert service.list_models_for("openai", "NEWKEY") == ["m1", "m2"]
    assert seen == {"provider": "openai", "key": "NEWKEY", "model": "",
                    "kwargs": {"transport": "T", "get_transport": "G"}}


# ---- 설정 화면 -----------------------------------------------------------------------------------------


def settings_dialog(models=None, error=None, runner=None, saved_key=None):
    from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog

    conn = db.connect(":memory:")
    calls = []

    def list_models(provider, key):
        calls.append((provider, key))
        if error:
            raise error
        return models if models is not None else []

    backend = SettingsBackend(
        SettingsRepository(conn), FakeSecrets({"gemini": saved_key} if saved_key else {}), lambda: False,
        lambda v: None, lambda t: (True, ""), lambda p: None, lambda p: p, list_models=list_models,
        runner=runner if runner is not None else ImmediateRunner())
    return SettingsDialog(backend), calls


def test_choosing_a_listed_model_fills_the_model_field(qapp):
    d, calls = settings_dialog(["gemini-3-flash", "gemini-2.5-pro"], saved_key="SAVED")
    d._load_models()
    assert calls == [("gemini", "SAVED")] and d.models_btn.isEnabled()
    assert [a.text() for a in d.models_menu.actions()] == ["gemini-3-flash", "gemini-2.5-pro"]
    assert "2개" in d.message.text() and d.message.objectName() == "ok"
    d.models_menu.actions()[1].trigger()
    assert d.model.text() == "gemini-2.5-pro"
    d.models_menu.close()


def test_the_typed_but_unsaved_key_is_used_first(qapp):
    d, calls = settings_dialog(["m"], saved_key="OLD")
    d.api_key.setText("  NEW-TYPED  ")
    d._load_models()
    assert calls == [("gemini", "NEW-TYPED")]
    d.models_menu.close()


def test_without_any_key_it_asks_for_one_and_calls_nothing(qapp):
    d, calls = settings_dialog(["m"])
    d._load_models()
    assert calls == [] and "키를 먼저" in d.message.text() and d.models_btn.isEnabled()


def test_errors_show_the_servers_reason_and_empty_list_is_explained(qapp):
    d, _ = settings_dialog(error=AIError("auth", "API key not valid"), saved_key="BAD")
    d._load_models()
    assert "API key not valid" in d.message.text() and d.message.objectName() == "error" and d.models_btn.isEnabled()
    d2, _ = settings_dialog(models=[], saved_key="K")
    d2._load_models()
    assert "찾지 못했습니다" in d2.message.text()


def test_button_is_disabled_while_waiting_and_a_late_result_after_closing_is_ignored(qapp):
    runner = DeferredRunner()
    d, _ = settings_dialog(["m"], runner=runner, saved_key="K")
    d._load_models()
    assert not d.models_btn.isEnabled() and "불러오는 중" in d.message.text()
    d.reject()
    fn, ok, err = runner.jobs[0]
    ok(fn())
    assert d.models_menu is None


def test_listing_works_with_the_real_worker_thread(qapp):
    from flowcalendar.services.task_runner import TaskRunner

    d, calls = settings_dialog(["gemini-3-flash"], runner=TaskRunner(), saved_key="K")
    d._load_models()
    assert pump_until(qapp, lambda: d.models_menu is not None), d.message.text()
    assert calls == [("gemini", "K")]
    d.models_menu.close()


def test_without_runner_or_function_the_dialog_explains_instead_of_crashing(qapp):
    from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog

    conn = db.connect(":memory:")
    d = SettingsDialog(SettingsBackend(SettingsRepository(conn), FakeSecrets({"gemini": "K"}), lambda: False,
                                       lambda v: None, lambda t: (True, ""), lambda p: None, lambda p: p))
    d._load_models()
    assert "불러올 수 없습니다" in d.message.text()
