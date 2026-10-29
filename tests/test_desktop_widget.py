import ctypes
from ctypes import wintypes

import pytest
from PySide6.QtWidgets import QApplication

from flowcalendar.services import desktop_widget as dw

FAKE = 0x1234


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _raise_attempt():
    """클릭으로 창이 활성화될 때 Windows 가 보내는 것과 같은 모양: 맨 위(HWND_TOP=0)로 올리려는 요청."""
    pos = dw.WINDOWPOS()
    pos.hwnd = FAKE
    pos.hwndInsertAfter = None
    pos.flags = dw.SWP_NOZORDER | dw.SWP_NOSIZE
    return pos


def _send(f, hwnd, pos, message=dw.WM_WINDOWPOSCHANGING, event_type=b"windows_generic_MSG"):
    msg = wintypes.MSG()  # 필터가 읽는 동안 살아 있도록 변수로 붙잡는다
    msg.hWnd = hwnd
    msg.message = message
    msg.lParam = ctypes.addressof(pos)
    return f.nativeEventFilter(event_type, ctypes.addressof(msg))


def test_raise_attempt_on_pinned_window_is_turned_into_bottom(app):
    f = dw.BottomPinFilter()
    f.pin(FAKE)
    pos = _raise_attempt()
    handled, _ = _send(f, FAKE, pos)
    assert handled is False  # 메시지는 막지 않고 그대로 흘려 보낸다
    assert pos.hwndInsertAfter == dw.HWND_BOTTOM
    assert not pos.flags & dw.SWP_NOZORDER  # "순서 유지" 표시가 있어도 순서를 바꾸도록
    assert pos.flags & dw.SWP_NOSIZE  # 다른 플래그는 그대로


def test_other_windows_and_other_messages_are_untouched(app):
    f = dw.BottomPinFilter()
    f.pin(FAKE)
    pos = _raise_attempt()
    _send(f, 0x9999, pos)  # 다른 창
    assert not pos.hwndInsertAfter
    _send(f, FAKE, pos, message=0x0200)  # WM_MOUSEMOVE
    assert not pos.hwndInsertAfter
    _send(f, FAKE, pos, event_type=b"not_windows")
    assert not pos.hwndInsertAfter
    assert pos.flags & dw.SWP_NOZORDER


def test_suspend_allows_explicit_raise_and_unpin_stops_everything(app):
    f = dw.BottomPinFilter()
    f.pin(FAKE)
    f.suspend(FAKE)
    pos = _raise_attempt()
    _send(f, FAKE, pos)
    assert not pos.hwndInsertAfter  # 트레이 '열기' 같은 명시적 요청은 통과
    f.resume(FAKE)
    _send(f, FAKE, pos)
    assert pos.hwndInsertAfter == dw.HWND_BOTTOM
    f.unpin(FAKE)
    pos = _raise_attempt()
    _send(f, FAKE, pos)
    assert not pos.hwndInsertAfter


def test_null_lparam_is_ignored(app):
    f = dw.BottomPinFilter()
    f.pin(FAKE)
    msg = wintypes.MSG()
    msg.hWnd, msg.message, msg.lParam = FAKE, dw.WM_WINDOWPOSCHANGING, 0
    f.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))  # 예외 없이 지나간다


def test_not_supported_on_offscreen_so_nothing_is_called(app):
    assert dw.is_supported() is False
    dw.send_to_bottom(FAKE)  # 가짜 핸들로 Win32 를 부르지 않는다 (예외 없이 무시)
