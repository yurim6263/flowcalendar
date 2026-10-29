"""제공사별 어댑터. 모두 같은 일을 한다: 시스템 지시 + 사용자 내용 + 응답 스키마를 보내고, 파싱된 JSON(dict)을 돌려준다.

여기서는 응답을 '읽기만' 한다. 데이터를 쓰는 일은 항상 사용자가 미리보기를 확인한 뒤 앱이 한다 (FR-AI-005).
"""

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

from flowcalendar.ai.errors import AIError
from flowcalendar.ai.http import DEFAULT_TIMEOUT, GetTransport, Transport, urllib_get, urllib_transport
from flowcalendar.ai.schema import to_gemini, to_json_schema, to_openai_strict

# 서버가 잠깐 바쁠 때(과부하, 일시 장애) 나는 상태 코드. 이 경우에만 자동으로 다시 보낸다.
# 인증(401/403)·모델 없음(404)·한도(429)·잘못된 요청(400)은 다시 보내도 같은 결과라 바로 알려 준다.
TRANSIENT_STATUS = (502, 503, 504, 529)
DEFAULT_RETRY_DELAYS = (1.0, 2.5)  # 초. 첫 시도가 실패하면 1초 뒤, 또 실패하면 2.5초 뒤에 한 번씩 더 시도한다
RETRY_DELAYS = DEFAULT_RETRY_DELAYS  # 테스트에서 기다리지 않게 바꿀 수 있도록 따로 둔다

# 모델 이름은 설정에서 바꿀 수 있다. 제공사가 이름을 바꾸거나 없애면 'model' 오류로 안내한다.
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "claude": "claude-haiku-5-5",
    "openai": "gpt-4o-mini",
}


def _error_message(text: str) -> str:
    """제공사 오류 본문에서 사람이 읽을 메시지만 꺼낸다."""
    try:
        data = json.loads(text)
        err = data.get("error", data) if isinstance(data, dict) else {}
        if isinstance(err, dict):
            return str(err.get("message") or err.get("status") or "")[:500]
    except (ValueError, AttributeError):
        pass
    return text[:120]


