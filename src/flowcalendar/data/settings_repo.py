import sqlite3

# 새 설정은 여기에 기본값과 함께 추가한다. API 키는 절대 넣지 않는다 (keyring 전용, NFR-004).
DEFAULTS = {
    "notifications_enabled": "1",
    "hotkey": "Ctrl+Alt+Space",
    "ai_provider": "gemini",
    "ai_briefing": "1",
    "ai_auto_register": "1",  # 1이면 ✨ 빠른 추가 결과를 확인 없이 바로 등록하고 5초 동안 되돌릴 수 있게 한다
    "tray_hint_shown": "0",
    "widget_mode": "0",  # 1이면 바탕화면 위젯처럼 테두리 없이 다른 창 뒤에 고정
    "widget_geometry": "",  # "x,y,w,h"
    "widget_opacity": "65",  # 위젯 모드 배경 투명도(%), 50~100
    "auto_backup": "1",  # 1이면 하루 한 번 DB를 자동으로 복사해 두고 최근 7개만 보관
    "done_keep_days": "30",  # 완료한 할 일을 보관하는 일수. 0이면 계속 보관
    "theme": "pink",  # ui/tokens.py 의 THEMES 키
}


class SettingsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is not None and row["value"] is not None:
            return row["value"]
        return DEFAULTS.get(key, "")

    def set(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_bool(self, key: str) -> bool:
        return self.get(key) == "1"

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, "1" if value else "0")
