"""하루 한 번 DB를 통째로 복사해 두고, 오래된 것은 지운다 (데이터 안전).

앱이 켜져 있는 동안에도 날짜가 바뀌면 새로 만든다. SQLite 온라인 백업이라 사용 중이어도 안전하다.
JSON 내보내기(FR-DATA-001)와는 별개로, 사용자가 아무것도 하지 않아도 최근 며칠 전 상태로 돌아갈 수 있게 한다.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

KEEP = 7
PREFIX = "auto-"


def _name(day: date) -> str:
    return f"{PREFIX}{day:%Y%m%d}.db"


def list_backups(folder: Path | str) -> list[Path]:
    """자동 백업 파일을 오래된 순으로."""
    return sorted(Path(folder).glob(f"{PREFIX}*.db"))


def prune(folder: Path | str, keep: int = KEEP) -> list[Path]:
    """최근 keep 개만 남기고 지운다. 지운 파일 목록을 돌려준다."""
    files = list_backups(folder)
    removed = files[:-keep] if keep > 0 else []
    for path in removed:
        try:
            path.unlink()
        except OSError:
            pass  # 지우지 못해도 앱 사용에는 지장이 없다. 다음에 다시 시도한다
    return removed


def run_if_due(conn: sqlite3.Connection, backup_dir: Path | str, today: date | None = None,
               keep: int = KEEP) -> Path | None:
    """오늘 자동 백업이 아직 없으면 만든다. 만들었으면 그 경로를, 이미 있으면 None."""
    today = today or datetime.now().date()
    folder = Path(backup_dir)
    target = folder / _name(today)
    if target.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")  # 중간에 끊겨도 온전한 백업으로 오해하지 않게 임시 이름으로 만든다
    dest = sqlite3.connect(str(partial))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    partial.replace(target)
    prune(folder, keep)
    return target
