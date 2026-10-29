import winreg

import pytest

from flowcalendar.services import autostart

TEST_KEY = r"Software\FlowCalendarTest\Run"


@pytest.fixture
def key_path():
    yield TEST_KEY
    # 테스트용 키만 정리한다. 실제 Run 키는 건드리지 않는다.
    for path in (TEST_KEY, r"Software\FlowCalendarTest"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def test_default_is_off_and_toggle_roundtrip(key_path):
    assert autostart.is_enabled(key_path) is False
    autostart.set_enabled(True, key_path, command='"C:\\x\\a.exe" --tray')
    assert autostart.is_enabled(key_path) is True
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        assert winreg.QueryValueEx(key, autostart.VALUE_NAME)[0] == '"C:\\x\\a.exe" --tray'
    autostart.set_enabled(False, key_path)
    assert autostart.is_enabled(key_path) is False


def test_disable_when_never_enabled_is_harmless(key_path):
    autostart.set_enabled(False, key_path)
    assert autostart.is_enabled(key_path) is False


def test_launch_command_starts_in_tray(monkeypatch):
    monkeypatch.setattr(autostart.sys, "executable", r"C:\Py\python.exe")
    cmd = autostart.launch_command()
    assert cmd == r'"C:\Py\pythonw.exe" -m flowcalendar --tray'
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\App\FlowCalendar.exe")
    assert autostart.launch_command() == r'"C:\App\FlowCalendar.exe" --tray'
