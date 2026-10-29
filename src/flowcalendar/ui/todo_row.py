from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QWidget

from flowcalendar.domain.models import (
    PRIORITIES,
    PRIORITY_HIGH,
    PRIORITY_LABELS,
    PRIORITY_LOW,
    Todo,
)
from flowcalendar.ui import tokens
from flowcalendar.ui.widgets import RoseCheckBox

COMPACT_H = 20  # 날짜 셀 안
NORMAL_H = 30  # Quick 패널, 날짜 목록 팝업


class _EditLine(QLineEdit):
    cancelled = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class TodoRow(QWidget):
    """To-Do 한 줄: 체크박스 + 제목(클릭하면 바로 수정) + hover 삭제 버튼 + 우클릭 메뉴.

    상태를 직접 바꾸지 않고 action(kind, todo, value)만 내보낸다.
      toggle(bool) / rename(str) / priority(int) / delete / move(Quick -> Daily 요청)
    """

    action = Signal(str, object, object)

    def __init__(self, todo: Todo, *, compact: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.todo = todo
        self.compact = compact
        self._editing = False
        self.setFixedHeight(COMPACT_H if compact else NORMAL_H)
        font_px = 12 if compact else 14
        self._font_css = f"font-size: {font_px}px;"

        self.check = RoseCheckBox()
        self.check.setFixedSize(16, 18)
        self.check.toggled.connect(lambda done: self.action.emit("toggle", self.todo, done))

        self.mark = QLabel("!")  # 우선순위 높음 표시
        self.mark.setStyleSheet(
            f"color: {tokens.SUNDAY}; font-weight: 700; background: transparent; {self._font_css}"
        )
        self.mark.setFixedWidth(7)

        self.title_btn = QPushButton()
        self.title_btn.setObjectName("todoTitle")
        self.title_btn.setCursor(Qt.CursorShape.IBeamCursor)
        self.title_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.title_btn.clicked.connect(self.start_edit)

        self.edit = _EditLine()
        self.edit.setStyleSheet(
            f"QLineEdit {{ padding: 0 4px; border-radius: 6px; {self._font_css} }}"
        )
        self.edit.hide()
        self.edit.editingFinished.connect(self._commit_edit)
        self.edit.cancelled.connect(self._cancel_edit)

        self.delete_btn = QPushButton("×", self)
        self.delete_btn.setObjectName("todoDelete")
        self.delete_btn.setFixedSize(16, 16)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setToolTip("삭제")
        self.delete_btn.hide()
        self.delete_btn.clicked.connect(lambda: self.action.emit("delete", self.todo, None))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(5)
        layout.addWidget(self.check)
        layout.addWidget(self.mark)
        layout.addWidget(self.title_btn, 1)
        layout.addWidget(self.edit, 1)

        self.set_todo(todo)

    # ---- 표시 -------------------------------------------------------------

    def set_todo(self, todo: Todo) -> None:
        self.todo = todo
        self.check.blockSignals(True)
        self.check.setChecked(todo.done)
        self.check.blockSignals(False)
        self.mark.setVisible(todo.priority == PRIORITY_HIGH and not todo.done)

        color = tokens.TEXT_MUTED if todo.done else (
            tokens.TEXT_SOFT if todo.priority == PRIORITY_LOW else tokens.TEXT
        )
        decoration = "line-through" if todo.done else "none"
        self.title_btn.setStyleSheet(
            f"QPushButton#todoTitle {{ color: {color}; text-decoration: {decoration};"
            f" {self._font_css} }}"
        )
        self.title_btn.setToolTip(f"{todo.title}\n(클릭해서 수정 · 우클릭 메뉴)")
        self._elide()

    def _elide(self) -> None:
        width = max(self.title_btn.width() - 2, 10)
        text = self.title_btn.fontMetrics().elidedText(
            self.todo.title, Qt.TextElideMode.ElideRight, width
        )
        self.title_btn.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.delete_btn.move(self.width() - 20, (self.height() - 16) // 2)
        self._elide()

    def enterEvent(self, event):
        if not self._editing:
            self.delete_btn.show()
            self.delete_btn.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.delete_btn.hide()
        super().leaveEvent(event)

    # ---- 바로 수정 ----------------------------------------------------------

    def start_edit(self) -> None:
        if self._editing:
            return
        self._editing = True
        self.delete_btn.hide()
        self.title_btn.hide()
        self.edit.setText(self.todo.title)
        self.edit.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def _finish_edit(self) -> str:
        text = self.edit.text().strip()
        self._editing = False
        self.edit.hide()
        self.title_btn.show()
        return text

    def _commit_edit(self) -> None:
        if not self._editing:
            return
        text = self._finish_edit()
        # 비우거나 그대로면 아무것도 바꾸지 않는다 (삭제는 × 또는 메뉴로만).
        if text and text != self.todo.title:
            self.action.emit("rename", self.todo, text)

    def _cancel_edit(self) -> None:
        if self._editing:
            self._finish_edit()

    # ---- 우클릭 메뉴 -----------------------------------------------------------

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("미완료로 되돌리기" if self.todo.done else "완료").triggered.connect(
            lambda: self.action.emit("toggle", self.todo, not self.todo.done)
        )
        menu.addSeparator()
        for level in sorted(PRIORITIES, reverse=True):
            current = "●" if level == self.todo.priority else "○"
            act = menu.addAction(f"{current}  우선순위 {PRIORITY_LABELS[level]}")
            act.triggered.connect(lambda _=False, v=level: self.action.emit("priority", self.todo, v))
        if not self.todo.is_daily:
            menu.addSeparator()
            menu.addAction("날짜로 옮기기…").triggered.connect(
                lambda: self.action.emit("move", self.todo, None)
            )
        menu.addSeparator()
        menu.addAction("삭제").triggered.connect(lambda: self.action.emit("delete", self.todo, None))
        return menu

    def contextMenuEvent(self, event):
        self.build_menu().exec(event.globalPos())
