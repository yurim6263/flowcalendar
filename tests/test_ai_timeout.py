"""'인터넷이 안 된다'와 '서버가 제한 시간 안에 답하지 않았다'를 구분해서 보여 주는지."""

import socket
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from flowcalendar.ai import http as ai_http
from flowcalendar.ai.errors import AIError
from flowcalendar.services.task_runner import ImmediateRunner
from flowcalendar.ui.ai_dialogs import QuickAddDialog
from tests.test_ai_ui import Env, qapp  # noqa: F401  (qapp 은 fixture)


class SlowHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        time.sleep(1.5)  # 제한 시간보다 오래 붙잡아 둔다
        try:
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
        except OSError:
            pass  # 이미 끊긴 연결

    do_GET = do_POST

    def log_message(self, *a):
        pass


@pytest.fixture
def slow_server():
    server = HTTPServer(("127.0.0.1", 0), SlowHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_slow_server_is_reported_as_timeout_with_the_waited_seconds(slow_server):
    with pytest.raises(AIError) as exc:
        ai_http.urllib_transport(slow_server + "/x", {}, {}, 0.3)
    assert exc.value.kind == "timeout" and exc.value.detail == "0.3초"
    assert "0.3초" in exc.value.user_message and "다른 모델" in exc.value.user_message


def test_slow_server_get_is_also_timeout(slow_server):
    with pytest.raises(AIError) as exc:
        ai_http.urllib_get(slow_server + "/models", {}, 0.3)
    assert exc.value.kind == "timeout"


def test_timeout_hidden_inside_urlerror_reason_is_still_a_timeout():
    """연결 단계의 시간 초과는 urllib 가 URLError(reason=timeout) 로 감싸서 던진다."""
    wrapped = urllib.error.URLError(socket.timeout("timed out"))
    assert ai_http._connection_error(wrapped, 30).kind == "timeout"
    assert ai_http._connection_error(TimeoutError(), 30).kind == "timeout"


def test_other_connection_failures_stay_network_errors_and_keep_their_cause():
    dns = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    err = ai_http._connection_error(dns, 30)
    assert err.kind == "network" and "gaierror" in err.detail and "getaddrinfo failed" in err.detail
    assert "원인: gaierror" in err.user_message
    assert ai_http._connection_error(ConnectionResetError("reset"), 30).kind == "network"
    assert len(ai_http._connection_error(OSError("x" * 1000), 30).detail) <= 200


def test_messages_distinguish_no_connection_from_slow_server():
    net, slow = AIError("network", "gaierror: x").user_message, AIError("timeout", "30초").user_message
    assert "연결하지 못했습니다" in net and "제한 시간" in slow and net != slow
    assert AIError("timeout").can_retry and AIError("network").can_retry
    assert "다른 모델" in AIError("server").user_message


def test_dialog_treats_timeout_like_overload(qapp):
    e = Env(error=AIError("timeout", "30초"))
    d = QuickAddDialog(e.window, e.service, ImmediateRunner())
    d.show()
    d.input.setText("29일 이력서 준비")
    d._convert()
    assert "제한 시간" in d.status.text() and "30초" in d.status.text()
    assert d.convert_btn.objectName() == "primary" and not d.settings_btn.isHidden()  # 다시 시도 + 다른 모델 고르기


def test_briefing_card_shows_timeout_reason_and_local_summary(qapp):
    e = Env(error=AIError("timeout", "30초"))
    e.window.show_briefing("day")
    card = e.window._briefing_card
    assert "제한 시간" in card.notice.text() and "30초" in card.notice.text()
    assert "일정" in card.summary.text()  # 코드로 만든 요약은 그대로 보인다
    card.close()
