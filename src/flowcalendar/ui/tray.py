from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from flowcalendar.ui.icons import app_icon


class TrayController(QObject):
    """트레이 아이콘 (열기 / 종료)과 Windows 토스트 알림. 트레이를 못 쓰는 환경이면 available=False."""

    open_requested = Signal()
    quit_requested = Signal()
    widget_mode_toggled = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.icon = QSystemTrayIcon(app_icon(), self)
        self.icon.setToolTip("Flow Calendar")
        self.menu = QMenu()
        self.open_action = QAction("열기", self.menu)
        self.widget_action = QAction("위젯 모드 (바탕화면 뒤에 고정)", self.menu)
        self.widget_action.setCheckable(True)
        self.quit_action = QAction("종료", self.menu)
        self.menu.addAction(self.open_action)
        self.menu.addAction(self.widget_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.open_action.triggered.connect(self.open_requested)
        self.quit_action.triggered.connect(self.quit_requested)
        self.widget_action.toggled.connect(self.widget_mode_toggled)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.messageClicked.connect(self.open_requested)

    def set_widget_mode_checked(self, on: bool) -> None:
        self.widget_action.blockSignals(True)  # 상태만 맞추고 다시 신호를 내지 않는다
        self.widget_action.setChecked(on)
        self.widget_action.blockSignals(False)

    def show(self) -> None:
        if self.available:
            self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str, ms: int = 10_000) -> None:
        if self.available:
            self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.NoIcon, ms)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit()
