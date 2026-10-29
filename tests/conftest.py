import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class MemorySecrets:
    """테스트용 키 저장소: 메모리에만 있다. 사용자가 실제로 저장해 둔 API 키(자격 증명 관리자)를 읽지도 쓰지도 않는다."""

    def __init__(self, *args, **kwargs):
        self.data = {}

    def get(self, provider):
        return self.data.get(provider) or None

    def has(self, provider):
        return self.get(provider) is not None

    def set(self, provider, value):
        self.data[provider] = value.strip()

    def delete(self, provider):
        self.data.pop(provider, None)


@pytest.fixture(autouse=True)
def _no_real_waiting_for_retries(monkeypatch):
    """서버 과부하(503) 자동 재시도 사이의 실제 대기(1초, 2.5초)를 테스트에서는 없앤다. 재시도를 시험하는 테스트는 값을 직접 준다."""
    monkeypatch.setattr("flowcalendar.ai.adapters.RETRY_DELAYS", ())


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch):
    """앱이 만드는 SecretStore 를 항상 빈 가짜로 바꾼다. 안 그러면 내 컴퓨터에 키가 있는지에 따라 테스트 결과가 달라지고,
    키가 있을 때는 단축키 테스트가 진짜 AI 팝업을 열어 멈춘다."""
    monkeypatch.setattr("flowcalendar.app.SecretStore", MemorySecrets)


@pytest.fixture(autouse=True)
def _reset_theme():
    """테마는 모듈 전역이라, 다른 테마를 고른 테스트가 다음 테스트의 색에 영향을 주지 않게 매번 분홍으로 되돌린다."""
    yield
    from flowcalendar.ui import tokens

    tokens.apply(tokens.DEFAULT_THEME)
