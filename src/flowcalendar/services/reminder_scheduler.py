"""주기적으로 일정 알림 시각을 확인해 reminder_due 신호를 낸다. 시각 계산은 reminders.py 가 한다."""

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.services.reminders import Reminder, due_reminders, lookup_range

CHECK_INTERVAL_MS = 15_000


class ReminderScheduler(QObject):
    reminder_due = Signal(object)  # Reminder

    def __init__(
        self,
        schedules: ScheduleRepository,
        settings: SettingsRepository,
        clock: Callable[[], datetime] = datetime.now,
        interval_ms: int = CHECK_INTERVAL_MS,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._schedules = schedules
        self._settings = settings
        self._clock = clock
        self._last_checked = clock()  # 켜기 전에 지난 알림은 울리지 않는다
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.tick)

    def start(self) -> None:
        self._last_checked = self._clock()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def tick(self) -> list[Reminder]:
        now = self._clock()
        after, self._last_checked = self._last_checked, now
        if not self._settings.get_bool("notifications_enabled") or now <= after:
            return []  # 꺼 둔 동안(또는 시계가 되감긴 경우)의 알림은 나중에 켜도 쏟아지지 않는다
        start, end = lookup_range(after, now)
        due = due_reminders(self._schedules.list_occurrences(start, end), after, now)
        for reminder in due:
            self.reminder_due.emit(reminder)
        return due
