"""위젯 모드: 창을 항상 다른 창 뒤(바탕화면 바로 위)에 둔다.

클릭하거나 입력해서 활성화돼도 앞으로 올라오지 않도록, 창 순서를 바꾸려는 WM_WINDOWPOSCHANGING 메시지를
가로채 "맨 뒤"로 고쳐 쓴다 (Rainmeter 의 Bottom 방식과 같은 원리).
"""

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtGui import QGuiApplication

HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
WM_WINDOWPOSCHANGING = 0x0046


class WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


def is_supported() -> bool:
    """진짜 Windows 창에서만 동작한다 (테스트용 offscreen 은 제외)."""
    return sys.platform == "win32" and QGuiApplication.platformName() == "windows"


# Windows 11 이 창에 덧붙이는 시스템 테두리(1px 회색)·반지름 8px 모서리·그림자를 끈다.
# 우리는 모서리와 가장자리를 직접 그리므로, 시스템 것이 겹치면 모서리에 어두운 선이 보인다.
DWMWA_NCRENDERING_POLICY = 2
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMNCRP_DISABLED = 1
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE
_CHROME_OFF = (
    (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND),
    (DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE),
)
# DWMWA_NCRENDERING_POLICY(비클라이언트 렌더링 끄기)는 일부러 쓰지 않는다: 실제 화면에서 시험해 보니
# 창이 불투명으로 취급되어 투명한 영역이 검게 합성되고 반투명 배경이 깨진다.


def remove_system_chrome(hwnd: int) -> dict[int, int]:
    """테두리 없는 창(위젯, 팝업)의 DWM 테두리/모서리/그림자를 끈다. {속성: HRESULT} 를 돌려준다.
    Windows 10 처럼 일부 속성을 모르는 환경은 그 속성만 실패하고 나머지는 적용된다."""
    results: dict[int, int] = {}
    if not is_supported() or not hwnd:
        return results
    dwmapi = ctypes.windll.dwmapi
    for attribute, value in _CHROME_OFF:
        data = ctypes.c_uint(value)
        results[attribute] = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
        ) & 0xFFFFFFFF
    return results


def send_to_bottom(hwnd: int) -> None:
    if not is_supported() or not hwnd:
        return
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(HWND_BOTTOM), 0, 0, 0, 0,
        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
    )


class BottomPinFilter(QAbstractNativeEventFilter):
    """pin() 한 창이 맨 뒤 말고 다른 곳으로 옮겨지려 하면 막는다. suspend() 중에는 잠시 풀어 둔다."""

    def __init__(self):
        super().__init__()
        self._pinned: set[int] = set()
        self._suspended: set[int] = set()
        self._installed = False

    def pin(self, hwnd: int) -> None:
        self._pinned.add(hwnd)
        if not self._installed and QGuiApplication.instance() is not None:
            QGuiApplication.instance().installNativeEventFilter(self)
            self._installed = True

    def unpin(self, hwnd: int) -> None:
        self._pinned.discard(hwnd)
        self._suspended.discard(hwnd)

    def suspend(self, hwnd: int) -> None:
        self._suspended.add(hwnd)

    def resume(self, hwnd: int) -> None:
        self._suspended.discard(hwnd)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_WINDOWPOSCHANGING and self._force_bottom(msg.hWnd, msg.lParam):
                pass
        return False, 0  # 메시지는 그대로 흘려 보낸다 (구조체만 고쳐 쓴다)

    def _force_bottom(self, hwnd, lparam) -> bool:
        if hwnd not in self._pinned or hwnd in self._suspended or not lparam:
            return False
        pos = WINDOWPOS.from_address(lparam)
        pos.hwndInsertAfter = HWND_BOTTOM
        pos.flags &= ~SWP_NOZORDER  # 순서를 바꾸지 않겠다는 표시가 있으면 지운다
        return True


_pinner: BottomPinFilter | None = None


def pinner() -> BottomPinFilter:
    global _pinner
    if _pinner is None:
        _pinner = BottomPinFilter()
    return _pinner
