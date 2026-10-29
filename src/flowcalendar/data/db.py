import os
import sqlite3
from datetime import datetime
from pathlib import Path

APP_DIR_NAME = "FlowCalendar"
DB_FILE_NAME = "flowcalendar.db"

# 마이그레이션은 순서대로 한 번씩만 적용된다. 인덱스 + 1 이 schema_version.
MIGRATIONS = [
    """
    CREATE TABLE schedules (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        start_at TEXT NOT NULL,
        end_at TEXT,
        all_day INTEGER NOT NULL DEFAULT 0,
        color TEXT NOT NULL DEFAULT 'yellow',
        recurrence TEXT,
        recurrence_until TEXT,
        remind_before_min INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    CREATE INDEX idx_schedules_start_at ON schedules(start_at);

    CREATE TABLE recurrence_exceptions (
        id INTEGER PRIMARY KEY,
        schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
        occurrence_date TEXT NOT NULL,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        override_title TEXT,
        override_start_at TEXT,
        override_end_at TEXT,
        UNIQUE (schedule_id, occurrence_date)
    );

    CREATE TABLE todos (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        date TEXT,
        done INTEGER NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    CREATE INDEX idx_todos_date ON todos(date);

    CREATE TABLE memos (
        id INTEGER PRIMARY KEY,
        content TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # 2: AI 가 이해하지 못했거나 오류로 처리하지 못한 빠른 추가 입력을 잃지 않게 남겨 두는 목록
    """
    CREATE TABLE ai_inbox (
        id INTEGER PRIMARY KEY,
        text TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    # 3: 완료한 할 일을 일정 기간만 보관하기 위해, 언제 완료했는지 기록한다 (이미 완료된 것은 지금부터 센다)
    """
    ALTER TABLE todos ADD COLUMN done_at TEXT;
    UPDATE todos SET done_at = datetime('now', 'localtime') WHERE done = 1;
    """,
]


DATA_DIR_ENV = "FLOWCALENDAR_DATA_DIR"  # 성능 측정이나 시험처럼 내 데이터를 건드리면 안 될 때 다른 폴더를 쓰게 한다


def default_db_path() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override) / DB_FILE_NAME
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_DIR_NAME / DB_FILE_NAME


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None and path != ":memory:" else path
    if db_path is None:
        db_path = default_db_path()
    if isinstance(db_path, Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if isinstance(db_path, Path):
        _backup_before_upgrade(conn, db_path)
    migrate(conn)
    return conn


def _backup_before_upgrade(conn: sqlite3.Connection, db_path: Path) -> None:
    """이미 쓰던 DB의 구조를 올리기 직전에 통째로 복사해 둔다. 새 DB나 올릴 것이 없으면 아무것도 하지 않는다."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if not 0 < version < len(MIGRATIONS):
        return
    folder = db_path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"before-schema{version}to{len(MIGRATIONS)}-{datetime.now():%Y%m%d-%H%M%S}.db"
    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {target}")
