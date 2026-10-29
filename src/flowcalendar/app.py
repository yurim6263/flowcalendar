"""앱 진입점: 화면, 트레이, 알림 스케줄러, 전역 단축키, 단일 인스턴스를 한곳에서 엮는다."""

import getpass
import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from flowcalendar.data import db
from flowcalendar.data.ai_inbox_repo import AIInboxRepository
from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.services import auto_backup, autostart, backup
from flowcalendar.services.ai_service import AIService
from flowcalendar.services.hotkey import GlobalHotkey
from flowcalendar.services.task_runner import TaskRunner
from flowcalendar.services.reminder_scheduler import ReminderScheduler
from flowcalendar.services.reminders import Reminder
from flowcalendar.services.secrets import SecretStore
from flowcalendar.services.single_instance import SingleInstance
from flowcalendar.ui import tokens
from flowcalendar.ui.icons import app_icon
from flowcalendar.ui.main_window import MainWindow
from flowcalendar.ui.backdrop import invalidate_all
from flowcalendar.ui.settings_dialog import (
    SettingsBackend, SettingsDialog, saved_keep_days, saved_opacity, saved_theme,
)
from flowcalendar.ui.tray import TrayController

TRAY_FLAG = autostart.TRAY_FLAG


MAINTENANCE_INTERVAL_MS = 60 * 60 * 1000


