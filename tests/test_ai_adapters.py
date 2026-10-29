import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from flowcalendar.ai import adapters
from flowcalendar.ai.errors import AIError
from flowcalendar.ai.http import urllib_transport
from flowcalendar.ai.schema import to_gemini, to_json_schema, to_openai_strict

KEY = "SECRET-KEY-123"

SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["schedule", "todo"]},
        "title": {"type": "string"},
        "date": {"type": "string", "nullable": True},
        "remind": {"type": "integer", "nullable": True},
        "color": {"type": "string", "enum": ["pink", "blue"], "nullable": True},
        "all_day": {"type": "boolean"},
    },
    "required": ["kind", "title", "all_day"],
}


class FakeTransport:
    """실제 네트워크를 쓰지 않고, 보낸 요청을 기록하고 정해 둔 응답을 돌려준다."""

    def __init__(self, status=200, body=None):
        self.status, self.body = status, body
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        text = self.body if isinstance(self.body, str) else json.dumps(self.body)
        return self.status, text


# ---- 스키마 변환 -----------------------------------------------------------------------


def test_gemini_schema_uses_uppercase_types_and_keeps_nullable():
    g = to_gemini(SCHEMA)
    assert g["type"] == "OBJECT"
    assert g["properties"]["date"] == {"type": "STRING", "nullable": True}
    assert g["properties"]["all_day"]["type"] == "BOOLEAN"


def test_json_schema_turns_nullable_into_type_arrays_and_adds_null_to_enum():
    j = to_json_schema(SCHEMA)
    assert j["properties"]["date"]["type"] == ["string", "null"]
    assert j["properties"]["color"]["type"] == ["string", "null"] and None in j["properties"]["color"]["enum"]
    assert "nullable" not in json.dumps(j)
    assert j["required"] == ["kind", "title", "all_day"]  # 원래 required 는 그대로


def test_openai_strict_requires_every_property_and_forbids_extras():
    o = to_openai_strict(SCHEMA)
    assert o["required"] == list(SCHEMA["properties"]) and o["additionalProperties"] is False
    assert o["properties"]["remind"]["type"] == ["integer", "null"]


def test_nested_objects_and_nullable_objects_are_converted_too():
    nested = {"type": "object", "properties": {
        "inner": {"type": "object", "nullable": True, "properties": {"x": {"type": "string", "nullable": True}}},
        "items": {"type": "array", "items": {"type": "object", "properties": {"y": {"type": "integer"}}}}}}
    assert to_gemini(nested)["properties"]["inner"]["properties"]["x"]["type"] == "STRING"
    assert to_gemini(nested)["properties"]["items"]["items"]["properties"]["y"]["type"] == "INTEGER"
    j = to_json_schema(nested)["properties"]["inner"]
    assert j["type"] == ["object", "null"] and j["properties"]["x"]["type"] == ["string", "null"]
    o = to_openai_strict(nested)
    assert o["properties"]["inner"]["required"] == ["x"] and o["properties"]["items"]["items"]["additionalProperties"] is False


def test_conversion_does_not_mutate_original_schema():
    before = json.dumps(SCHEMA, sort_keys=True)
    to_gemini(SCHEMA), to_json_schema(SCHEMA), to_openai_strict(SCHEMA)
    assert json.dumps(SCHEMA, sort_keys=True) == before


# ---- 요청 모양 ------------------------------------------------------------------------


def test_gemini_request_shape_and_key_only_in_header():
    t = FakeTransport(body={"candidates": [{"content": {"parts": [{"text": '{"title": "회의"}'}]}}]})
    out = adapters.GeminiAdapter(KEY, "gemini-2.5-flash", t).complete_json("시스템", "사용자 문장", SCHEMA)
    url, headers, body, _ = t.calls[0]
    assert out == {"title": "회의"}
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    assert headers == {"x-goog-api-key": KEY} and KEY not in url
    assert body["systemInstruction"]["parts"][0]["text"] == "시스템"
    assert body["contents"][0]["parts"][0]["text"] == "사용자 문장"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"]["type"] == "OBJECT"


