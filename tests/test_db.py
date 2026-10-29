from flowcalendar.data import db


def test_migrate_creates_tables_and_sets_version():
    conn = db.connect(":memory:")
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"schedules", "recurrence_exceptions", "todos", "memos", "settings"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_migrate_is_idempotent():
    conn = db.connect(":memory:")
    db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_quick_and_daily_todo_share_a_table():
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO todos(title, date) VALUES ('우유 사기', NULL)")
    conn.execute("INSERT INTO todos(title, date) VALUES ('회의자료 준비', '2026-10-28')")
    quick = conn.execute("SELECT COUNT(*) FROM todos WHERE date IS NULL").fetchone()[0]
    daily = conn.execute("SELECT COUNT(*) FROM todos WHERE date IS NOT NULL").fetchone()[0]
    assert (quick, daily) == (1, 1)
