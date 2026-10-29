from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

UNDO_MS = 5000  # FR-DTODO-003


class UndoToast(QFrame):
    """host 아래쪽 가운데에 잠깐 떠서 "되돌리기"를 제안한다. 시간이 지나면 저절로 사라진다."""

    def __init__(self, host: QWidget, message: str, on_undo: Callable[[], None] | None,
                 timeout_ms: int = UNDO_MS):
        super().__init__(host)
        self.setObjectName("toast")
        self._host = host
        self._on_undo = on_undo
        self.undone = False

        label = QLabel(message)
        button = QPushButton("되돌리기")
        button.setObjectName("undo")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(self.undo)
        button.setVisible(on_undo is not None)  # 되돌릴 것이 없는 안내(예: 이미 있어 건너뜀)에는 버튼을 숨긴다
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 8, 6)
        layout.addWidget(label)
        layout.addWidget(button)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(self.dismiss)
        self.timer.start()

        self._filter = _ResizeFilter(self)
        host.installEventFilter(self._filter)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

    def reposition(self) -> None:
        self.adjustSize()
        x = (self._host.width() - self.width()) // 2
        y = self._host.height() - self.height() - 24
        self.move(max(x, 0), max(y, 0))

    def undo(self) -> None:
        if self.undone or self._on_undo is None:
            return
        self.undone = True
        self._on_undo()
        self.dismiss()

    def dismiss(self) -> None:
        self.timer.stop()
        self._host.removeEventFilter(self._filter)
        self.hide()
        self.deleteLater()


class _ResizeFilter(QObject):
    def __init__(self, toast: UndoToast):
        super().__init__(toast)
        self._toast = toast

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self._toast.reposition()
        return False
