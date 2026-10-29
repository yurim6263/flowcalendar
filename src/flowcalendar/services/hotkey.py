"""전역 단축키 (Windows RegisterHotKey). 실패해도 앱은 정상 동작하고 설정 화면에서 안내만 한다 (FR-DESK-004)."""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "meta": MOD_WIN,
}


class HotkeyError(ValueError):
    pass


def parse(text: str) -> tuple[int, int]:
    """"Ctrl+Alt+Space" -> (modifier 비트마스크, 가상 키 코드). 잘못된 조합은 HotkeyError."""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if len(parts) < 2:
        raise HotkeyError("Ctrl, Alt, Shift 중 하나 이상과 키를 함께 지정하세요. 예: Ctrl+Alt+Space")
    mods = 0
    for name in parts[:-1]:
        flag = _MODIFIERS.get(name.lower())
        if flag is None:
            raise HotkeyError(f"알 수 없는 조합 키입니다: {name}")
        mods |= flag
    key = parts[-1].upper()
    if key == "SPACE":
        vk = 0x20
    elif len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise HotkeyError(f"지원하지 않는 키입니다: {parts[-1]} (영문, 숫자, F1~F24, Space)")
    return mods, vk


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner: "GlobalHotkey"):
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._owner.hotkey_id:
                self._owner.triggered.emit()
                return True, 0
        return False, 0


class GlobalHotkey(QObject):
    triggered = Signal()

    def __init__(self, hotkey_id: int = 0xF10C, parent: QObject | None = None):
        super().__init__(parent)
        self.hotkey_id = hotkey_id
        self.registered: str | None = None
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._filter = _Filter(self)
        QApplication.instance().installNativeEventFilter(self._filter)

    def register(self, text: str) -> tuple[bool, str]:
        """(성공 여부, 실패 시 사용자에게 보여 줄 안내). 성공하면 이전 단축키는 해제된다."""
        try:
            mods, vk = parse(text)
        except HotkeyError as exc:
            return False, str(exc)
        previous = self.registered
        self.unregister()
        if not self._user32.RegisterHotKey(None, self.hotkey_id, mods | MOD_NOREPEAT, vk):
            conflict = ctypes.get_last_error() == ERROR_HOTKEY_ALREADY_REGISTERED
            if previous is not None:
                self.register(previous)  # 실패해도 쓰던 단축키는 계속 동작하게 되돌린다
            if conflict:
                return False, f"{text} 는 다른 프로그램이 이미 쓰고 있습니다. 다른 조합을 지정하세요."
            return False, f"{text} 를 등록하지 못했습니다. 다른 조합을 지정하세요."
        self.registered = text
        return True, ""

    def unregister(self) -> None:
        if self.registered is not None:
            self._user32.UnregisterHotKey(None, self.hotkey_id)
            self.registered = None
