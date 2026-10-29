"""Windows 시작 시 자동 실행 (HKCU Run 키). 관리자 권한이 필요 없다."""

import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FlowCalendar"
TRAY_FLAG = "--tray"  # 자동 실행 때는 창을 띄우지 않고 트레이에서 시작한다


def launch_command() -> str:
    """개발 중에는 pythonw -m flowcalendar, 빌드한 뒤에는 exe 경로."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {TRAY_FLAG}'
    interpreter = sys.executable
    if interpreter.lower().endswith("python.exe"):
        interpreter = interpreter[: -len("python.exe")] + "pythonw.exe"  # 콘솔 창이 뜨지 않게
    return f'"{interpreter}" -m flowcalendar {TRAY_FLAG}'


def is_enabled(key_path: str = RUN_KEY) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY, command: str | None = None) -> None:
    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command or launch_command())
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass  # 이미 꺼져 있다
