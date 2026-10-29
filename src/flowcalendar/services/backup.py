"""전체 데이터 JSON 내보내기 / 가져오기 (FR-DATA-001).

- API 키는 DB에 없고(keyring 전용), 설정 행 중 키/토큰처럼 보이는 것도 한 번 더 걸러서 내보낸다 (NFR-004).
- 가져오기는 "교체"다. 파일 검증 -> 현재 DB 자동 백업 -> 한 트랜잭션으로 교체 순서이며,
  중간에 실패하면 롤백되어 기존 데이터가 그대로 남는다.
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

APP_ID = "FlowCalendar"
FORMAT_VERSION = 1
_SECRET_KEY = re.compile(r"key|secret|token|password|credential", re.IGNORECASE)

# 테이블별로 내보낼 열. 삽입 순서는 외래키(schedules -> recurrence_exceptions)를 따른다.
TABLES = {
    "schedules": ["id", "title", "start_at", "end_at", "all_day", "color", "recurrence",
                  "recurrence_until", "remind_before_min", "created_at", "updated_at"],
    "recurrence_exceptions": ["id", "schedule_id", "occurrence_date", "is_deleted",
                              "override_title", "override_start_at", "override_end_at"],
    "todos": ["id", "title", "date", "done", "priority", "sort_order", "done_at", "created_at", "updated_at"],
    "memos": ["id", "content", "sort_order", "created_at", "updated_at"],
    "ai_inbox": ["id", "text", "reason", "created_at"],
}
_REQUIRED = {
    "schedules": ["id", "title", "start_at", "color"],
    "recurrence_exceptions": ["id", "schedule_id", "occurrence_date"],
    "todos": ["id", "title"],
    "memos": ["id"],
    "ai_inbox": ["id", "text"],
}


class BackupError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 한국어 메시지를 담는다."""


def _is_secret(key: str) -> bool:
    return bool(_SECRET_KEY.search(key))


def export_data(conn: sqlite3.Connection) -> dict:
    data: dict = {
        "app": APP_ID,
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    for table, columns in TABLES.items():
        rows = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id").fetchall()
        data[table] = [dict(zip(columns, row)) for row in rows]
    data["settings"] = {
        row["key"]: row["value"]
        for row in conn.execute("SELECT key, value FROM settings ORDER BY key")
        if not _is_secret(row["key"])
    }
    return data


def export_to_file(conn: sqlite3.Connection, path: Path | str) -> None:
    text = json.dumps(export_data(conn), ensure_ascii=False, indent=2)
    Path(path).write_text(text, encoding="utf-8")


def validate(data: object) -> dict:
    """가져오기 전에 파일 내용을 검사한다. 문제가 있으면 BackupError."""
    if not isinstance(data, dict) or data.get("app") != APP_ID:
        raise BackupError("Flow Calendar에서 내보낸 파일이 아닙니다.")
    version = data.get("format_version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise BackupError("이 앱보다 새로운 형식의 파일입니다. 앱을 업데이트한 뒤 다시 시도하세요.")
    for table, required in _REQUIRED.items():
        rows = data.get(table, [])
        if not isinstance(rows, list):
            raise BackupError(f"'{table}' 항목 형식이 올바르지 않습니다.")
        for row in rows:
            if not isinstance(row, dict) or any(row.get(col) is None for col in required):
                raise BackupError(f"'{table}' 항목에 필수 값이 빠진 줄이 있습니다.")
    if not isinstance(data.get("settings", {}), dict):
        raise BackupError("'settings' 항목 형식이 올바르지 않습니다.")
    return data


def backup_database(conn: sqlite3.Connection, backup_dir: Path | str) -> Path:
    """현재 DB를 통째로 복사해 둔다 (SQLite 온라인 백업이라 사용 중이어도 안전)."""
    folder = Path(backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"flowcalendar-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def import_from_file(conn: sqlite3.Connection, path: Path | str, backup_dir: Path | str) -> Path:
    """파일로 모든 데이터를 교체한다. 가져오기 전에 만든 백업 파일 경로를 돌려준다."""
    try:
        data = validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError) as exc:
        raise BackupError(f"파일을 읽지 못했습니다: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BackupError("JSON 형식이 올바르지 않습니다.") from exc

    saved = backup_database(conn, backup_dir)
    try:
        with conn:  # 하나의 트랜잭션: 하나라도 실패하면 전부 롤백
            for table in ("recurrence_exceptions", "schedules", "todos", "memos", "ai_inbox", "settings"):
                conn.execute(f"DELETE FROM {table}")
            for table, columns in TABLES.items():
                present = [c for c in columns if any(c in row for row in data.get(table, []))]
                marks = ", ".join("?" * len(present))
                for row in data.get(table, []):
                    conn.execute(
                        f"INSERT INTO {table} ({', '.join(present)}) VALUES ({marks})",
                        [row.get(c) for c in present],
                    )
            for key, value in data.get("settings", {}).items():
                if not _is_secret(key):
                    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
    except sqlite3.Error as exc:
        raise BackupError(
            f"가져오는 중 오류가 나서 원래 데이터를 그대로 두었습니다. ({exc})"
        ) from exc
    return saved
