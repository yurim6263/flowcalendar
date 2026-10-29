import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QPushButton, QWidget

from flowcalendar.domain.models import Occurrence, Todo
from flowcalendar.ui import tokens
from flowcalendar.ui.todo_row import TodoRow

WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")
CHIP_H = 20
CHIP_STEP = 22
CELL_TOP = 34


def _chip_style(color: str, left_round: bool = True, right_round: bool = True) -> str:
    bg = tokens.CHIP[color]
    hover = QColor(bg).darker(106).name()
    left, right = ("6px" if left_round else "0"), ("6px" if right_round else "0")
    return (
        f"QPushButton {{ background: {bg}; border: 0; text-align: left;"
        f" border-top-left-radius: {left}; border-bottom-left-radius: {left};"
        f" border-top-right-radius: {right}; border-bottom-right-radius: {right};"
        f" padding: 0 0 0 8px; font-size: 12px; }}"
        f"QPushButton:hover {{ background: {hover}; }}"
    )


OCCURRENCE_MIME = "application/x-flowcalendar-occurrence"


class OccurrenceButton(QPushButton):
    """달력의 일정 칩/막대. 누르면 열리고, 끌어서 다른 날로 옮길 수 있다 (Ctrl 을 누른 채 놓으면 복사)."""

    def __init__(self, occ: Occurrence, day_at, parent: QWidget | None = None):
        super().__init__(parent)
        self.occ = occ
        self._day_at = day_at  # 버튼 안의 위치 -> 그 자리의 날짜 (여러 칸 막대는 잡은 칸이 기준이다)
        self._press: QPoint | None = None
        self._dragged = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 칸마다 수십 개라 Tab 으로 지나가지 않는다 (마우스용)

    def mousePressEvent(self, event):
        self._dragged = False
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()
                and self.occ.schedule.id is not None):
            self._start_drag()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        if self._dragged:  # 끌었다 놓은 것은 '클릭'이 아니다
            self._dragged = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _start_drag(self) -> None:
        press = self._press
        self._press, self._dragged = None, True
        payload = {"id": self.occ.schedule.id, "date": self.occ.date.isoformat(),
                   "press": self._day_at(press).isoformat()}
        mime = QMimeData()
        mime.setData(OCCURRENCE_MIME, json.dumps(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(press)
        self.setDown(False)
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)


@dataclass(frozen=True)
class Segment:
    """여러 날에 걸친 일정을 한 주(週) 안에서 이은 막대 한 토막.

    같은 일정은 그 주의 모든 칸에서 같은 줄(slot)을 쓰고, 막대는 칸 위에 한 개의 위젯으로 그린다.
    """

    occ: Occurrence
    week: int
    col_start: int
    col_end: int
    slot: int
    continues_left: bool   # 이 주보다 앞에서 시작했다
    continues_right: bool  # 이 주를 넘어서 이어진다


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class DayCell(QFrame):
    add_clicked = Signal(object)
    occurrence_clicked = Signal(object)
    overflow_clicked = Signal(object)
    todo_action = Signal(str, object, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dayCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("hover", False)
        self.setMinimumSize(60, 56)
        self.day: date | None = None
        self._slots: list[Occurrence | Segment | None] = []  # 위에서부터 한 줄에 하나. 막대 자리는 비워 둔다
        # 위젯은 실제로 보일 줄만 만든다 (넘쳐서 '+N개'로 접힌 것까지 다 만들면 월을 넘길 때 느려진다). 못 만든 자리는 None.
        self._chips: list[QPushButton | None] = []
        self._todos: list[Todo] = []
        self._rows: list[TodoRow | None] = []

        self.number = QLabel(self)
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plus = QPushButton("+", self)
        self.plus.setObjectName("cellPlus")
        self.plus.setFixedSize(24, 24)
        self.plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plus.setToolTip("일정 / 할 일 추가")
        self.plus.hide()
        self.plus.clicked.connect(lambda: self.add_clicked.emit(self.day))
        self.more = QPushButton(self)
        self.more.setObjectName("more")
        self.more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.hide()
        self.more.clicked.connect(lambda: self.overflow_clicked.emit(self.day))

    def set_day(self, day: date, in_month: bool, is_today: bool, occurrences: list[Occurrence],
                todos: list[Todo] = (), reserved: dict[int, Segment] | None = None):
        """occurrences 는 이 칸에 칩으로 그릴 하루짜리 일정, reserved 는 {줄: 이 칸을 지나는 막대}."""
        self.day = day
        self._slots = self._arrange(occurrences, reserved or {})
        self.number.setText(str(day.day))
        if is_today:
            color, extra = tokens.ON_ACCENT, f"background: {tokens.ACCENT}; border-radius: 12px;"
        else:
            color = {6: tokens.SUNDAY, 5: tokens.SATURDAY}.get(day.weekday(), tokens.TEXT)
            if not in_month:
                color = tokens.TEXT_MUTED
            extra = "background: transparent;"
        self.number.setStyleSheet(f"color: {color}; {extra} font-size: 14px;")

        for chip in self._chips:
            if chip is not None:
                chip.hide()
                chip.deleteLater()
        self._chips = [None] * len(self._slots)
        for row in self._rows:
            if row is not None:
                row.hide()
                row.deleteLater()
        self._todos = list(todos)
        self._rows = [None] * len(self._todos)
        self._layout_children()

    def _make_chip(self, entry: Occurrence) -> OccurrenceButton:
        day = self.day
        chip = OccurrenceButton(entry, lambda pos, d=day: d, self)
        chip.setStyleSheet(_chip_style(entry.color))
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setToolTip(self._tooltip(entry))
        chip.clicked.connect(lambda _=False, o=entry: self.occurrence_clicked.emit(o))
        return chip

    def _make_row(self, todo: Todo) -> TodoRow:
        row = TodoRow(todo, compact=True, parent=self)
        row.action.connect(self.todo_action)
        return row

    @staticmethod
    def _arrange(singles: list[Occurrence], reserved: dict[int, Segment]) -> list[Occurrence | Segment | None]:
        """막대가 차지한 줄은 그대로 두고, 그 사이 빈 줄부터 하루짜리 일정을 채운다."""
        slots: list[Occurrence | Segment | None] = [None] * (max(reserved) + 1 if reserved else 0)
        for slot, segment in reserved.items():
            slots[slot] = segment
        pending = iter(singles)
        for i, entry in enumerate(slots):
            if entry is None:
                slots[i] = next(pending, None)
        slots.extend(pending)
        while slots and slots[-1] is None:
            slots.pop()
        return slots

    def _row_count(self) -> int:
        return len(self._slots) + len(self._todos)

    def visible_rows(self) -> int:
        """지금 크기에서 실제로 보이는 줄 수. 넘치면 맨 아랫줄은 '+N개' 자리가 된다."""
        capacity = max(0, (self.height() - CELL_TOP - 4) // CHIP_STEP)
        total = self._row_count()
        return total if total <= capacity else max(capacity - 1, 0)

    @staticmethod
    def _tooltip(occ: Occurrence) -> str:
        if occ.is_multiday:
            days = f"{occ.first_day:%m/%d} ~ {occ.last_day:%m/%d}"
            if occ.all_day:
                return f"{occ.title}\n{days} (종일)"
            return f"{occ.title}\n{days}\n{occ.start_at:%H:%M} - {occ.end_at:%m/%d %H:%M}"
        if occ.all_day:
            return f"{occ.title} (종일)"
        span = occ.start_at.strftime("%H:%M")
        if occ.end_at:
            span += f" - {occ.end_at.strftime('%H:%M')}"
        return f"{occ.title}\n{span}"

    def _layout_children(self) -> None:
        w, h = self.width(), self.height()
        self.number.setGeometry(8, 6, 24, 24)
        self.plus.move(w - 30, 6)

        # 일정이 위, To-Do가 아래. 넘침 계산은 둘을 합쳐서 한다 (FR-CAL-004, 006).
        shown = self.visible_rows()
        metrics = self.fontMetrics()
        hidden = 0
        for i, entry in enumerate(self._slots):
            if entry is None:  # 빈 줄
                continue
            if i >= shown:
                hidden += 1
                if self._chips[i] is not None:
                    self._chips[i].hide()
                continue
            if isinstance(entry, Segment):  # 막대는 격자가 그린다. 이 줄은 비워 둔다
                continue
            chip = self._chips[i]
            if chip is None:
                chip = self._chips[i] = self._make_chip(entry)
            chip.setGeometry(6, CELL_TOP + i * CHIP_STEP, w - 12, CHIP_H)
            chip.setText(metrics.elidedText(entry.title, Qt.TextElideMode.ElideRight, w - 28))
            chip.show()
        for j, todo in enumerate(self._todos):
            i = len(self._slots) + j
            if i >= shown:
                hidden += 1
                if self._rows[j] is not None:
                    self._rows[j].hide()
                continue
            row = self._rows[j]
            if row is None:
                row = self._rows[j] = self._make_row(todo)
            row.setGeometry(6, CELL_TOP + i * CHIP_STEP, w - 12, CHIP_H)
            row.show()
        if hidden > 0:
            self.more.setText(f"+{hidden}개")
            self.more.setGeometry(6, CELL_TOP + shown * CHIP_STEP, w - 12, CHIP_H)
            self.more.show()
        else:
            self.more.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_children()

    def enterEvent(self, event):
        self.setProperty("hover", True)
        _repolish(self)
        self.plus.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hover", False)
        _repolish(self)
        self.plus.hide()
        super().leaveEvent(event)


class CalendarGrid(QWidget):
    add_clicked = Signal(object)
    occurrence_clicked = Signal(object)
    overflow_clicked = Signal(object)
    todo_action = Signal(str, object, object)
    occurrence_dropped = Signal(int, object, int, bool)  # (일정 id, 그 회차의 시작일, 옮긴 날 수, 복사 여부)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drop_cell: DayCell | None = None
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._saturday: QLabel | None = None
        for col, name in enumerate(WEEKDAYS):
            label = QLabel(name)
            label.setObjectName("weekday")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 6:
                self._saturday = label
            self._layout.addWidget(label, 0, col)
            self._layout.setColumnStretch(col, 1)
        self.retheme()

        self._bars: list[QPushButton] = []
        self._segments: list[Segment] = []
        self._cells: list[DayCell] = []
        for i in range(42):
            cell = DayCell()
            cell.add_clicked.connect(self.add_clicked)
            cell.occurrence_clicked.connect(self.occurrence_clicked)
            cell.overflow_clicked.connect(self.overflow_clicked)
            cell.todo_action.connect(self.todo_action)
            self._layout.addWidget(cell, 1 + i // 7, i % 7)
            self._cells.append(cell)

    def retheme(self) -> None:
        """테마 색이 바뀌었을 때 직접 색을 지정한 부분(토요일 머리글)을 맞춘다. 칸과 막대는 refresh 가 다시 만든다."""
        if self._saturday is not None:
            self._saturday.setStyleSheet(f"color: {tokens.SATURDAY};")

    @staticmethod
    def visible_range(year: int, month: int) -> tuple[date, date]:
        """월간 격자에 보이는 첫 날(일요일)과 마지막 날."""
        first = date(year, month, 1)
        start = first - timedelta(days=(first.weekday() + 1) % 7)
        weeks = -(-((first.weekday() + 1) % 7 + calendar.monthrange(year, month)[1]) // 7)
        return start, start + timedelta(days=weeks * 7 - 1)

    @staticmethod
    def plan_week(week: int, days: list[date], multiday: list[Occurrence]) -> list[Segment]:
        """한 주 안에서 여러 날 일정의 막대를 줄(slot)에 배치한다. 먼저 시작한 것, 긴 것이 위로 간다."""
        used: list[set[int]] = [set() for _ in range(7)]
        segments = []
        ordered = sorted(
            (o for o in multiday if o.first_day <= days[6] and o.last_day >= days[0]),
            key=lambda o: (o.first_day, not o.all_day, -(o.last_day - o.first_day).days, o.title),
        )
        for occ in ordered:
            a = max((occ.first_day - days[0]).days, 0)
            b = min((occ.last_day - days[0]).days, 6)
            slot = 0
            while any(slot in used[c] for c in range(a, b + 1)):
                slot += 1
            for c in range(a, b + 1):
                used[c].add(slot)
            segments.append(Segment(occ, week, a, b, slot, occ.first_day < days[0], occ.last_day > days[6]))
        return segments

    def set_month(self, year: int, month: int, occurrences: list[Occurrence], today: date,
                  todos: list[Todo] = ()):
        start, end = self.visible_range(year, month)
        weeks = ((end - start).days + 1) // 7
        singles: dict[date, list[Occurrence]] = {}
        multiday = []
        for occ in occurrences:
            if occ.is_multiday:
                multiday.append(occ)
            else:
                singles.setdefault(occ.date, []).append(occ)
        todos_by_day: dict[date, list[Todo]] = {}
        for todo in todos:
            todos_by_day.setdefault(todo.day, []).append(todo)

        segments: list[Segment] = []
        reserved: dict[date, dict[int, Segment]] = {}
        for week in range(weeks):
            days = [start + timedelta(days=week * 7 + c) for c in range(7)]
            for seg in self.plan_week(week, days, multiday):
                segments.append(seg)
                for c in range(seg.col_start, seg.col_end + 1):
                    reserved.setdefault(days[c], {})[seg.slot] = seg

        for i, cell in enumerate(self._cells):
            is_visible = i // 7 < weeks
            cell.setVisible(is_visible)
            if is_visible:
                day = start + timedelta(days=i)
                cell.set_day(day, day.month == month, day == today, singles.get(day, []),
                             todos_by_day.get(day, []), reserved.get(day))
        for row in range(6):
            self._layout.setRowStretch(1 + row, 1 if row < weeks else 0)
        self._set_bars(segments)

    def bars(self) -> list[QPushButton]:
        return self._bars

    # ---- 끌어서 옮기기 ------------------------------------------------------------------------

    def _bar_day(self, seg: Segment, x_in_bar: int) -> date:
        """막대 안의 x 위치가 가리키는 날짜 (여러 칸 막대에서 어느 날을 잡았는지)."""
        bar = self._bars[self._segments.index(seg)]
        x = bar.x() + x_in_bar
        for col in range(seg.col_start, seg.col_end + 1):
            cell = self._cells[seg.week * 7 + col]
            if cell.x() <= x < cell.x() + cell.width():
                return cell.day
        return self._cells[seg.week * 7 + seg.col_start].day

    def _cell_at(self, pos: QPoint) -> "DayCell | None":
        for cell in self._cells:
            if cell.isVisible() and cell.geometry().contains(pos) and cell.day is not None:
                return cell
        return None

    def _highlight_drop(self, cell: "DayCell | None") -> None:
        if cell is self._drop_cell:
            return
        for old, value in ((self._drop_cell, False), (cell, True)):
            if old is not None:
                old.setProperty("hover", value)
                _repolish(old)
        self._drop_cell = cell

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(OCCURRENCE_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(OCCURRENCE_MIME):
            self._highlight_drop(self._cell_at(event.position().toPoint()))
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._highlight_drop(None)

    def dropEvent(self, event):
        self._highlight_drop(None)
        if not event.mimeData().hasFormat(OCCURRENCE_MIME):
            return
        target = self._cell_at(event.position().toPoint())
        if target is None:
            return
        try:
            data = json.loads(bytes(event.mimeData().data(OCCURRENCE_MIME)).decode("utf-8"))
            press = date.fromisoformat(data["press"])
            occ_date = date.fromisoformat(data["date"])
            schedule_id = int(data["id"])
        except (ValueError, KeyError, TypeError):
            return
        copy = event.proposedAction() == Qt.DropAction.CopyAction
        event.setDropAction(Qt.DropAction.CopyAction if copy else Qt.DropAction.MoveAction)
        event.accept()
        self.occurrence_dropped.emit(schedule_id, occ_date, (target.day - press).days, copy)

    def _set_bars(self, segments: list[Segment]) -> None:
        for bar in self._bars:
            bar.hide()
            bar.deleteLater()
        self._bars = []
        self._segments = segments
        for seg in segments:
            bar = OccurrenceButton(seg.occ, lambda pos, s=seg: self._bar_day(s, pos.x()), self)
            bar.setStyleSheet(_chip_style(seg.occ.color, not seg.continues_left, not seg.continues_right))
            bar.setCursor(Qt.CursorShape.PointingHandCursor)
            bar.setToolTip(DayCell._tooltip(seg.occ))
            bar.clicked.connect(lambda _=False, o=seg.occ: self.occurrence_clicked.emit(o))
            self._bars.append(bar)
        self._place_bars()

    def _place_bars(self) -> None:
        """막대를 칸 위에 얹는다. 칸 가장자리 여백은 이어지는 쪽에서는 없앤다."""
        self._layout.activate()
        metrics = self.fontMetrics()
        for seg, bar in zip(self._segments, self._bars):
            first = self._cells[seg.week * 7 + seg.col_start]
            last = self._cells[seg.week * 7 + seg.col_end]
            left = first.x() + (0 if seg.continues_left else 6)
            right = last.x() + last.width() - (0 if seg.continues_right else 6)
            bar.setGeometry(left, first.y() + CELL_TOP + seg.slot * CHIP_STEP, max(right - left, 1), CHIP_H)
            bar.setText(metrics.elidedText(seg.occ.title, Qt.TextElideMode.ElideRight, bar.width() - 20))
            covered = self._cells[seg.week * 7 + seg.col_start: seg.week * 7 + seg.col_end + 1]
            visible = all(seg.slot < cell.visible_rows() for cell in covered)
            bar.setVisible(visible)
            if visible:
                bar.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_bars()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_bars()