def test_gemini_accepts_models_prefix_in_model_name():
    t = FakeTransport(body={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    adapters.GeminiAdapter(KEY, "models/gemini-x", t).complete_json("s", "u", SCHEMA)
    assert "/models/gemini-x:generateContent" in t.calls[0][0] and "models/models" not in t.calls[0][0]


def test_claude_request_forces_tool_and_reads_tool_input():
    t = FakeTransport(body={"content": [{"type": "text", "text": "..."},
                                        {"type": "tool_use", "name": "result", "input": {"title": "회의"}}]})
    out = adapters.ClaudeAdapter(KEY, "claude-haiku-5-5", t).complete_json("시스템", "문장", SCHEMA)
    url, headers, body, _ = t.calls[0]
    assert out == {"title": "회의"}
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == KEY and headers["anthropic-version"] == "2023-06-01"
    assert body["tool_choice"] == {"type": "tool", "name": "result"}
    assert body["system"] == "시스템" and body["messages"] == [{"role": "user", "content": "문장"}]
    assert body["tools"][0]["input_schema"]["properties"]["date"]["type"] == ["string", "null"]


def test_openai_request_uses_strict_json_schema_and_bearer_header():
    t = FakeTransport(body={"choices": [{"message": {"content": '{"title": "회의"}'}}]})
    out = adapters.OpenAIAdapter(KEY, "gpt-4o-mini", t).complete_json("시스템", "문장", SCHEMA, name="quick_add")
    url, headers, body, _ = t.calls[0]
    assert out == {"title": "회의"}
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers == {"Authorization": f"Bearer {KEY}"}
    fmt = body["response_format"]["json_schema"]
    assert fmt["name"] == "quick_add" and fmt["strict"] is True and fmt["schema"]["additionalProperties"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


# ---- 응답/오류 처리 ----------------------------------------------------------------------


@pytest.mark.parametrize("cls,bad_body", [
    (adapters.GeminiAdapter, {"candidates": []}),
    (adapters.GeminiAdapter, {"candidates": [{"content": {"parts": [{"text": "JSON 아님"}]}}]}),
    (adapters.GeminiAdapter, {"promptFeedback": {"blockReason": "SAFETY"}}),
    (adapters.ClaudeAdapter, {"content": [{"type": "text", "text": "도구 호출 없이 글만"}]}),
    (adapters.OpenAIAdapter, {"choices": [{"message": {"content": "JSON 아님"}}]}),
    (adapters.OpenAIAdapter, {"choices": [{"message": {"content": None, "refusal": "거절"}}]}),
    (adapters.OpenAIAdapter, {"choices": []}),
])
def test_unreadable_response_is_bad_response_not_a_crash(cls, bad_body):
    with pytest.raises(AIError) as exc:
        cls(KEY, "m", FakeTransport(body=bad_body)).complete_json("s", "u", SCHEMA)
    assert exc.value.kind == "bad_response"


def test_non_json_body_and_non_object_result_are_bad_response():
    with pytest.raises(AIError) as exc:
        adapters.OpenAIAdapter(KEY, "m", FakeTransport(body="<html>")).complete_json("s", "u", SCHEMA)
    assert exc.value.kind == "bad_response"
    t = FakeTransport(body={"choices": [{"message": {"content": "[1, 2]"}}]})
    with pytest.raises(AIError) as exc:
        adapters.OpenAIAdapter(KEY, "m", t).complete_json("s", "u", SCHEMA)
    assert exc.value.kind == "bad_response"


@pytest.mark.parametrize("status,body,kind", [
    (401, {"error": {"message": "bad key"}}, "auth"),
    (403, {"error": {"message": "forbidden"}}, "auth"),
    (400, {"error": {"message": "API key not valid. Please pass a valid API key."}}, "auth"),
    (429, {"error": {"message": "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED"}}, "quota"),
    (400, {"error": {"message": "You exceeded your current quota"}}, "quota"),
    (404, {"error": {"message": "model not found"}}, "model"),
    (500, {"error": {"message": "boom"}}, "server"),
    (503, "<html>unavailable</html>", "server"),
    (529, {"error": {"type": "overloaded_error", "message": "Overloaded"}}, "server"),
    (400, {"error": {"message": "invalid request"}}, "bad_request"),
])
@pytest.mark.parametrize("cls", [adapters.GeminiAdapter, adapters.ClaudeAdapter, adapters.OpenAIAdapter])
def test_http_errors_map_to_clear_kinds(cls, status, body, kind):
    with pytest.raises(AIError) as exc:
        cls(KEY, "m", FakeTransport(status, body)).complete_json("s", "u", SCHEMA)
    assert exc.value.kind == kind
    assert exc.value.user_message  # 사용자에게 보여 줄 한국어 안내가 항상 있다


def test_api_key_is_scrubbed_if_provider_echoes_it_back():
    t = FakeTransport(401, {"error": {"message": f"Incorrect API key provided: {KEY}"}})
    with pytest.raises(AIError) as exc:
        adapters.OpenAIAdapter(KEY, "m", t).complete_json("s", "u", SCHEMA)
    assert KEY not in exc.value.detail and KEY not in str(exc.value) and KEY not in exc.value.user_message


def test_missing_key_is_no_key_error_and_unknown_provider_rejected():
    with pytest.raises(AIError) as exc:
        adapters.GeminiAdapter("", "m")
    assert exc.value.kind == "no_key"
    with pytest.raises(AIError):
        adapters.create_adapter("unknown", KEY)


def test_create_adapter_uses_default_model_when_blank():
    assert adapters.create_adapter("claude", KEY, "").model == adapters.DEFAULT_MODELS["claude"]
    assert adapters.create_adapter("gemini", KEY, "my-model").model == "my-model"
    assert set(adapters.ADAPTERS) == set(adapters.DEFAULT_MODELS)


def test_error_helpers():
    assert AIError("network").can_retry and AIError("quota").can_retry and not AIError("auth").can_retry
    assert "(" in AIError("bad_response", "상세").user_message
    assert AIError("weird").user_message  # 모르는 종류도 안내문이 있다


# ---- 실제 전송 부분: 내 컴퓨터 안의 임시 서버로만 시험한다 (외부 AI 호출 없음) -------------------


class _Handler(BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _Handler.seen = {"path": self.path, "headers": dict(self.headers), "body": json.loads(self.rfile.read(length))}
        code = 429 if self.path == "/limited" else 200
        payload = b'{"error": {"message": "slow down"}}' if code == 429 else b'{"ok": true}'
        self.send_response(code)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_urllib_transport_sends_json_and_headers(local_server):
    status, text = urllib_transport(local_server + "/ok", {"x-test": "1"}, {"a": "한글"}, 5)
    assert (status, json.loads(text)) == (200, {"ok": True})
    assert _Handler.seen["body"] == {"a": "한글"}
    headers = {k.lower(): v for k, v in _Handler.seen["headers"].items()}  # 헤더 이름은 대소문자를 구분하지 않는다
    assert headers["x-test"] == "1" and headers["content-type"] == "application/json"


def test_urllib_transport_returns_error_status_and_body_instead_of_raising(local_server):
    status, text = urllib_transport(local_server + "/limited", {}, {}, 5)
    assert status == 429 and "slow down" in text


def test_urllib_transport_connection_refused_is_network_error():
    with pytest.raises(AIError) as exc:
        urllib_transport("http://127.0.0.1:1/", {}, {}, 2)  # 아무도 듣지 않는 포트
    assert exc.value.kind in ("network", "timeout")  # 닫힌 포트는 Windows 에서 거부가 느려 시간 초과로 보이기도 한다
