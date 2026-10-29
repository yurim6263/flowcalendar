from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from flowcalendar.ui import tokens


APP_ICON_COLOR = "#C2506A"


def _draw(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    body = QLinearGradient(0, 0, s, s)
    body.setColorAt(0, QColor("#F4A7B9"))
    body.setColorAt(1, QColor(APP_ICON_COLOR))  # 앱 아이콘은 테마와 상관없이 늘 같은 모습이다
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(body)
    painter.drawRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.24, s * 0.24)

    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawRoundedRect(QRectF(s * 0.22, s * 0.30, s * 0.56, s * 0.48), s * 0.08, s * 0.08)
    painter.setBrush(QColor(255, 255, 255))
    for x in (0.32, 0.62):  # 달력 고리
        painter.drawRoundedRect(QRectF(s * x, s * 0.20, s * 0.06, s * 0.16), s * 0.03, s * 0.03)
    painter.setBrush(QColor(APP_ICON_COLOR))
    for col in range(3):
        for row in range(2):
            painter.drawEllipse(QRectF(s * (0.30 + col * 0.15), s * (0.46 + row * 0.13), s * 0.07, s * 0.07))
    painter.end()
    return pixmap


def hamburger_icon(size: int = 20) -> QIcon:
    """☰ 글자는 폰트에 따라 없을 수 있어 직접 그린다."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(tokens.TEXT))
    bar_h, gap = size * 0.11, size * 0.22
    top = (size - (bar_h * 3 + gap * 2)) / 2
    for i in range(3):
        painter.drawRoundedRect(QRectF(size * 0.15, top + i * (bar_h + gap), size * 0.70, bar_h),
                                bar_h / 2, bar_h / 2)
    painter.end()
    return QIcon(pixmap)


def search_icon(size: int = 20) -> QIcon:
    """돋보기. 글자(🔍)는 폰트마다 다르게 보여서 직접 그린다."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(tokens.TEXT), size * 0.10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = size * 0.27
    cx, cy = size * 0.43, size * 0.43
    painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    painter.drawLine(QPointF(cx + r * 0.72, cy + r * 0.72), QPointF(size * 0.82, size * 0.82))
    painter.end()
    return QIcon(pixmap)


def chevron_icon(direction: str, size: int = 20) -> QIcon:
    """달력 이동 화살표(‹ ›). 글자는 폰트마다 위아래 위치가 달라 중앙이 안 맞아서 직접 그린다."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(tokens.TEXT), size * 0.10, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    half_h, half_w = size * 0.26, size * 0.14  # 위아래 대칭이라 정확히 가운데에 놓인다
    cx, cy = size / 2, size / 2
    sign = -1 if direction == "prev" else 1
    path = QPainterPath()
    path.moveTo(cx - sign * half_w, cy - half_h)
    path.lineTo(cx + sign * half_w, cy)
    path.lineTo(cx - sign * half_w, cy + half_h)
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def sparkle_icon(size: int = 20) -> QIcon:
    """✨ 는 글꼴에 따라 없을 수 있어 네 갈래 별 두 개를 직접 그린다."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    def star(cx: float, cy: float, r: float, color: str) -> None:
        path = QPainterPath()
        inner = r * 0.28
        points = [(0, -r), (inner, -inner), (r, 0), (inner, inner), (0, r), (-inner, inner), (-r, 0), (-inner, -inner)]
        path.moveTo(cx + points[0][0], cy + points[0][1])
        for px, py in points[1:]:
            path.lineTo(cx + px, cy + py)
        path.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(path)

    star(size * 0.42, size * 0.58, size * 0.34, tokens.ACCENT)
    star(size * 0.76, size * 0.24, size * 0.17, "#E98BAA")
    painter.end()
    return QIcon(pixmap)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_draw(size))
    return icon
