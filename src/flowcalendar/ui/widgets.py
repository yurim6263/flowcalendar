"""Rose Glass 스타일의 작은 공용 위젯. QSS로는 체크 표시를 그릴 수 없어 직접 그린다."""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QLayout, QPushButton, QSlider, QWidget

from flowcalendar.ui import tokens


class RoseCheckBox(QCheckBox):
    BOX = 16
    GAP = 8

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        width = self.BOX
        if self.text():
            width += self.GAP + metrics.horizontalAdvance(self.text())
        return QSize(width, max(self.BOX + 2, metrics.height()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(1, (self.height() - self.BOX) / 2 + 0.5, self.BOX - 2, self.BOX - 2)
        enabled = self.isEnabled()

        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.DONE if enabled else tokens.TEXT_MUTED))
            painter.drawRoundedRect(box, 4, 4)
            tick = QPainterPath()
            tick.moveTo(box.left() + box.width() * 0.25, box.top() + box.height() * 0.52)
            tick.lineTo(box.left() + box.width() * 0.43, box.top() + box.height() * 0.70)
            tick.lineTo(box.left() + box.width() * 0.76, box.top() + box.height() * 0.32)
            painter.setPen(QPen(QColor("white"), 1.8, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tick)
        else:
            border = tokens.ACCENT if self.underMouse() and enabled else tokens.CHECK_BORDER
            painter.setPen(QPen(QColor(border), 1.4))
            painter.setBrush(QColor(*tokens.CHECK_FILL))
            painter.drawRoundedRect(box, 4, 4)

        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            painter.setPen(QPen(QColor(tokens.ACCENT), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-1.5, -1.5, 1.5, 1.5), 5, 5)

        if self.text():
            painter.setPen(QColor(tokens.TEXT if enabled else tokens.TEXT_MUTED))
            text_rect = QRectF(self.BOX + self.GAP, 0, self.width() - self.BOX - self.GAP, self.height())
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             self.text())


def _draw_chevron(widget: QWidget) -> None:
    """드롭다운 오른쪽 끝의 얇은 ∨. 기본 화살표는 스타일에 따라 검은 모서리가 남아서 직접 그린다."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = tokens.TEXT_SOFT if widget.isEnabled() else tokens.TEXT_MUTED
    painter.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    cx, cy = widget.width() - 16, widget.height() / 2
    path = QPainterPath()
    path.moveTo(cx - 4.5, cy - 2.2)
    path.lineTo(cx, cy + 2.5)
    path.lineTo(cx + 4.5, cy - 2.2)
    painter.drawPath(path)


class RoseComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        _draw_chevron(self)

    def wheelEvent(self, event):
        """마우스를 올리고 휠을 돌려도 값이 바뀌지 않는다. 스크롤 영역 안에서 지나가다 바뀌는 일을 막고, 휠은 바깥 영역이 받는다."""
        event.ignore()


class RoseSlider(QSlider):
    def wheelEvent(self, event):
        event.ignore()  # 슬라이더도 끌거나 키보드로만 바꾼다


class RoseDateEdit(QDateEdit):
    """달력 팝업이 있는 날짜 입력칸. 오른쪽 ∨ 를 누르면 달력이 열린다."""

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.calendarPopup():
            _draw_chevron(self)


class DragBar(QWidget):
    """위젯 모드에서 이 영역을 끌면 창이 움직인다 (테두리가 없어서 제목 표시줄이 없다)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.drag_enabled = False

    def mousePressEvent(self, event):
        handle = self.window().windowHandle()
        if self.drag_enabled and event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)


def keyboard_focus_only(root: QWidget) -> None:
    """버튼은 Tab 키로만 포커스를 받게 한다. 마우스로 누른 버튼에 포커스 표시가 남지 않고, 키보드 사용자는 Tab/Space 로 쓸 수 있다."""
    for button in root.findChildren(QPushButton):
        if button.focusPolicy() == Qt.FocusPolicy.StrongFocus:
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
