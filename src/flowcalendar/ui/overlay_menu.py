from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget


class OverlayMenu(QFrame):
    """헤더 버튼 아래에 뜨는 Overlay Popup (FR-SET-001). 바깥을 누르면 닫힌다."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.items: dict[str, QPushButton] = {}
        panel = QFrame(self)
        panel.setObjectName("overlayPanel")
        self._layout = QVBoxLayout(panel)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        self.setMinimumWidth(210)

    def add_item(self, key: str, text: str, callback: Callable[[], None] | None = None,
                 *, enabled: bool = True, close_on_click: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("menuItem")
        button.setEnabled(enabled)
        button.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        if callback is not None:
            if close_on_click:
                button.clicked.connect(self.close)
            button.clicked.connect(lambda: callback())
        self._layout.addWidget(button)
        self.items[key] = button
        return button

    def add_separator(self) -> None:
        line = QFrame()
        line.setObjectName("menuSeparator")
        line.setFixedHeight(1)
        self._layout.addWidget(line)

    def popup_below(self, anchor: QWidget) -> None:
        """anchor 의 오른쪽 끝에 맞춰 아래에 띄운다."""
        self.adjustSize()
        corner = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height() + 6))
        self.move(corner.x() - self.width(), corner.y())
        self.show()
