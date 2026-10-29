from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QTime, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCalendarWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
)

from flowcalendar.domain.models import (
    COLORS,
    PRIORITIES,
    PRIORITY_LABELS,
    PRIORITY_NORMAL,
    Occurrence,
    Schedule,
    Todo,
    validate,
    validate_todo,
)
from flowcalendar.ui import tokens
from flowcalendar.ui.backdrop import BackdropDialog
from flowcalendar.ui.calendar_view import WEEKDAYS
from flowcalendar.ui.todo_row import TodoRow
from flowcalendar.ui.widgets import RoseCheckBox, RoseComboBox, RoseDateEdit, clear_layout

REMINDERS = [("알림 없음", None), ("5분 전", 5), ("10분 전", 10), ("30분 전", 30), ("1시간 전", 60)]
RECURRENCES = [("반복 안 함", None), ("매일", "daily"), ("매주", "weekly"), ("매월", "monthly")]


class AddChooserDialog(BackdropDialog):
    """날짜의 "+" 를 눌렀을 때 무엇을 추가할지 고른다 (POPUP 1)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("무엇을 추가할까요?")
        self.choice: str | None = None
        self.setMinimumWidth(300)
        heading = QLabel("무엇을 추가할까요?")
        heading.setObjectName("dialogTitle")
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(heading)
        schedule = QPushButton("일정 추가")
        schedule.clicked.connect(lambda: self._pick("schedule"))
        todo = QPushButton("Daily To-Do 추가")
        todo.clicked.connect(lambda: self._pick("todo"))
        layout.addWidget(schedule)
        layout.addWidget(todo)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class TodoDialog(BackdropDialog):
    """To-Do 추가 (POPUP 3). day가 있으면 Daily, 없으면 Quick."""

    def __init__(self, parent=None, *, day: date | None = None, todo: Todo | None = None,
                 initial_title: str = "", notice: str = ""):
        super().__init__(parent)
        self.day = day
        self.setWindowTitle("Daily To-Do" if day else "To-Do")
        self.setMinimumWidth(340)

        heading = QLabel("Daily To-Do" if day else "Quick To-Do")
        heading.setObjectName("dialogTitle")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("할 일을 입력하세요")
        self.priority = RoseComboBox()
        for level in sorted(PRIORITIES, reverse=True):
            self.priority.addItem(PRIORITY_LABELS[level], level)
        self.priority.setCurrentIndex(self.priority.findData(PRIORITY_NORMAL))
        if todo is not None:  # AI 초안 등으로 미리 채운다
            self.title_edit.setText(todo.title)
            self.priority.setCurrentIndex(self.priority.findData(todo.priority))
        elif initial_title:
            self.title_edit.setText(initial_title)
        self.error = QLabel()
        self.error.setObjectName("error")

        form = QFormLayout()
        form.addRow("내용", self.title_edit)
        form.addRow("우선순위", self.priority)

        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        save = QPushButton("저장")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(heading)
        if notice:
            note = QLabel(notice)
            note.setObjectName("note")
            note.setWordWrap(True)
            layout.addWidget(note)
        if day:
            hint = QLabel(f"{day.month}월 {day.day}일 ({WEEKDAYS[(day.weekday() + 1) % 7]})")
            hint.setObjectName("hint")
            layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addLayout(buttons)

    def todo(self) -> Todo:
        return Todo(
            title=self.title_edit.text().strip(),
            day=self.day,
            priority=self.priority.currentData(),
        )

    def _on_save(self) -> None:
        try:
            validate_todo(self.todo())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class DatePickDialog(BackdropDialog):
    """Quick To-Do를 옮길 날짜를 고른다 (FR-QTODO-003)."""

    def __init__(self, parent=None, *, start: date | None = None):
        super().__init__(parent)
        self.setWindowTitle("날짜로 옮기기")
        heading = QLabel("어느 날짜의 Daily To-Do로 옮길까요?")
        heading.setObjectName("dialogTitle")
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        if start:
            self.calendar.setSelectedDate(QDate(start.year, start.month, start.day))
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        move = QPushButton("옮기기")
        move.setObjectName("primary")
        move.setDefault(True)
        move.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(move)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(self.calendar)
        layout.addLayout(buttons)

    def day(self) -> date:
        return self.calendar.selectedDate().toPython()


class ScheduleDialog(BackdropDialog):
    """일정 생성 / 상세·수정·삭제 (SC-ADD-001 POPUP 2, SC-SCH-001)."""

    def __init__(self, parent=None, *, day: date | None = None, occurrence: Occurrence | None = None,
                 draft: Schedule | None = None, initial_title: str = "", notice: str = ""):
        super().__init__(parent)
        self.occurrence = occurrence
        self.action: str | None = None  # "save" | "delete"
        editing = occurrence is not None
        self.setWindowTitle("일정 수정" if editing else "일정 추가")
        self.setMinimumWidth(400)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("제목을 입력하세요")

        self.date_edit = RoseDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.has_end_date = RoseCheckBox("종료 날짜")
        self.has_end_date.setToolTip("체크하면 시작일부터 종료일까지 여러 날에 걸친 일정이 됩니다")
        self.has_end_date.toggled.connect(self._sync_enabled)
        self.end_date_edit = RoseDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.dateChanged.connect(self._keep_end_after_start)
        self.all_day = RoseCheckBox("종일")
        self.start_edit = QTimeEdit(QTime(9, 0))
        self.end_edit = QTimeEdit(QTime(10, 0))
        for edit in (self.start_edit, self.end_edit):
            edit.setDisplayFormat("HH:mm")
            edit.setToolTip("시간을 직접 입력하거나, 마우스 휠 · ↑↓ 키로 바꿀 수 있어요")
        self.all_day.toggled.connect(self._sync_enabled)

        self.color_group = QButtonGroup(self)
        self._swatches = {}
        swatch_row = QHBoxLayout()
        for name in COLORS:
            button = QPushButton()
            button.setCheckable(True)
            button.setFixedSize(30, 30)
            button.setToolTip(name)
            button.setStyleSheet(
                f"QPushButton {{ background: {tokens.SWATCH[name]}; border: 2px solid transparent;"
                f" border-radius: 15px; padding: 0; }}"
                f"QPushButton:checked {{ border: 2px solid {tokens.TEXT}; }}"
            )
            self.color_group.addButton(button)
            self._swatches[name] = button
            swatch_row.addWidget(button)
        swatch_row.addStretch(1)
        self._swatches["yellow"].setChecked(True)

        self.reminder = RoseComboBox()
        for label, minutes in REMINDERS:
            self.reminder.addItem(label, minutes)
        self.recurrence = RoseComboBox()
        for label, value in RECURRENCES:
            self.recurrence.addItem(label, value)
        self.recurrence.currentIndexChanged.connect(self._sync_enabled)
        self.has_until = RoseCheckBox("반복 종료일")
        self.has_until.toggled.connect(self._sync_enabled)
        self.until_edit = RoseDateEdit()
        self.until_edit.setCalendarPopup(True)
        self.until_edit.setDisplayFormat("yyyy-MM-dd")

        form = QFormLayout()
        form.addRow("제목", self.title_edit)
        form.addRow("날짜", self.date_edit)
        end_row = QHBoxLayout()
        end_row.addWidget(self.has_end_date)
        end_row.addWidget(self.end_date_edit, 1)
        form.addRow("", end_row)
        time_row = QHBoxLayout()
        time_row.addWidget(self.start_edit)
        time_row.addWidget(QLabel("~"))
        time_row.addWidget(self.end_edit)
        time_row.addWidget(self.all_day)
        form.addRow("시간", time_row)
        form.addRow("색상", swatch_row)
        form.addRow("알림", self.reminder)
        form.addRow("반복", self.recurrence)
        until_row = QHBoxLayout()
        until_row.addWidget(self.has_until)
        until_row.addWidget(self.until_edit, 1)
        form.addRow("", until_row)

        self.error = QLabel()
        self.error.setObjectName("error")

        buttons = QHBoxLayout()
        if editing:
            delete = QPushButton("삭제")
            delete.setObjectName("danger")
            delete.clicked.connect(self._on_delete)
            buttons.addWidget(delete)
            duplicate = QPushButton("복제")
            duplicate.setToolTip("이 일정과 같은 내용으로 새 일정을 만듭니다 (날짜는 새로 고릅니다)")
            duplicate.clicked.connect(self._on_duplicate)
            buttons.addWidget(duplicate)
        buttons.addStretch(1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        save = QPushButton("저장")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        heading = QLabel("일정 수정" if editing else "일정 추가")
        heading.setObjectName("dialogTitle")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(heading)
        if notice:
            note = QLabel(notice)
            note.setObjectName("note")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addLayout(buttons)

        # 초안(draft)은 저장된 일정이 아니라서 self.occurrence 는 비워 두고, 값만 폼에 채운다
        prefill = occurrence or (
            Occurrence(draft, draft.start_at.date(), draft.start_at, draft.end_at) if draft is not None else None
        )
        self._load(day, prefill)
        if occurrence is None and initial_title and draft is None:
            self.title_edit.setText(initial_title)
        self._sync_enabled()

    # ---- 값 <-> 폼 -------------------------------------------------------

    def _load(self, day: date | None, occurrence: Occurrence | None) -> None:
        if occurrence is None:
            self.date_edit.setDate(QDate(day.year, day.month, day.day) if day else QDate.currentDate())
            self.end_date_edit.setDate(self.date_edit.date())
            self.until_edit.setDate(self.date_edit.date())
            return
        s = occurrence.schedule
        self.title_edit.setText(s.title)
        self.date_edit.setDate(QDate(occurrence.date.year, occurrence.date.month, occurrence.date.day))
        last = occurrence.last_day
        self.end_date_edit.setDate(QDate(last.year, last.month, last.day))
        self.has_end_date.setChecked(occurrence.is_multiday)
        self.all_day.setChecked(s.all_day)
        self.start_edit.setTime(QTime(occurrence.start_at.hour, occurrence.start_at.minute))
        end = occurrence.end_at or (occurrence.start_at + timedelta(hours=1))
        self.end_edit.setTime(QTime(end.hour, end.minute))
        self._swatches[s.color].setChecked(True)
        self._select(self.reminder, s.remind_before_min, f"{s.remind_before_min}분 전")
        self._select(self.recurrence, s.recurrence)
        if s.recurrence_until:
            self.has_until.setChecked(True)
            u = s.recurrence_until
            self.until_edit.setDate(QDate(u.year, u.month, u.day))
        else:
            self.until_edit.setDate(self.date_edit.date())

    @staticmethod
    def _select(combo: RoseComboBox, value, fallback_label: str | None = None) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
        if fallback_label is not None:  # 목록에 없는 값(예: AI가 만든 15분 전)도 보존한다
            combo.addItem(fallback_label, value)
            combo.setCurrentIndex(combo.count() - 1)

    def _keep_end_after_start(self) -> None:
        """시작일을 종료일보다 뒤로 옮기면 종료일도 따라간다. 종료 날짜를 안 쓸 때는 항상 시작일과 같다."""
        if self.has_end_date.isChecked():
            self.end_date_edit.setMinimumDate(self.date_edit.date())  # 종료일이 더 빠르면 Qt가 끌어올린다
        else:
            self.end_date_edit.setDate(self.date_edit.date())

    def _sync_enabled(self) -> None:
        self.end_date_edit.setEnabled(self.has_end_date.isChecked())
        if self.has_end_date.isChecked():
            self.end_date_edit.setMinimumDate(self.date_edit.date())
        else:
            self.end_date_edit.setMinimumDate(QDate(1900, 1, 1))
            self.end_date_edit.setDate(self.date_edit.date())
        timed = not self.all_day.isChecked()
        self.start_edit.setEnabled(timed)
        self.end_edit.setEnabled(timed)
        self.reminder.setEnabled(timed)  # 종일 일정은 알림 기준 시각이 없어 알림을 쓰지 않는다
        repeats = self.recurrence.currentData() is not None
        self.has_until.setEnabled(repeats)
        self.until_edit.setEnabled(repeats and self.has_until.isChecked())

    def schedule(self) -> Schedule:
        d: date = self.date_edit.date().toPython()
        end_d: date = self.end_date_edit.date().toPython() if self.has_end_date.isChecked() else d
        all_day = self.all_day.isChecked()
        if all_day:
            start_at = datetime.combine(d, datetime.min.time())
            end_at = datetime.combine(end_d, datetime.min.time()) if end_d > d else None
        else:
            start_at = datetime.combine(d, self.start_edit.time().toPython())
            end_at = datetime.combine(end_d, self.end_edit.time().toPython())
        recurrence = self.recurrence.currentData()
        until = (
            self.until_edit.date().toPython()
            if recurrence is not None and self.has_until.isChecked()
            else None
        )
        color = next(name for name, b in self._swatches.items() if b.isChecked())
        return Schedule(
            id=self.occurrence.schedule.id if self.occurrence else None,
            title=self.title_edit.text().strip(),
            start_at=start_at,
            end_at=end_at,
            all_day=all_day,
            color=color,
            recurrence=recurrence,
            recurrence_until=until,
            remind_before_min=None if all_day else self.reminder.currentData(),
        )

    def _on_save(self) -> None:
        try:
            validate(self.schedule())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.action = "save"
        self.accept()

    def _on_delete(self) -> None:
        self.action = "delete"
        self.accept()

    def _on_duplicate(self) -> None:
        self.action = "duplicate"
        self.accept()


class DayListDialog(BackdropDialog):
    """셀에 다 표시되지 못한 일정과 To-Do를 날짜별로 보여 준다 (FR-CAL-006).

    To-Do는 셀과 같은 TodoRow라서 여기서도 바로 수정·완료·삭제할 수 있다.
    저장은 하지 않고 todo_action만 내보내며, 바뀐 목록은 set_items()로 다시 받는다.
    """

    todo_action = Signal(str, object, object)

    def __init__(self, parent, day: date, occurrences: list[Occurrence], todos: list[Todo]):
        super().__init__(parent)
        self.day = day
        self.setWindowTitle(f"{day.month}월 {day.day}일")
        self.setMinimumWidth(320)
        self.selected: Occurrence | None = None
        heading = QLabel(f"{day.month}월 {day.day}일 ({WEEKDAYS[(day.weekday() + 1) % 7]})")
        heading.setObjectName("dialogTitle")
        self._layout = QVBoxLayout()
        self._layout.setSpacing(6)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(10)
        outer.addWidget(heading)
        outer.addLayout(self._layout)
        self.set_items(occurrences, todos)

    def set_items(self, occurrences: list[Occurrence], todos: list[Todo]) -> None:
        clear_layout(self._layout)
        for occ in occurrences:
            label = occ.title if occ.all_day else f"{occ.start_at:%H:%M}  {occ.title}"
            if occ.is_multiday:
                label += f"  ({occ.first_day:%m/%d}~{occ.last_day:%m/%d})"
            button = QPushButton(label)
            button.setStyleSheet(
                f"QPushButton {{ background: {tokens.CHIP[occ.color]}; border: 0; text-align: left; }}"
            )
            button.clicked.connect(lambda _=False, o=occ: self._pick(o))
            self._layout.addWidget(button)
        for todo in todos:
            row = TodoRow(todo)
            row.action.connect(self.todo_action)
            self._layout.addWidget(row)
            row.show()
        if not occurrences and not todos:
            empty = QLabel("항목이 없습니다")
            empty.setObjectName("empty")
            self._layout.addWidget(empty)

    def _pick(self, occ: Occurrence) -> None:
        self.selected = occ
        self.accept()
