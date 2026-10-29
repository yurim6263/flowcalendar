from PySide6.QtCore import QPointF, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPalette, QTextBlock, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from flowcalendar.domain.models import Todo
from flowcalendar.ui.todo_row import TodoRow
from flowcalendar.ui.widgets import clear_layout

MEMO_SAVE_DELAY_MS = 600


def _header(title: str, plus: QPushButton | None) -> QHBoxLayout:
    row = QHBoxLayout()
    label = QLabel(title)
    label.setObjectName("cardTitle")
    row.addWidget(label)
    row.addStretch(1)
    if plus is not None:
        row.addWidget(plus)
    return row


def _plus_button(tooltip: str) -> QPushButton:
    button = QPushButton("+")
    button.setObjectName("cardPlus")
    button.setFixedSize(26, 26)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(tooltip)
    return button


class QuickTodoCard(QFrame):
    """우측 TO-DO 카드. 날짜와 연결되지 않은 Quick To-Do 목록."""

    add_clicked = Signal()
    todo_action = Signal(str, object, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.plus = _plus_button("Quick To-Do 추가")
        self.plus.clicked.connect(self.add_clicked)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self.empty = QLabel("할 일을 추가해 보세요")
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 4, 4)
        body_layout.addLayout(self._rows)
        body_layout.addWidget(self.empty)
        body_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(_header("TO-DO", self.plus))
        layout.addWidget(scroll, 1)

    def set_todos(self, todos: list[Todo]) -> None:
        clear_layout(self._rows)
        for todo in todos:
            row = TodoRow(todo)
            row.action.connect(self.todo_action)
            self._rows.addWidget(row)
            row.show()
        self.empty.setVisible(not todos)

    def rows(self) -> list[TodoRow]:
        return [self._rows.itemAt(i).widget() for i in range(self._rows.count())]


BULLET_INDENT = 18  # 줄 왼쪽에 비워 두는 폭(px). 불릿이 이 안에 그려진다
BULLET_RADIUS = 2.6


def _indent_format() -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setLeftMargin(BULLET_INDENT)
    return fmt


class MemoEdit(QTextEdit):
    """한 장의 불릿 메모. 입력이 멈추면 changed(본문)를 내보내 자동 저장하게 한다.

    줄마다 불릿을 붙이는 건 서식일 뿐이라 저장되는 본문에는 불릿 문자가 없다.
    """

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None, delay_ms: int = MEMO_SAVE_DELAY_MS):
        super().__init__(parent)
        self.setObjectName("memo")
        self.setAcceptRichText(False)
        self._bulleting = False
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.flush)
        self.textChanged.connect(self._on_text_changed)
        self._bulletize()

    def set_content(self, text: str) -> None:
        self.blockSignals(True)
        self.setPlainText(text)
        self.blockSignals(False)
        self._bulletize()
        self._dirty = False

    def content(self) -> str:
        return self.toPlainText().rstrip("\n")

    def selected_text(self) -> str:
        """사용자가 고른 글. (줄바꿈은 문단 구분 문자로 들어오므로 되돌린다)"""
        return self.textCursor().selectedText().replace("\u2029", "\n")

    def flush(self) -> None:
        self._timer.stop()
        if self._dirty:
            self._dirty = False
            self.changed.emit(self.content())

    def focusOutEvent(self, event):
        self.flush()
        super().focusOutEvent(event)

    def _on_text_changed(self) -> None:
        if self._bulleting:
            return
        self._bulletize()
        self._dirty = True
        self._timer.start()

    def _bulletize(self) -> None:
        """모든 줄의 왼쪽을 불릿 자리만큼 띄운다. (불릿은 paintEvent에서 직접 그린다)"""
        self._bulleting = True
        try:
            block = self.document().begin()
            while block.isValid():
                if block.blockFormat().leftMargin() != BULLET_INDENT:
                    QTextCursor(block).mergeBlockFormat(_indent_format())
                block = block.next()
        finally:
            self._bulleting = False

    def has_bullet(self, block: QTextBlock) -> bool:
        """메모가 완전히 비어 있으면 불릿도 없다. 줄이 하나라도 있으면 빈 줄에도 불릿이 보인다."""
        doc = self.document()
        return doc.blockCount() > 1 or doc.characterCount() > 1

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        doc = self.document()
        layout = doc.documentLayout()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Text))
        scroll_y = self.verticalScrollBar().value()
        scroll_x = self.horizontalScrollBar().value()
        top = event.rect().top()
        bottom = event.rect().bottom()
        block = doc.begin()
        while block.isValid():
            if self.has_bullet(block) and block.isVisible():
                rect = layout.blockBoundingRect(block)
                y0 = rect.top() - scroll_y
                if y0 > bottom:
                    break
                if y0 + rect.height() >= top and block.layout().lineCount() > 0:
                    line = block.layout().lineAt(0)
                    cy = y0 + line.y() + line.height() / 2
                    cx = rect.left() + doc.documentMargin() + BULLET_RADIUS + 2 - scroll_x
                    painter.drawEllipse(QPointF(cx, cy), BULLET_RADIUS, BULLET_RADIUS)
            block = block.next()
        painter.end()


class MemoCard(QFrame):
    """우측 MEMO 카드. AI 키가 있으면 헤더에 'AI' 버튼이 보이고, 메모에서 고른 글만 일정/할 일 후보로 바꾼다."""

    convert_requested = Signal(str)  # 사용자가 고른 메모 글

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.edit = MemoEdit()
        self.ai_btn = QPushButton("AI")
        self.ai_btn.setObjectName("cardAi")
        self.ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ai_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 눌러도 메모의 선택이 풀리지 않게
        self.ai_btn.hide()
        self.ai_btn.clicked.connect(self._on_ai_clicked)
        self.edit.selectionChanged.connect(self._update_ai_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(_header("MEMO", self.ai_btn))
        layout.addWidget(self.edit, 1)
        self._update_ai_button()

    def set_ai_available(self, available: bool) -> None:
        self.ai_btn.setVisible(available)
        self._update_ai_button()

    def _update_ai_button(self) -> None:
        has_selection = bool(self.edit.selected_text().strip())
        self.ai_btn.setEnabled(has_selection)
        self.ai_btn.setToolTip(
            "선택한 메모 내용을 AI로 일정·할 일 후보로 바꿉니다 (선택한 부분만 AI에 보냅니다)"
            if has_selection else "메모에서 줄을 먼저 선택하세요. 선택한 부분만 AI로 일정·할 일을 찾습니다"
        )

    def _on_ai_clicked(self) -> None:
        text = self.edit.selected_text().strip()
        if text:
            self.convert_requested.emit(text)
