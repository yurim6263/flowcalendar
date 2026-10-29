"""서버가 잠깐 바쁠 때(503 등) 자동으로 다시 보내는지, 그리고 다시 보내면 안 되는 오류는 바로 알리는지."""

import json

import pytest

from flowcalendar.ai import adapters
from flowcalendar.ai.errors import AIError
from tests.test_ai_adapters import KEY, SCHEMA

BUSY = {"error": {"code": 503, "status": "UNAVAILABLE",
                  "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary."}}
OK_GEMINI = {"candidates": [{"content": {"parts": [{"text": json.dumps({"title": "이력서 준비"})}]}}]}


class Sequence:
    """호출할 때마다 정해 둔 (상태, 본문) 을 차례로 돌려주는 가짜 전송."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self, *args):
        self.calls += 1
        status, body = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return status, body if isinstance(body, str) else json.dumps(body)


def adapter(transport, delays=(1.0, 2.5), get=None):
    slept = []
    a = adapters.GeminiAdapter(KEY, "m", transport, get_transport=get or Sequence((200, {})),
                               retry_delays=delays, sleep=slept.append)
    a.slept = slept
    return a


def test_busy_server_is_retried_with_waits_and_then_succeeds():
    t = Sequence((503, BUSY), (503, BUSY), (200, OK_GEMINI))
    a = adapter(t)
    assert a.complete_json("s", "u", SCHEMA) == {"title": "이력서 준비"}
    assert t.calls == 3 and a.slept == [1.0, 2.5]  # 1초, 2.5초 기다리며 두 번 더 보냈다


def test_busy_server_that_never_recovers_is_reported_with_the_servers_reason_after_the_last_try():
    t = Sequence((503, BUSY))
    a = adapter(t)
    with pytest.raises(AIError) as exc:
        a.complete_json("s", "u", SCHEMA)
    assert exc.value.kind == "server" and "high demand" in exc.value.user_message
    assert t.calls == 3 and a.slept == [1.0, 2.5]  # 무한히 다시 보내지 않는다 (처음 1번 + 재시도 2번)


@pytest.mark.parametrize("status", [502, 503, 504, 529])
def test_all_transient_statuses_are_retried(status):
    t = Sequence((status, {"error": {"message": "busy"}}), (200, OK_GEMINI))
    assert adapter(t).complete_json("s", "u", SCHEMA) == {"title": "이력서 준비"} and t.calls == 2


@pytest.mark.parametrize("status,kind", [(400, "bad_request"), (401, "auth"), (403, "auth"), (404, "model"),
                                         (429, "quota"), (500, "server")])
def test_errors_that_a_retry_cannot_fix_are_reported_immediately(status, kind):
    t = Sequence((status, {"error": {"message": "x"}}))
    a = adapter(t)
    with pytest.raises(AIError) as exc:
        a.complete_json("s", "u", SCHEMA)
    assert exc.value.kind == kind and t.calls == 1 and a.slept == []  # 기다리지도, 다시 보내지도 않는다


def test_network_errors_are_not_retried_silently():
    calls = []

    def broken(*args):
        calls.append(1)
        raise AIError("network", "TimeoutError")

    with pytest.raises(AIError) as exc:
        adapter(broken).complete_json("s", "u", SCHEMA)
    assert exc.value.kind == "network" and len(calls) == 1


def test_no_retries_when_delays_are_empty():
    t = Sequence((503, BUSY))
    with pytest.raises(AIError):
        adapter(t, delays=()).complete_json("s", "u", SCHEMA)
    assert t.calls == 1


def test_model_list_is_retried_too():
    get = Sequence((503, BUSY), (200, {"models": [{"name": "models/gemini-3.8-flash",
                                                    "supportedGenerationMethods": ["generateContent"]}]}))
    a = adapter(Sequence((200, OK_GEMINI)), get=get)
    assert a.list_models() == ["gemini-3.8-flash"] and get.calls == 2 and a.slept == [1.0]


def test_real_defaults_are_two_retries_and_a_few_seconds_at_most():
    assert adapters.DEFAULT_RETRY_DELAYS == (1.0, 2.5) and sum(adapters.DEFAULT_RETRY_DELAYS) < 5
    assert set(adapters.TRANSIENT_STATUS) == {502, 503, 504, 529}


def test_tests_do_not_wait_for_real_by_default():
    """conftest 가 기본 대기를 없앤다: 기본 생성자로 만든 어댑터는 재시도 없이 바로 결과를 낸다."""
    t = Sequence((503, BUSY))
    with pytest.raises(AIError):
        adapters.GeminiAdapter(KEY, "m", t).complete_json("s", "u", SCHEMA)
    assert t.calls == 1
