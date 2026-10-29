from flowcalendar.data import db
from flowcalendar.data.settings_repo import SettingsRepository


def test_defaults_then_override_and_bool():
    repo = SettingsRepository(db.connect(":memory:"))
    assert repo.get("hotkey") == "Ctrl+Alt+Space"
    assert repo.get_bool("notifications_enabled") is True
    assert repo.get("없는 키") == ""
    repo.set("hotkey", "Ctrl+Shift+K")
    repo.set_bool("notifications_enabled", False)
    repo.set("hotkey", "Ctrl+Shift+J")  # 같은 키를 다시 써도 한 행만 유지
    assert repo.get("hotkey") == "Ctrl+Shift+J"
    assert repo.get_bool("notifications_enabled") is False
    assert repo.conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 2
