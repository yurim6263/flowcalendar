"""검색 팝업: 일정·할 일 제목과 메모 내용을 한꺼번에 찾고, 결과를 누르면 그 항목으로 이동한다."""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services.search import SearchResults
from flowcalendar.ui import tokens
from flowcalendar.ui.backdrop import BackdropDialog
from flowcalendar.ui.calendar_view import WEEKDAYS
from flowcalendar.ui.widgets import clear_layout

HINT = "일정·할 일 제목, 메모 내용에서 찾습니다."
NOTHING = "찾는 내용이 없어요."


def _day_label(day: date) -> str:
    return f"{day.month}/{day.day}({WEEKDAYS[(day.weekday() + 1) % 7]})"


def schedule_label(s: Schedule) -> str:
    when = _day_label(s.start_at.date())
    if s.end_at is not None and s.end_at.date() > s.start_at.date():
        when += f"~{_day_label(s.end_at.date())}"
    if s.recurrence:
        when += " · 반복"
    return f"{when}  {s.title}"


def todo_label(t: Todo) -> str:
    where = _day_label(t.day) if t.day else "Quick"
    return f"{'✓ ' if t.done else ''}{where}  {t.title}"


class SearchDialog(BackdropDialog):
    """selected 에 ("schedule", Schedule) / ("todo", Todo) / ("memo", 찾은 줄) 중 하나가 담겨 닫힌다."""

    def __init__(self, parent, search: Callable[[str], SearchResults]):
        super().__init__(parent)
        self.setWindowTitle("검색")
        self.setMinimumSize(460, 480)
        self._search = search
        self.selected: tuple[str, object] | None = None
        self.results = SearchResults("")
        self._buttons: list[QPushButton] = []

        heading = QLabel("검색")
        heading.setObjectName("dialogTitle")
        self.input = QLineEdit()
        self.input.setPlaceholderText("찾을 말을 입력하세요")
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._refresh)
        self.input.returnPressed.connect(self._pick_first)
        self.status = QLabel(HINT)
        self.status.setObjectName("note")

        self._list = QVBoxLayout()
        self._list.setSpacing(6)
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)
        body = QWidget()
        body.setLayout(self._list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        self.scroll = scroll

        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(self.input)
        layout.addWidget(self.status)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
        self.input.setFocus()

    # ---- 결과 -----------------------------------------------------------------

    def _refresh(self, text: str) -> None:
        clear_layout(self._list)
        self._buttons = []
        self.results = self._search(text)
        if not text.strip():
            self.status.setText(HINT)
            return
        r = self.results
        if r.total == 0:
            self.status.setText(NOTHING)
            return
        self.status.setText(f"일정 {len(r.schedules)} · 할 일 {len(r.todos)} · 메모 {len(r.memo_lines)}")
        for s in r.schedules:
            self._add_row("일정", schedule_label(s), ("schedule", s), tokens.CHIP[s.color])
        for t in r.todos:
            self._add_row("할 일", todo_label(t), ("todo", t), tokens.GLASS_HOVER)
        for line in r.memo_lines:
            self._add_row("메모", line, ("memo", line), tokens.MEMO_BG)

    def _add_row(self, kind: str, text: str, payload: tuple[str, object], color: str) -> None:
        button = QPushButton(f"{kind}   {text}")
        button.setToolTip(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background: {color}; border: 0; text-align: left; padding: 6px 10px; }}"
        )
        button.clicked.connect(lambda _=False, p=payload: self._pick(p))
        self._list.addWidget(button)
        self._buttons.append(button)

    def _pick(self, payload: tuple[str, object]) -> None:
        self.selected = payload
        self.accept()

    def _pick_first(self) -> None:
        r = self.results
        if r.schedules:
            self._pick(("schedule", r.schedules[0]))
        elif r.todos:
            self._pick(("todo", r.todos[0]))
        elif r.memo_lines:
            self._pick(("memo", r.memo_lines[0]))