class FlowCalendarApp(QObject):
    def __init__(
        self,
        conn: sqlite3.Connection,
        backup_dir: Path,
        *,
        tray: TrayController | None = None,
        start_hidden: bool = False,
        register_hotkey: bool = True,
        schedule_briefing: bool = False,
    ):
        super().__init__()
        self.conn = conn
        self.backup_dir = Path(backup_dir)
        self.schedules = ScheduleRepository(conn)
        self.settings = SettingsRepository(conn)
        self.secrets = SecretStore()
        self.apply_theme(saved_theme(self.settings))  # 창을 만들기 전에 정해야 처음부터 그 색으로 그려진다
        self.last_backup_error = ""
        self.run_maintenance()  # 자동 백업 -> 오래된 완료 할 일 정리 (창을 만들기 전에 해서 처음 화면에 반영된다)
        self._maintenance_timer = QTimer(self)  # 며칠씩 켜 둬도 날짜가 바뀌면 다시 한다
        self._maintenance_timer.setInterval(MAINTENANCE_INTERVAL_MS)
        self._maintenance_timer.timeout.connect(self.run_maintenance)
        self._maintenance_timer.start()

        self.window = MainWindow(self.schedules, TodoRepository(conn), MemoRepository(conn))
        QApplication.instance().aboutToQuit.connect(self.window.memo_card.edit.flush)  # 종료·로그오프 때 마지막 메모를 저장
        self.window.settings_requested.connect(self.open_settings)
        self.ai = AIService(self.settings, self.secrets)
        self.runner = TaskRunner(self)
        self.window.set_ai(self.ai, self.runner, AIInboxRepository(conn))
        self.window.ai_registered.connect(self._notify_ai_registered)

        self.tray = tray or TrayController(self)
        self.tray.open_requested.connect(self.show_window)
        self.tray.quit_requested.connect(self.quit)
        self.tray.widget_mode_toggled.connect(self.window.set_widget_mode)
        self.tray.show()
        # 트레이를 쓸 수 있을 때만 닫기 = 숨기기. 아니면 닫으면 그냥 종료된다.
        self.window.hide_on_close = self.tray.available
        self.window.set_widget_opacity(saved_opacity(self.settings))
        self.window.hidden_to_tray.connect(self._tell_tray_once)
        self.window.widget_mode_changed.connect(self._on_widget_mode_changed)
        self.window.widget_geometry_changed.connect(lambda g: self.settings.set("widget_geometry", g))
        if self.settings.get_bool("widget_mode"):
            self.window.set_widget_mode(True, self._saved_widget_geometry())
            self.tray.set_widget_mode_checked(True)

        self.scheduler = ReminderScheduler(self.schedules, self.settings, parent=self)
        self.scheduler.reminder_due.connect(self.on_reminder)
        self.scheduler.start()

        self.hotkey = GlobalHotkey(parent=self)
        self.hotkey.triggered.connect(self.on_hotkey)
        self.hotkey_warning = ""
        if register_hotkey:
            ok, hint = self.hotkey.register(self.settings.get("hotkey"))
            self.hotkey_warning = "" if ok else hint

        # 위젯 모드는 로그인하면 바로 바탕화면에 보여야 하니 --tray 로 시작해도 숨기지 않는다.
        if self.window.widget_mode or not (start_hidden and self.tray.available):
            self.window.show()
        if schedule_briefing:  # 앱을 켠 뒤 한 번만, 화면이 자리 잡은 다음에 띄운다 (FR-AI-002)
            QTimer.singleShot(3000, self.maybe_show_briefing)

    # ---- 데이터 관리: 자동 백업, 완료한 할 일 정리 ------------------------------------------

    def run_maintenance(self) -> None:
        """하루 한 번 DB를 복사해 두고(설정에서 끌 수 있다), 보관 기간이 지난 완료 할 일을 지운다.
        백업을 먼저 하므로 정리로 지워진 것도 최근 백업에는 남아 있다."""
        if self.settings.get_bool("auto_backup"):
            try:
                auto_backup.run_if_due(self.conn, self.backup_dir)
                self.last_backup_error = ""
            except (OSError, sqlite3.Error) as exc:  # 백업이 안 돼도 앱은 계속 쓸 수 있어야 한다
                self.last_backup_error = str(exc)
        removed = TodoRepository(self.conn).purge_done(saved_keep_days(self.settings))
        window = getattr(self, "window", None)
        if removed and window is not None:
            window.refresh()

    # ---- 테마 ----------------------------------------------------------------------

    def apply_theme(self, name: str) -> None:
        """테마를 바꾸고 열려 있는 창에 바로 반영한다 (미리보기와 저장 모두 이 길을 쓴다)."""
        tokens.apply(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(tokens.STYLESHEET)
        invalidate_all()
        window = getattr(self, "window", None)
        if window is not None:
            window.retheme()

    # ---- 창 / 종료 -----------------------------------------------------------

    def show_window(self) -> None:
        self.window.bring_forward()

    def _on_widget_mode_changed(self, on: bool) -> None:
        self.settings.set_bool("widget_mode", on)
        self.tray.set_widget_mode_checked(on)
        if on and self.window.isVisible():
            self.window._emit_geometry()  # 처음 켠 위치도 저장해 둔다

    def _saved_widget_geometry(self) -> QRect | None:
        """저장된 위치. 모니터를 뺐거나 해상도가 바뀌어 화면 밖이면 버린다."""
        try:
            x, y, w, h = (int(v) for v in self.settings.get("widget_geometry").split(","))
        except ValueError:
            return None
        rect = QRect(x, y, max(w, 640), max(h, 420))
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersected(rect).width() >= 120 and \
               screen.availableGeometry().intersected(rect).height() >= 80:
                return rect
        return None

    def quit(self) -> None:
        self.scheduler.stop()
        self.hotkey.unregister()
        self.window.hide_on_close = False
        self.window.close()  # 메모 저장은 closeEvent 가 한다
        self.tray.hide()
        QApplication.quit()

    def _tell_tray_once(self) -> None:
        if not self.settings.get_bool("tray_hint_shown"):
            self.settings.set_bool("tray_hint_shown", True)
            self.tray.notify("Flow Calendar", "창을 닫아도 트레이에서 계속 실행되어 알림이 울립니다.")

    # ---- 알림 / 단축키 -----------------------------------------------------------

    def on_reminder(self, reminder: Reminder) -> None:
        self.tray.notify(reminder.occurrence.title, reminder.message())

    def _notify_ai_registered(self, message: str) -> None:
        """단축키로 다른 프로그램 위에서 등록한 경우에도 등록됐다는 것을 알 수 있게, 창이 안 보일 때는 알림으로 알려 준다."""
        if not self.window.isActiveWindow():
            self.tray.notify("Flow Calendar", message)

    def on_hotkey(self) -> None:
        self.show_window()
        if self.window.ai_available:  # 키가 없으면 AI 화면은 없으므로 창만 보여 준다
            self.window.open_quick_add()

    def maybe_show_briefing(self) -> bool:
        """시작할 때 오늘 브리핑 (키가 있고, 설정에서 켜 둔 경우만)."""
        if self.window.ai_available and self.settings.get_bool("ai_briefing"):
            self.window.show_briefing("day")
            return True
        return False

    # ---- 설정 ---------------------------------------------------------------------

    def settings_backend(self) -> SettingsBackend:
        return SettingsBackend(
            settings=self.settings,
            secrets=self.secrets,
            autostart_enabled=autostart.is_enabled,
            set_autostart=autostart.set_enabled,
            apply_hotkey=self.hotkey.register,
            export_data=lambda path: backup.export_to_file(self.conn, path),
            import_data=lambda path: backup.import_from_file(self.conn, path, self.backup_dir),
            list_models=self.ai.list_models_for,
            runner=self.runner,
        )

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings_backend(), self.window, warning=self.hotkey_warning)
        dialog.data_imported.connect(self.window.reload_all)
        dialog.opacity_preview.connect(self.window.set_widget_opacity)
        dialog.theme_preview.connect(self.apply_theme)
        dialog.exec()
        self.window.refresh_ai()  # 키를 넣거나 지웠으면 ✨ 와 메모의 AI 버튼을 바로 맞춘다
        # 저장했으면 저장된 값, 닫기/취소였으면 미리보기 전의 값으로 돌아간다
        self.window.set_widget_opacity(saved_opacity(self.settings))
        self.apply_theme(saved_theme(self.settings))