class AIAdapter(ABC):
    provider_id = ""

    def __init__(self, api_key: str, model: str, transport: Transport = urllib_transport,
                 timeout: float = DEFAULT_TIMEOUT, get_transport: GetTransport = urllib_get,
                 retry_delays: tuple[float, ...] | None = None, sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise AIError("no_key")
        self._key = api_key
        self.model = model
        self._transport = transport
        self._get = get_transport
        self._timeout = timeout
        self._retry_delays = RETRY_DELAYS if retry_delays is None else retry_delays
        self._sleep = sleep

    def _send(self, send: Callable[[], tuple[int, str]]) -> tuple[int, str]:
        """요청을 보낸다. 서버가 잠깐 바쁘다는 응답이면 간격을 두고 몇 번 더 보낸다 (별도 스레드에서 불리므로 기다려도 된다)."""
        delays = list(self._retry_delays)
        while True:
            status, text = send()
            if status in TRANSIENT_STATUS and delays:
                self._sleep(delays.pop(0))
                continue
            return status, text

    @abstractmethod
    def _request(self, system: str, user: str, schema: dict, name: str) -> tuple[str, dict, dict]:
        """(url, headers, body)"""

    @abstractmethod
    def _extract(self, data: dict) -> dict:
        """성공 응답에서 구조화된 결과(dict)를 꺼낸다. 이해할 수 없으면 AIError('bad_response')."""

    @abstractmethod
    def _models_request(self) -> tuple[str, dict]:
        """모델 목록을 읽는 (url, headers)"""

    @abstractmethod
    def _parse_models(self, data: dict) -> list[str]:
        """모델 목록 응답에서 글쓰기/대화에 쓸 수 있는 모델 이름만 뽑는다."""

    def list_models(self) -> list[str]:
        """이 키로 쓸 수 있는 모델 이름들. 사용자 데이터는 보내지 않고 키만 헤더로 보낸다."""
        url, headers = self._models_request()
        status, text = self._send(lambda: self._get(url, headers, self._timeout))
        self._raise_for_status(status, text)
        try:
            return self._parse_models(json.loads(text))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise AIError("bad_response", "모델 목록 형식이 예상과 다름") from exc

    def complete_json(self, system: str, user: str, schema: dict, name: str = "result") -> dict:
        url, headers, body = self._request(system, user, schema, name)
        status, text = self._send(lambda: self._transport(url, headers, body, self._timeout))
        self._raise_for_status(status, text)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise AIError("bad_response", "JSON 이 아님") from exc
        result = self._extract(data)
        if not isinstance(result, dict):
            raise AIError("bad_response", "객체 형식이 아님")
        return result

    def _raise_for_status(self, status: int, text: str) -> None:
        if 200 <= status < 300:
            return
        detail = _error_message(text).replace(self._key, "***")  # 키가 응답에 되돌아와도 새지 않게
        lowered = detail.lower()
        if status in (401, 403) or "api key not valid" in lowered or "invalid api key" in lowered:
            raise AIError("auth", detail)
        if status == 429 or "quota" in lowered or "rate limit" in lowered:
            raise AIError("quota", detail)
        if status == 404:
            raise AIError("model", detail)
        if status >= 500:  # 529 overloaded 포함
            raise AIError("server", detail)
        raise AIError("bad_request", detail)


class GeminiAdapter(AIAdapter):
    provider_id = "gemini"

    def _request(self, system, user, schema, name):
        model = self.model.removeprefix("models/")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": to_gemini(schema),
                "temperature": 0.1,
            },
        }
        return url, {"x-goog-api-key": self._key}, body  # 키는 주소가 아니라 헤더로 보낸다 (로그에 남지 않게)

    def _models_request(self):
        return ("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", {"x-goog-api-key": self._key})

    def _parse_models(self, data):
        names = [m["name"].removeprefix("models/") for m in data.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        return sorted(set(names), key=lambda n: (not n.startswith("gemini"), n))

    def _extract(self, data):
        if data.get("promptFeedback", {}).get("blockReason"):
            raise AIError("bad_response", "안전 정책으로 응답이 차단됨")
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
            return json.loads(text)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIError("bad_response", "예상한 형식이 아님") from exc


class ClaudeAdapter(AIAdapter):
    provider_id = "claude"

    def _request(self, system, user, schema, name):
        body = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            # 도구 호출을 강제하면 입력이 항상 스키마에 맞는 JSON 으로 온다
            "tools": [{"name": name, "description": "결과를 이 형식으로 돌려준다.",
                       "input_schema": to_json_schema(schema)}],
            "tool_choice": {"type": "tool", "name": name},
        }
        return ("https://api.anthropic.com/v1/messages",
                {"x-api-key": self._key, "anthropic-version": "2023-06-01"}, body)

    def _models_request(self):
        return ("https://api.anthropic.com/v1/models?limit=100",
                {"x-api-key": self._key, "anthropic-version": "2023-06-01"})

    def _parse_models(self, data):
        return sorted({m["id"] for m in data.get("data", []) if m.get("id")})

    def _extract(self, data):
        for block in data.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block.get("input")
        raise AIError("bad_response", "도구 응답이 없음")


class OpenAIAdapter(AIAdapter):
    provider_id = "openai"

    def _request(self, system, user, schema, name):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": to_openai_strict(schema)},
            },
        }
        return ("https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {self._key}"}, body)

    def _models_request(self):
        return "https://api.openai.com/v1/models", {"Authorization": f"Bearer {self._key}"}

    _NOT_CHAT = ("embedding", "whisper", "tts", "audio", "image", "realtime", "transcribe", "moderation",
                 "dall-e", "davinci", "babbage", "search", "instruct")

    def _parse_models(self, data):
        ids = {m["id"] for m in data.get("data", []) if m.get("id")}
        chat = [i for i in ids if i.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))
                and not any(bad in i for bad in self._NOT_CHAT)]
        return sorted(chat or ids)

    def _extract(self, data):
        try:
            message = data["choices"][0]["message"]
            if message.get("refusal"):
                raise AIError("bad_response", "AI 가 요청을 거절함")
            return json.loads(message["content"])
        except AIError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIError("bad_response", "예상한 형식이 아님") from exc


ADAPTERS = {"gemini": GeminiAdapter, "claude": ClaudeAdapter, "openai": OpenAIAdapter}


def create_adapter(provider: str, api_key: str, model: str = "", transport: Transport = urllib_transport,
                   get_transport: GetTransport = urllib_get, *, timeout: float | None = None,
                   retry_delays: tuple[float, ...] | None = None) -> AIAdapter:
    if provider not in ADAPTERS:
        raise AIError("bad_request", f"지원하지 않는 제공자: {provider}")
    extra = {} if timeout is None else {"timeout": timeout}
    return ADAPTERS[provider](api_key, model or DEFAULT_MODELS[provider], transport, get_transport=get_transport,
                              retry_delays=retry_delays, **extra)
