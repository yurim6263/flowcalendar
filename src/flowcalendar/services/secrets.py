"""API 키 저장소. Windows 자격 증명 관리자(keyring)에만 저장하고 DB·파일·로그에는 남기지 않는다 (NFR-004)."""

import keyring
from keyring.errors import KeyringError

SERVICE = "FlowCalendar"


class SecretError(Exception):
    pass


class SecretStore:
    def __init__(self, service: str = SERVICE):
        self.service = service

    def get(self, provider: str) -> str | None:
        try:
            return keyring.get_password(self.service, provider) or None
        except KeyringError as exc:
            raise SecretError(f"자격 증명 관리자를 읽지 못했습니다: {exc}") from exc

    def has(self, provider: str) -> bool:
        return self.get(provider) is not None

    def set(self, provider: str, value: str) -> None:
        try:
            keyring.set_password(self.service, provider, value.strip())
        except KeyringError as exc:
            raise SecretError(f"자격 증명 관리자에 저장하지 못했습니다: {exc}") from exc

    def delete(self, provider: str) -> None:
        try:
            keyring.delete_password(self.service, provider)
        except keyring.errors.PasswordDeleteError:
            pass  # 원래 없었다
        except KeyringError as exc:
            raise SecretError(f"자격 증명 관리자에서 지우지 못했습니다: {exc}") from exc