BENCHMARK_FLAG = "--benchmark"
BENCHMARK_OUT_ENV = "FLOWCALENDAR_BENCH_OUT"
BENCHMARK_MONTHS = 24


def run_benchmark(app: QApplication) -> int:
    """성능 측정용 실행(tools/measure_perf.py 가 부른다): 창을 띄워 첫 화면이 그려질 때까지의 시간과
    월 이동 시간을 재서 결과 파일에 JSON 으로 쓰고 끝낸다. 내 데이터를 건드리지 않도록 별도 데이터 폴더가 지정돼 있어야 한다."""
    import json
    import os
    import time

    started = time.perf_counter()
    if not os.environ.get(db.DATA_DIR_ENV):
        print(f"{db.DATA_DIR_ENV} 로 측정용 데이터 폴더를 지정해야 합니다.", file=sys.stderr)
        return 2
    conn = db.connect()
    controller = FlowCalendarApp(conn, db.default_db_path().parent / "backups", register_hotkey=False)
    window = controller.window
    window.show()
    window.repaint()  # 첫 화면을 실제로 그린다
    app.processEvents()
    ready_ms = (time.perf_counter() - started) * 1000
    out = os.environ.get(BENCHMARK_OUT_ENV)
    if out:  # 첫 화면이 그려졌다는 표시 (측정 도구가 이 파일이 생기는 순간까지의 시간을 잰다)
        with open(out + ".ready", "w", encoding="utf-8") as handle:
            json.dump({"ready_ms": round(ready_ms, 1)}, handle)

    times = []
    for _ in range(BENCHMARK_MONTHS):
        begin = time.perf_counter()
        window.shift_month(1)
        window.repaint()
        app.processEvents()
        times.append((time.perf_counter() - begin) * 1000)
    import keyring

    result = {"ready_ms": round(ready_ms, 1), "nav_avg_ms": round(sum(times) / len(times), 1),
              "nav_max_ms": round(max(times), 1), "nav_runs": len(times),
              "keyring_backend": type(keyring.get_keyring()).__name__,  # 묶은 실행 파일에서도 키 저장소가 잡히는지 확인용
              "frozen": bool(getattr(sys, "frozen", False))}
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle)
    else:
        print(json.dumps(result))
    deadline = time.perf_counter() + 0.8  # 측정 도구가 이 시점의 메모리를 읽을 시간을 준다
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.02)
    controller.scheduler.stop()
    window.hide_on_close = False
    window.close()
    controller.tray.hide()
    conn.close()
    return 0


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("Flow Calendar")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(tokens.STYLESHEET)
    app.setQuitOnLastWindowClosed(False)  # 창을 닫아도 트레이에 남는다
    if BENCHMARK_FLAG in argv:
        return run_benchmark(app)

    instance = SingleInstance(f"FlowCalendar-{getpass.getuser()}")
    if not instance.acquire():
        return 0  # 이미 실행 중인 창을 앞으로 가져오도록 알렸다

    conn = db.connect()
    controller = FlowCalendarApp(
        conn, db.default_db_path().parent / "backups", start_hidden=TRAY_FLAG in argv, schedule_briefing=True
    )
    instance.activated.connect(controller.show_window)
    code = app.exec()
    conn.close()
    return code
