class AIError(Exception):
    """AI 호출 실패. kind 로 원인을 구분하고, user_message 는 사용자에게 그대로 보여 줄 한국어 안내다.
    API 키는 어떤 메시지에도 넣지 않는다 (NFR-004)."""

    MESSAGES = {
        "no_key": "AI API 키가 없습니다. 설정에서 키를 입력하세요.",
        "auth": "API 키가 올바르지 않거나 권한이 없습니다. 설정에서 키를 확인하세요.",
        "quota": "사용 한도를 넘었거나 요청이 너무 많습니다. 잠시 뒤에 다시 시도하거나, 제공사의 사용량·요금 설정을 확인하세요.",
        "model": "이 키로 쓸 수 없는 모델 이름입니다. 설정에서 '사용 가능한 모델 불러오기'로 확인해 고르세요.",
        "network": "AI 서버에 연결하지 못했습니다. 인터넷 연결(VPN, 방화벽 포함)을 확인하고 다시 시도하세요.",
        "timeout": "AI 서버가 제한 시간 안에 응답하지 않았습니다. 서버가 바쁜 것일 수 있으니 잠시 뒤에 다시 시도하거나, "
                   "설정에서 다른 모델을 골라 보세요.",
        "server": "AI 서비스가 일시적으로 응답하지 않습니다. 잠시 뒤에 다시 시도하거나, 설정에서 다른 모델을 골라 보세요.",
        "bad_request": "AI 서비스가 요청을 받아들이지 않았습니다.",
        "bad_response": "AI의 응답을 이해하지 못했습니다.",
    }

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail

    @property
    def user_message(self) -> str:
        base = self.MESSAGES.get(self.kind, "AI 호출 중 알 수 없는 오류가 났습니다.")
        # 서버가 보낸 이유를 그대로 보여 준다. 원인을 짐작해서 숨기면 사용자가 고칠 방법이 없다 (키는 어댑터에서 이미 지운다).
        if self.kind == "timeout":
            return base + (f" (기다린 시간: {self.detail})" if self.detail else "")
        if self.detail and self.kind in ("bad_response", "network"):  # 우리 쪽에서 본 이유 (서버가 한 말이 아니다)
            return f"{base} (원인: {self.detail})" if self.kind == "network" else f"{base} ({self.detail})"
        if self.detail:
            return f"{base} (서버 메시지: {self.detail})"
        return base

    @property
    def can_retry(self) -> bool:
        """같은 요청을 잠시 뒤에 다시 보내 볼 만한 오류인가."""
        return self.kind in ("network", "timeout", "server", "quota")
