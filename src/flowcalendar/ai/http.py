import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable

from flowcalendar.ai.errors import AIError

# (url, headers, JSON 본문, 제한 시간) -> (HTTP 상태 코드, 응답 본문 글자). 테스트에서는 가짜로 바꿔 끼운다.
Transport = Callable[[str, dict, dict, float], tuple[int, str]]

DEFAULT_TIMEOUT = 30.0


def _connection_error(exc: BaseException, timeout: float) -> AIError:
    """연결 실패를 '응답이 너무 늦음(시간 초과)'과 '연결 자체가 안 됨'으로 나눈다. 원인은 숨기지 않고 detail 에 남긴다."""
    reason = getattr(exc, "reason", exc)  # URLError 는 진짜 원인을 reason 에 들고 있다
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return AIError("timeout", f"{timeout:g}초")
    return AIError("network", f"{type(reason).__name__}: {reason}"[:200])


def urllib_transport(url: str, headers: dict, body: dict, timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # 4xx / 5xx: 본문에 원인이 들어 있어서 그대로 돌려준다
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        raise _connection_error(exc, timeout) from exc


# (url, headers, 제한 시간) -> (HTTP 상태 코드, 응답 본문 글자). 모델 목록처럼 읽기만 하는 요청에 쓴다.
GetTransport = Callable[[str, dict, float], tuple[int, str]]


def urllib_get(url: str, headers: dict, timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        raise _connection_error(exc, timeout) from exc
