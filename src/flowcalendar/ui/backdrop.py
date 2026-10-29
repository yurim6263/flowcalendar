from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

from flowcalendar.services import desktop_widget
from flowcalendar.ui import tokens
from flowcalendar.ui.widgets import keyboard_focus_only


def _render(size: QSize, opacity: float = 1.0) -> QPixmap:
    """로즈 그라데이션 배경. opacity < 1 이면 배경만 투명해진다(카드는 위젯이 따로 그린다)."""
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setOpacity(opacity)
    w, h = size.width(), size.height()

    base = QLinearGradient(0, 0, w, h)
    base.setColorAt(0, QColor(tokens.BG_TOP))
    base.setColorAt(1, QColor(tokens.BG_BOTTOM))
    painter.fillRect(0, 0, w, h, base)

    for cx, cy, scale, color in tokens.BLOBS:
        glow = QRadialGradient(QPointF(w * cx, h * cy), max(w, h) * scale)
        inner = QColor(color)
        inner.setAlpha(150)
        outer = QColor(color)
        outer.setAlpha(0)
        glow.setColorAt(0, inner)
        glow.setColorAt(1, outer)
        painter.fillRect(0, 0, w, h, glow)
    painter.end()
    return pixmap


class _Backdrop:
    """크기가 바뀔 때만 다시 그려서, 셀 Hover 같은 부분 갱신이 배경 계산을 일으키지 않게 한다."""

    _cache: QPixmap | None = None
    _cache_opacity = 1.0
    _opacity = 1.0

    def set_opacity(self, opacity: float) -> None:
        self._opacity = max(0.0, min(1.0, opacity))
        self._cache = None
        self.update()

    def _paint_backdrop(self, radius: float = 0.0) -> None:
        if self._cache is None or self._cache.size() != self.size() or self._cache_opacity != self._opacity:
            self._cache = _render(self.size(), self._opacity)
            self._cache_opacity = self._opacity
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not radius:
            painter.drawPixmap(0, 0, self._cache)
            return
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.setClipPath(outline)
        painter.drawPixmap(0, 0, self._cache)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(*tokens.EDGE), 1))
        painter.drawPath(outline)


def invalidate_all() -> None:
    """테마가 바뀌면 열려 있는 창의 배경 그림(캐시)을 버리고 다시 그리게 한다."""
    for widget in QApplication.allWidgets():
        if isinstance(widget, _Backdrop):
            widget._cache = None
            widget.update()


# 팝업 배경 투명도. 위젯 모드의 배경 투명도를 따라가고(일반 창 모드에서는 1.0), 입력칸 같은 내용 영역은 영향받지 않는다.
_popup_opacity = 1.0


def popup_opacity() -> float:
    return _popup_opacity


def set_popup_opacity(value: float) -> None:
    global _popup_opacity
    _popup_opacity = max(0.0, min(1.0, value))
    for widget in QApplication.topLevelWidgets():  # 이미 열려 있는 팝업(설정 화면 등)도 바로 다시 그린다
        if isinstance(widget, BackdropDialog):
            widget.update()


class BackdropWidget(_Backdrop, QWidget):
    _radius = 0.0

    def set_corner_radius(self, radius: float) -> None:
        """테두리 없는 창은 Windows 가 모서리를 둥글게 해 주지 않아서 직접 둥글게 그린다."""
        self._radius = radius
        self.update()

    def paintEvent(self, event):
        self._paint_backdrop(self._radius)


class BackdropDialog(_Backdrop, QDialog):
    """모든 팝업의 바탕: 제목 표시줄 없는 둥근 카드. 오른쪽 위 ×, 빈 곳을 끌어 이동, Esc 로 닫기."""

    RADIUS = tokens.WINDOW_RADIUS

    @property
    def _opacity(self) -> float:  # 모든 팝업이 같은 값을 쓴다
        return _popup_opacity

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # 둥근 모서리 바깥을 투명하게
        self.setContentsMargins(6, 6, 6, 6)
        self.close_btn = QPushButton("×", self)
        self.close_btn.setObjectName("dialogClose")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setToolTip("닫기 (Esc)")
        self.close_btn.clicked.connect(self.reject)

    def showEvent(self, event):
        super().showEvent(event)
        keyboard_focus_only(self)
        desktop_widget.remove_system_chrome(int(self.winId()))  # 둥근 카드 둘레에 시스템 테두리/그림자가 겹치지 않게

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.close_btn.move(self.width() - self.close_btn.width() - 12, 10)
        self.close_btn.raise_()

    def paintEvent(self, event):
        self._paint_backdrop(self.RADIUS)

    def mousePressEvent(self, event):
        handle = self.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()  # 라벨 등 빈 곳을 잡고 끌면 팝업이 움직인다
            event.accept()
            return
        super().mousePressEvent(event)
