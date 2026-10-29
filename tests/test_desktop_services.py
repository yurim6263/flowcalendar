import ctypes
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from flowcalendar.services import hotkey
from flowcalendar.services.secrets import SecretStore
from flowcalendar.services.single_instance import SingleInstance


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ---- 단축키 ---------------------------------------------------------------


def test_parse_valid_combinations():
    assert hotkey.parse("Ctrl+Alt+Space") == (hotkey.MOD_CONTROL | hotkey.MOD_ALT, 0x20)
    assert hotkey.parse("ctrl + shift + k") == (hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, ord("K"))
    assert hotkey.parse("Win+F5") == (hotkey.MOD_WIN, 0x74)
    assert hotkey.parse("Alt+7") == (hotkey.MOD_ALT, ord("7"))


@pytest.mark.parametrize("text", ["", "Space", "K", "Ctrl+", "Foo+K", "Ctrl+Enter", "Ctrl+F25", "Ctrl+한"])
def test_parse_rejects_bad_combinations(text):
    with pytest.raises(hotkey.HotkeyError):
        hotkey.parse(text)


def test_register_succeeds_then_conflict_is_reported_and_dispatch_works(app):
    first = hotkey.GlobalHotkey(hotkey_id=0xF101)
    second = hotkey.GlobalHotkey(hotkey_id=0xF102)
    combo = "Ctrl+Alt+Shift+F11"
    try:
        ok, msg = first.register(combo)
        assert ok, msg
        ok, msg = second.register(combo)  # 같은 조합을 또 잡으면 실패 + 안내 문구
        assert not ok and "이미" in msg and second.registered is None

        ok, msg = first.register("잘못")  # 잘못된 입력이어도 쓰던 단축키는 유지
        assert not ok and first.registered == combo
        second.register("Ctrl+Alt+Shift+F10")
        ok, msg = first.register("Ctrl+Alt+Shift+F10")  # 충돌해도 이전 것으로 복구
        assert not ok and first.registered == combo
        assert first._user32.UnregisterHotKey(None, 0xF101)  # 실제로 등록돼 있었다는 증거
        first.registered = None

        # WM_HOTKEY 메시지가 오면 신호가 나간다 (실제 키 입력은 사람이 눌러 봐야 한다).
        assert first.register(combo)[0]
        hits = []
        first.triggered.connect(lambda: hits.append(1))
        msg = wintypes.MSG()
        msg.message, msg.wParam = hotkey.WM_HOTKEY, 0xF101
        handled, _ = first._filter.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
        assert handled and hits == [1]
        msg.wParam = 0x9999  # 다른 id 는 무시
        handled, _ = first._filter.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
        assert not handled and hits == [1]
    finally:
        first.unregister()
        second.unregister()


# ---- 단일 인스턴스 ----------------------------------------------------------


SECOND_PROCESS = """
import sys
sys.path.insert(0, {src!r})
from PySide6.QtCore import QCoreApplication
from flowcalendar.services.single_instance import SingleInstance
app = QCoreApplication([])
print("first" if SingleInstance({name!r}).acquire() else "already-running")
"""


def test_second_process_notifies_first_and_exits(app):
    """두 번째 실행은 실제로 별도 프로세스로 띄워서 확인한다."""
    name = f"FlowCalendarTest-{uuid.uuid4().hex}"
    first = SingleInstance(name)
    shown = []
    first.activated.connect(lambda: shown.append(1))
    assert first.acquire() is True

    src = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", SECOND_PROCESS.format(src=src, name=name)],
        stdout=subprocess.PIPE, text=True,
    )
    deadline = time.time() + 10
    while proc.poll() is None and time.time() < deadline:
        app.processEvents()  # 첫 인스턴스(이 프로세스)가 요청을 받을 수 있도록 이벤트를 돌린다
        time.sleep(0.01)
    for _ in range(20):
        app.processEvents()
    assert proc.stdout.read().strip() == "already-running"
    assert proc.returncode == 0
    assert shown == [1]


def test_second_acquire_in_same_process_is_refused(app):
    name = f"FlowCalendarTest-{uuid.uuid4().hex}"
    first = SingleInstance(name)
    assert first.acquire() is True
    # 같은 스레드라 서버가 응답을 못 하지만(타임아웃 후) 실행 중으로 판단해야 한다
    assert SingleInstance(name).acquire() is False


def test_stale_server_name_can_be_taken_again(app):
    name = f"FlowCalendarTest-{uuid.uuid4().hex}"
    one = SingleInstance(name)
    assert one.acquire()
    one._server.close()  # 첫 인스턴스가 죽었다
    assert SingleInstance(name).acquire() is True


# ---- 키 저장소 (실제 Windows 자격 증명 관리자, 테스트용 서비스 이름) --------------


def test_secret_store_roundtrip_in_credential_manager():
    store = SecretStore(service=f"FlowCalendarTest-{uuid.uuid4().hex}")
    try:
        assert store.get("gemini") is None and not store.has("gemini")
        store.set("gemini", "  AIza-test-value \n")
        assert store.get("gemini") == "AIza-test-value"
        store.delete("gemini")
        assert store.get("gemini") is None
        store.delete("gemini")  # 없는 것을 지워도 오류 없음
    finally:
        store.delete("gemini")


def test_secret_never_written_to_db_file(tmp_path):
    from flowcalendar.data import db
    from flowcalendar.data.settings_repo import SettingsRepository

    path = tmp_path / "x.db"
    conn = db.connect(path)
    SettingsRepository(conn).set("ai_provider", "gemini")
    conn.close()
    assert b"AIza" not in path.read_bytes() and os.path.getsize(path) > 0
