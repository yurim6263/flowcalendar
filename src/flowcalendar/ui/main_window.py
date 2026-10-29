from dataclasses import replace
from datetime import date, datetime, timedelta

from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Occurrence, Todo
from flowcalendar.ui import tokens
from flowcalendar.ui import backdrop
from flowcalendar.ui.backdrop import BackdropWidget
from flowcalendar.ui.calendar_view import CalendarGrid
from flowcalendar.ui.dialogs import (
    AddChooserDialog,
    DatePickDialog,
    DayListDialog,
    ScheduleDialog,
    TodoDialog,
)
from flowcalendar.ui.icons import chevron_icon, hamburger_icon, search_icon, sparkle_icon
from flowcalendar.ui.message_dialog import ask_choice, confirm
from flowcalendar.ai import briefing as ai_briefing
from flowcalendar.ai.quick_add import describe
from flowcalendar.ai.errors import AIError
from flowcalendar.domain.models import Schedule
from flowcalendar.services.ai_service import find_duplicates
from flowcalendar.ui.ai_dialogs import DraftListDialog, QuickAddDialog, error_text
from flowcalendar.services.search import search_all
from flowcalendar.ui.briefing_card import BriefingCard
from flowcalendar.ui.search_dialog import SearchDialog
from flowcalendar.ui.overlay_menu import OverlayMenu
from flowcalendar.ui.side_panel import MemoCard, QuickTodoCard
from flowcalendar.ui.toast import UndoToast
from flowcalendar.ui.widgets import DragBar, keyboard_focus_only
from flowcalendar.services import desktop_widget


HEADER_BUTTON_H = 32  # 머리글 버튼(이전·오늘·다음, AI, M, 메뉴)의 공통 높이


class MainWindow(QMainWindow):
    settings_requested = Signal()
    hidden_to_tray = Signal()  # hide_on_close 로 창을 숨겼다 (첫 안내용)
    ai_registered = Signal(str)  # AI 가 자동으로 등록했다는 안내 (창이 가려져 있으면 앱이 트레이 알림으로 보여 준다)
    widget_mode_changed = Signal(bool)
    widget_geometry_changed = Signal(str)  # "x,y,w,h" (위젯 모드에서 옮기거나 크기를 바꾼 뒤)

    def __init__(
        self,
        repo: ScheduleRepository,
        todo_repo: TodoRepository,
        memo_repo: MemoRepository,
        today: date | None = None,
    ):
        super().__init__()
        self.repo = repo
        self.todo_repo = todo_repo
        self.memo_repo = memo_repo
        self._today = today
        self._day_dialog: DayListDialog | None = None
        self._toast: UndoToast | None = None
        self._menu: OverlayMenu | None = None
        self.ai_service = None  # set_ai() 로 연결한다. 없거나 키가 없으면 AI 화면은 모두 숨긴다
        self.ai_inbox = None  # 처리하지 못한 빠른 추가 입력 목록
        self.task_runner = None
        self._briefing_card: BriefingCard | None = None
        self._briefing_token = 0
        self.hide_on_close = False  # 트레이가 준비되면 앱이 켠다
        self._widget_mode = False
        self._widget_opacity = tokens.WIDGET_OPACITY_DEFAULT
        self._normal_geometry: QRect | None = None
        self._raised = False  # 위젯 모드에서 '열기'로 잠시 앞으로 올린 상태
        self._raised_active = False
        self._pinned_hwnd = 0
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(400)
        self._geometry_timer.timeout.connect(self._emit_geometry)
        t = self.today()
        self.year, self.month = t.year, t.month
        self.setWindowTitle("Flow Calendar")
        self.resize(*self._default_size())

        self.prev_btn = QPushButton()
        self.next_btn = QPushButton()
        self.today_btn = QPushButton("오늘")
        self.prev_btn.setObjectName("nav")
        self.next_btn.setObjectName("nav")
        self.prev_btn.setToolTip("이전 달")
        self.next_btn.setToolTip("다음 달")
        self.prev_btn.clicked.connect(lambda: self.shift_month(-1))
        self.next_btn.clicked.connect(lambda: self.shift_month(1))
        self.today_btn.clicked.connect(self.go_today)
        self.title = QLabel()
        self.title.setObjectName("title")

        self.header_bar = DragBar()
        header = QHBoxLayout(self.header_bar)
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.prev_btn)
        header.addWidget(self.today_btn)
        header.addWidget(self.next_btn)
        header.addSpacing(24)
        header.addWidget(self.title)
        header.addStretch(1)
        # M: 현재 보기(월간). Week/Day 는 Ver1.x 라서 누르면 보기 메뉴만 열린다.
        self.view_btn = QPushButton("M")
        self.view_btn.setObjectName("headerBtn")
        self.view_btn.setToolTip("월간 보기")
        self.view_btn.clicked.connect(lambda: self.open_view_menu(self.view_btn))
        self.menu_btn = QPushButton()
        self.menu_btn.setObjectName("headerBtn")
        self.menu_btn.setToolTip("메뉴")
        self.menu_btn.clicked.connect(self.open_main_menu)
        self.search_btn = QPushButton()
        self.search_btn.setObjectName("headerBtn")
        self.search_btn.setToolTip("검색 (Ctrl+F)")
        self.search_btn.clicked.connect(self.open_search)
        self.ai_btn = QPushButton()
        self.ai_btn.setObjectName("headerBtn")
        self.ai_btn.setToolTip("AI 빠른 추가 (문장으로 일정/할 일 만들기)")
        self.ai_btn.clicked.connect(self.open_quick_add)
        self.ai_btn.hide()
        header.addWidget(self.search_btn)
        header.addWidget(self.ai_btn)
        header.addWidget(self.view_btn)
        header.addWidget(self.menu_btn)
        # 머리글 버튼은 높이를 같게 고정한다 (글자·아이콘 버튼의 높이가 제각각이던 것을 맞춘다)
        for button in (self.prev_btn, self.today_btn, self.next_btn, self.search_btn, self.ai_btn, self.view_btn,
                       self.menu_btn):
            button.setFixedHeight(HEADER_BUTTON_H)
        self._set_header_icons()
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.open_search)  # 검색
        keyboard_focus_only(self.header_bar)

        self.grid = CalendarGrid()
        self.grid.add_clicked.connect(self.on_add)
        self.grid.occurrence_clicked.connect(self.on_edit)
        self.grid.overflow_clicked.connect(self.on_overflow)
        self.grid.todo_action.connect(self.on_todo_action)
        self.grid.occurrence_dropped.connect(self.on_occurrence_dropped)

        grid_card = QFrame()
        grid_card.setObjectName("card")
        grid_layout = QVBoxLayout(grid_card)
        grid_layout.setContentsMargins(8, 4, 8, 8)
        grid_layout.addWidget(self.grid)

        side = QVBoxLayout()
        side.setSpacing(16)
        self.quick_card = QuickTodoCard()
        self.quick_card.add_clicked.connect(self.on_quick_add)
        self.quick_card.todo_action.connect(self.on_todo_action)
        self.memo_card = MemoCard()
        self.memo_card.edit.set_content(self.memo_repo.get())
        self.memo_card.edit.changed.connect(self.memo_repo.set)
        self.memo_card.convert_requested.connect(self.convert_memo_selection)
        side.addWidget(self.quick_card, 1)
        side.addWidget(self.memo_card, 1)

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(grid_card, 3)
        content.addLayout(side, 1)
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 20)
        body.setSpacing(12)
        body.addWidget(self.header_bar)
        body.addLayout(content, 1)
        root = BackdropWidget()
        root.setLayout(body)
        self.setCentralWidget(root)
        self.size_grip = QSizeGrip(root)  # 테두리 없는 위젯 모드에서 크기를 바꾸는 손잡이
        self.size_grip.hide()
        self._apply_opacity()  # 새 창은 항상 일반 모드로 시작하므로 팝업 투명도도 불투명으로 맞춘다
        self.refresh()

    def _default_size(self) -> tuple[int, int]:
        """1280x820 을 기본으로 하되, 작업 표시줄을 뺀 화면보다 크면 화면 안에 들어오게 줄인다."""
        screen = self.screen()
        if screen is None:
            return 1280, 820
        avail = screen.availableGeometry()
        # 제목 표시줄과 창 테두리 몫으로 세로 40px, 가로 20px 을 남긴다. 너무 작아지지 않게 하한을 둔다.
        return max(min(1280, avail.width() - 20), 900), max(min(820, avail.height() - 40), 600)

    def today(self) -> date:
        return self._today or date.today()

    # ---- 월 이동 / 갱신 ---------------------------------------------------

    def shift_month(self, delta: int) -> None:
        index = self.year * 12 + (self.month - 1) + delta
        self.year, self.month = index // 12, index % 12 + 1
        self.refresh_calendar()

    def go_today(self) -> None:
        t = self.today()
        self.year, self.month = t.year, t.month
        self.refresh_calendar()

    def refresh_calendar(self) -> None:
        start, end = self.grid.visible_range(self.year, self.month)
        occurrences = self.repo.list_occurrences(start, end)
        todos = self.todo_repo.list_daily(start, end)
        self.grid.set_month(self.year, self.month, occurrences, self.today(), todos)
        self.title.setText(f"{self.year}년 {self.month}월")

    def refresh(self) -> None:
        """데이터가 바뀐 뒤 화면 전체(캘린더, Quick To-Do, 열려 있는 날짜 목록)를 다시 그린다."""
        self.refresh_calendar()
        self.quick_card.set_todos(self.todo_repo.list_quick())
        if self._day_dialog is not None:
            self._day_dialog.set_items(*self._day_items(self._day_dialog.day))

    def _day_items(self, day: date) -> tuple[list[Occurrence], list[Todo]]:
        return self.repo.list_occurrences(day, day), self.todo_repo.list_daily(day, day)

    # ---- AI (키가 있을 때만 보인다) --------------------------------------------------------------

    AI_DRAFT_NOTICE = "AI가 만든 초안입니다. 내용을 확인하고 고친 뒤 저장하세요."

    def set_ai(self, service, runner, inbox=None) -> None:
        self.ai_service, self.task_runner, self.ai_inbox = service, runner, inbox
        self.refresh_ai()

    @property
    def ai_available(self) -> bool:
        return self.ai_service is not None and self.ai_service.has_key()

    def refresh_ai(self) -> None:
        """키를 넣거나 지웠을 때 ✨ 버튼, 메모의 AI 버튼, 메뉴 항목을 맞춘다 (FR-AI-003)."""
        available = self.ai_available
        self.ai_btn.setVisible(available)
        self.memo_card.set_ai_available(available)

    def open_quick_add(self) -> None:
        if not self.ai_available:
            return
        auto = self.auto_register_enabled()
        dialog = QuickAddDialog(self, self.ai_service, self.task_runner, inbox=self.ai_inbox, auto_register=auto)
        dialog.exec()
        self._announce_model_fallback()
        if dialog.outcome == "drafts" and auto:
            self._auto_register_drafts(dialog.drafts, dialog.source_text)
        elif dialog.outcome == "drafts":
            self._review_drafts(dialog.drafts, single_form=True)
        elif dialog.outcome == "manual":  # AI 가 안 될 때 막히지 않게 수동 입력으로 넘어간다
            self.on_add(self.today(), initial_title=dialog.manual_text)
        elif dialog.outcome == "settings":  # 모델 이름/키 오류: 고치러 설정을 연다
            self.settings_requested.emit()

    def _announce_model_fallback(self) -> None:
        """AI 모델이 사라져 대신 쓴 모델로 바꿨다면 알려 준다."""
        notice = self.ai_service.apply_fallback() if self.ai_service is not None else None
        if notice:
            self._show_toast(notice, None)

    def auto_register_enabled(self) -> bool:
        return self.ai_service is not None and self.ai_service.settings.get_bool("ai_auto_register")

    def _auto_register_drafts(self, drafts, source_text: str) -> None:
        """✨ 빠른 추가 결과를 확인 없이 바로 등록한다 (설정에서 끌 수 있다).
        그 대신 등록 직후 5초 동안 되돌릴 수 있고, 같은 날 같은 제목이 이미 있으면 건너뛴다."""
        duplicates = find_duplicates(drafts, self.repo, self.todo_repo)
        created, skipped, failed = [], 0, []
        for draft, duplicate in zip(drafts, duplicates):
            if duplicate:
                skipped += 1
                continue
            try:
                if draft.is_schedule:
                    item = draft.to_schedule()
                    created.append((self.repo, self.repo.add(item), describe(item)))
                else:
                    item = draft.to_todo()
                    created.append((self.todo_repo, self.todo_repo.add(item), describe(item)))
            except ValueError as exc:  # 검증을 통과하지 못한 후보: 나머지는 계속 등록한다
                failed.append(str(exc))
        if created:
            self.refresh()
        if failed and self.ai_inbox is not None:
            self.ai_inbox.add(source_text, f"등록하지 못함: {failed[0]}")  # 입력한 글은 잃지 않는다

        parts = []
        if created:
            summary = created[0][2]
            summary = summary if len(summary) <= 46 else summary[:45] + "…"
            parts.append(f"AI가 {len(created)}개를 등록했어요 · {summary}" + (" 외" if len(created) > 1 else ""))
        if skipped:
            parts.append(f"이미 있는 {skipped}개는 건너뜀" if created else "이미 같은 항목이 있어 등록하지 않았어요")
        if failed:
            parts.append(f"{len(failed)}개는 등록하지 못함 (미처리 목록에 남김)")
        message = " · ".join(parts)

        def undo() -> None:
            for repo, item_id, _ in created:
                repo.delete(item_id)
            self.refresh()

        self._show_toast(message, undo if created else None)
        self.ai_registered.emit(message)

    def convert_memo_selection(self, text: str) -> None:
        """메모에서 사용자가 고른 글만 AI 에 보내 후보를 받는다. 메모 내용은 바꾸지 않는다."""
        if not self.ai_available or not text.strip():
            return
        dialog = QuickAddDialog(self, self.ai_service, self.task_runner, memo_text=text)
        dialog.exec()
        if dialog.outcome == "drafts":
            self._review_drafts(dialog.drafts, single_form=False)
        elif dialog.outcome == "settings":
            self.settings_requested.emit()
        elif dialog.outcome == "manual":
            first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            self.on_add(self.today(), initial_title=first_line[:100])

    def _review_drafts(self, drafts, *, single_form: bool) -> None:
        """AI 후보는 미리보기를 거쳐 사용자가 확인한 것만 저장한다 (FR-AI-005)."""
        items = [d.to_schedule() if d.is_schedule else d.to_todo() for d in drafts]
        if single_form and len(items) == 1:
            saved = self._edit_candidate(items[0])
            chosen = [saved] if saved is not None else []
        else:
            notice = ("선택한 메모 내용만 AI에 보냈습니다. 체크한 항목만 등록되고, 메모는 바뀌지 않습니다."
                      if not single_form else "체크한 항목만 등록됩니다.")
            dialog = DraftListDialog(self, items, find_duplicates(drafts, self.repo, self.todo_repo),
                                     notice=notice, edit_item=self._edit_candidate)
            chosen = dialog.chosen() if dialog.exec() == dialog.DialogCode.Accepted else []
        for item in chosen:
            (self.repo if isinstance(item, Schedule) else self.todo_repo).add(item)
        if chosen:
            self.refresh()

    def _edit_candidate(self, item):
        """후보 하나를 일정/할 일 입력 팝업에 채워 보여 주고, 사용자가 저장한 결과(없으면 None)를 돌려준다."""
        if isinstance(item, Schedule):
            dialog = ScheduleDialog(self, draft=item, notice=self.AI_DRAFT_NOTICE)
            ok = dialog.exec() == dialog.DialogCode.Accepted and dialog.action == "save"
            return dialog.schedule() if ok else None
        dialog = TodoDialog(self, day=item.day, todo=item, notice=self.AI_DRAFT_NOTICE)
        return dialog.todo() if dialog.exec() == dialog.DialogCode.Accepted else None

    def show_briefing(self, period: str = "day") -> None:
        if not self.ai_available:
            return
        start, end = ai_briefing.period_range(period, self.today())
        data = ai_briefing.build_data(
            period, self.today(), self.repo.list_occurrences(start, end),
            self.todo_repo.list_daily(start, end), self.todo_repo.list_quick(),
        )
        if self._briefing_card is None:
            self._briefing_card = BriefingCard(self)
            self._briefing_card.period_requested.connect(self.show_briefing)
        card = self._briefing_card
        self._briefing_token += 1
        token = self._briefing_token
        card.show_loading(data)
        card.show()
        card.place()

        def current() -> bool:  # 기간을 바꾸거나 닫은 뒤에 늦게 온 결과는 버린다
            return token == self._briefing_token and card.isVisible()

        try:
            call = self.ai_service.prepare()  # 설정/키 읽기는 화면 스레드에서
        except AIError as exc:
            card.show_error(data, error_text(exc))
            return
        self.task_runner.run(
            lambda: self.ai_service.summarize_with(call, data),
            lambda summary: (self._announce_model_fallback(), card.show_summary(data, summary) if current() else None),
            lambda exc: card.show_error(data, error_text(exc)) if current() else None,
        )

    def _set_header_icons(self) -> None:
        self.prev_btn.setIcon(chevron_icon("prev"))
        self.next_btn.setIcon(chevron_icon("next"))
        self.menu_btn.setIcon(hamburger_icon())
        self.ai_btn.setIcon(sparkle_icon())
        self.search_btn.setIcon(search_icon())

    def retheme(self) -> None:
        """테마가 바뀐 뒤 색을 코드로 지정한 부분(아이콘, 칸, 막대, 할 일 줄)을 새 색으로 다시 만든다."""
        self._set_header_icons()
        self.grid.retheme()
        self.refresh()

    def reload_all(self) -> None:
        """파일 가져오기처럼 DB가 통째로 바뀐 뒤 메모까지 포함해 다시 읽는다."""
        self.memo_card.edit.set_content(self.memo_repo.get())
        self.refresh()

    # ---- 위젯 모드: 테두리 없이 항상 다른 창 뒤에 둔다 ----------------------------

    @property
    def widget_mode(self) -> bool:
        return self._widget_mode

    def set_widget_mode(self, on: bool, geometry: QRect | None = None) -> None:
        """geometry 는 위젯 모드에서 쓸 마지막 위치/크기. 일반 모드로 돌아가면 이전 위치로 복원한다."""
        if on == self._widget_mode:
            if on and geometry is not None:
                self.setGeometry(geometry)
            return
        was_visible = self.isVisible()
        self._unpin()
        if on:
            self._normal_geometry = self.geometry()
        # 투명(알파) 창인지는 네이티브 창을 만들 때 정해진다. 이미 만든 창에 투명 속성만 켜면 투명해야 할 곳이
        # 검게 나오고 색도 어두워지므로(모서리의 검정 쐐기), 전환할 때는 기존 네이티브 창을 버리고 새로 만든다.
        self.hide()
        self.destroy()
        if on:
            self.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            )
        else:
            self.setWindowFlags(Qt.WindowType.Window)
        self._widget_mode = on
        # 테두리가 없는 위젯 모드에서만 창 자체를 투명하게 한다. 일반 창은 불투명(Windows 제약 + 가독성).
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, on)
        self._apply_opacity()
        self.header_bar.drag_enabled = on
        self.size_grip.setVisible(on)
        if on and geometry is not None:
            self.setGeometry(geometry)
        elif not on and self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
        if was_visible:
            self.show()  # setWindowFlags 는 창을 숨기므로 다시 보여 준다
        self.widget_mode_changed.emit(on)

    @property
    def widget_opacity(self) -> int:
        return self._widget_opacity

    def set_widget_opacity(self, percent: int) -> None:
        """위젯 모드 배경 투명도(%). 범위를 벗어난 값은 잘라 쓴다."""
        self._widget_opacity = max(tokens.WIDGET_OPACITY_MIN, min(100, int(percent)))
        self._apply_opacity()

    def _apply_opacity(self) -> None:
        """위젯 모드에서만: 배경 투명도 + 둥근 모서리 + 팝업 투명도. 일반 창과 그 팝업은 불투명."""
        value = self._widget_opacity / 100 if self._widget_mode else 1.0
        root = self.centralWidget()
        root.set_opacity(value)
        root.set_corner_radius(tokens.WINDOW_RADIUS if self._widget_mode else 0)
        backdrop.set_popup_opacity(value)

    def _pin(self) -> None:
        if desktop_widget.is_supported() and self._widget_mode:
            self._pinned_hwnd = int(self.winId())
            desktop_widget.remove_system_chrome(self._pinned_hwnd)
            desktop_widget.pinner().pin(self._pinned_hwnd)
            desktop_widget.send_to_bottom(self._pinned_hwnd)

    def _unpin(self) -> None:
        if self._pinned_hwnd:
            desktop_widget.pinner().unpin(self._pinned_hwnd)
            self._pinned_hwnd = 0
        self._raised = self._raised_active = False

    def bring_forward(self) -> None:
        """트레이 '열기' 나 두 번째 실행처럼 사용자가 명시적으로 부를 때만 잠깐 앞으로 올린다.
        다른 창을 클릭해 활성화가 넘어가면 다시 뒤로 돌아간다."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        if self._widget_mode and self._pinned_hwnd:
            self._raised = True
            desktop_widget.pinner().suspend(self._pinned_hwnd)
        self.raise_()
        self.activateWindow()
        self._raised_active = self._raised and self.isActiveWindow()

    def showEvent(self, event):
        super().showEvent(event)
        self._pin()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._unpin()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange:
            if self._widget_mode and self._pinned_hwnd:
                desktop_widget.remove_system_chrome(self._pinned_hwnd)  # Windows 가 다시 켜는 경우 대비
            if self._raised and self.isActiveWindow():
                self._raised_active = True
            elif self._raised and self._raised_active and self._pinned_hwnd:
                # 앞으로 올라와 활성화됐다가 다른 창으로 넘어갔다: 다시 뒤로 돌아간다.
                # (활성화되기 전에 오는 비활성화 이벤트로 곧바로 되돌리면 '열기'가 무의미해진다)
                self._raised = self._raised_active = False
                desktop_widget.pinner().resume(self._pinned_hwnd)
                desktop_widget.send_to_bottom(self._pinned_hwnd)
        elif event.type() == QEvent.Type.WindowStateChange:
            # '바탕화면 보기'(Win+D) 등으로 최소화돼도 위젯은 바탕화면에 남아 있어야 한다.
            if self._widget_mode and self.isMinimized():
                QTimer.singleShot(0, self._restore_from_minimize)

    def _restore_from_minimize(self) -> None:
        if self._widget_mode and self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            self.show()
            self._pin()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        root = self.centralWidget()
        if root is not None:
            grip = self.size_grip
            grip.move(root.width() - grip.sizeHint().width() - 6, root.height() - grip.sizeHint().height() - 6)
            grip.raise_()
        self._schedule_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_geometry()

    def _schedule_geometry(self) -> None:
        if self._widget_mode and self.isVisible():
            self._geometry_timer.start()

    def _emit_geometry(self) -> None:
        g = self.geometry()
        self.widget_geometry_changed.emit(f"{g.x()},{g.y()},{g.width()},{g.height()}")

    def closeEvent(self, event):
        self.memo_card.edit.flush()
        if self.hide_on_close:  # 창을 닫아도 트레이에 남아 알림을 계속 울린다 (FR-DESK-001)
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            return
        super().closeEvent(event)

    # ---- 메뉴 (Overlay Popup) --------------------------------------------

    def open_main_menu(self) -> None:
        menu = OverlayMenu(self)
        menu.add_item("settings", "설정", self.settings_requested.emit)
        menu.add_item(
            "widget",
            "위젯 모드 끄기 (일반 창)" if self._widget_mode else "위젯 모드 켜기 (바탕화면 뒤에 고정)",
            lambda: self.set_widget_mode(not self._widget_mode),
        )
        if self._widget_mode:
            menu.add_item("hide", "트레이로 숨기기", self.close)
        if self.ai_available:
            menu.add_item("ai_quick", "AI 빠른 추가", self.open_quick_add)
            menu.add_item("ai_briefing", "브리핑 보기", lambda: self.show_briefing("day"))
        menu.add_item("view", "캘린더 보기   ›", lambda: self.open_view_menu(self.menu_btn),
                      close_on_click=True)
        self._menu = menu
        menu.popup_below(self.menu_btn)

    def open_view_menu(self, anchor: QWidget) -> None:
        menu = OverlayMenu(self)
        menu.add_item("month", "● 월간 보기")
        menu.add_item("week", "○ 주간 보기 (Ver1.x)", enabled=False)
        menu.add_item("day", "○ 일간 보기 (Ver1.x)", enabled=False)
        self._menu = menu
        menu.popup_below(anchor)

    # ---- 일정 추가 / 수정 / 삭제 -------------------------------------------

    def on_add(self, day: date, initial_title: str = "") -> None:
        chooser = AddChooserDialog(self)
        if chooser.exec() != chooser.DialogCode.Accepted:
            return
        if chooser.choice == "schedule":
            dialog = ScheduleDialog(self, day=day, initial_title=initial_title)
            if dialog.exec() == dialog.DialogCode.Accepted and dialog.action == "save":
                self.repo.add(dialog.schedule())
                self.refresh()
        elif chooser.choice == "todo":
            self._add_todo(day, initial_title)

    # ---- 검색 ----------------------------------------------------------------------------

    def open_search(self) -> None:
        dialog = SearchDialog(
            self, lambda q: search_all(self.repo, self.todo_repo, self.memo_repo, q, self.today())
        )
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected is None:
            return
        self.open_search_result(*dialog.selected)

    def open_search_result(self, kind: str, item) -> None:
        """검색 결과로 이동한다: 일정은 그 달로 가서 수정 팝업, 할 일은 그 날 목록, 메모는 찾은 글을 고른 상태로."""
        if kind == "schedule":
            day = item.start_at.date()
            self.year, self.month = day.year, day.month
            self.refresh_calendar()
            self.on_edit(Occurrence(item, day, item.start_at, item.end_at))
        elif kind == "todo":
            if item.day is not None:
                self.year, self.month = item.day.year, item.day.month
                self.refresh_calendar()
                self.on_overflow(item.day)
            else:
                self._show_toast(f"Quick To-Do에 있어요 · {item.title}", None)
        elif kind == "memo":
            edit = self.memo_card.edit
            edit.moveCursor(edit.textCursor().MoveOperation.Start)
            if edit.find(item):  # 찾은 글이 선택돼 보인다
                edit.setFocus()

    def on_quick_add(self) -> None:
        self._add_todo(None)

    def _add_todo(self, day: date | None, initial_title: str = "") -> None:
        dialog = TodoDialog(self, day=day, initial_title=initial_title)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.todo_repo.add(dialog.todo())
            self.refresh()

    def on_overflow(self, day: date) -> None:
        dialog = DayListDialog(self, day, *self._day_items(day))
        dialog.todo_action.connect(self.on_todo_action)
        self._day_dialog = dialog
        try:
            accepted = dialog.exec() == dialog.DialogCode.Accepted
        finally:
            self._day_dialog = None
        if accepted and dialog.selected:
            self.on_edit(dialog.selected)

    # ---- To-Do 동작 (셀, 날짜 목록, Quick 패널이 모두 여기로 모인다) ---------------

    def on_todo_action(self, kind: str, todo: Todo, value) -> None:
        if kind == "toggle":
            self.todo_repo.update(replace(todo, done=bool(value)))
        elif kind == "rename":
            self.todo_repo.update(replace(todo, title=value))
        elif kind == "priority":
            self.todo_repo.update(replace(todo, priority=value))
        elif kind == "delete":
            snapshot = self.todo_repo.delete(todo.id)
            self.refresh()
            if snapshot is not None:
                self._show_undo(snapshot)
            return
        elif kind == "move":
            dialog = DatePickDialog(self, start=self.today())
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            self.todo_repo.move_to_date(todo.id, dialog.day())
        self.refresh()

    def _show_undo(self, snapshot: Todo) -> None:
        title = snapshot.title if len(snapshot.title) <= 14 else snapshot.title[:13] + "…"
        self._show_toast(f"'{title}' 삭제됨", lambda: self._undo_delete(snapshot))

    def _show_toast(self, message: str, on_undo) -> None:
        """아래쪽에 잠깐 뜨는 안내. on_undo 가 있으면 5초 동안 '되돌리기'를 누를 수 있다."""
        if self._toast is not None:
            self._toast.dismiss()
        host = self._day_dialog or self.centralWidget()
        self._toast = UndoToast(host, message, on_undo)

    def _undo_delete(self, snapshot: Todo) -> None:
        self.todo_repo.restore(snapshot)
        self.refresh()

    def on_edit(self, occ: Occurrence) -> None:
        dialog = ScheduleDialog(self, occurrence=occ)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        recurring = occ.schedule.recurrence is not None
        sid = occ.schedule.id
        if dialog.action == "duplicate":
            self._duplicate_schedule(occ)
            return
        if dialog.action == "delete":
            if recurring:
                scope = self._ask_scope("삭제")
                if scope == "this":
                    self.repo.delete_occurrence(sid, occ.date)
                elif scope == "following":
                    self.repo.delete_from(sid, occ.date)
                else:
                    return
            elif self._confirm_delete(occ.title):
                self.repo.delete(sid)
            else:
                return
        elif dialog.action == "save":
            new = dialog.schedule()
            if recurring:
                scope = self._ask_scope("수정")
                if scope == "this":
                    self.repo.update_occurrence(sid, occ.date, new)
                elif scope == "following":
                    self.repo.update_from(sid, occ.date, new)
                else:
                    return
            else:
                self.repo.update(new)
        self.refresh()

    # ---- 끌어서 옮기기 / 복사 ----------------------------------------------------------------

    def on_occurrence_dropped(self, schedule_id: int, occ_date: date, delta_days: int, copy: bool) -> None:
        """일정을 다른 날로 끌어다 놓았다. 옮기기는 같은 일정의 날짜만 바꾸고, Ctrl 로 놓으면 복사본을 만든다.
        반복 일정은 끈 회차 하나만 다루고(원래 자리에서는 빠진다), 5초 동안 되돌릴 수 있다."""
        if delta_days == 0:
            return
        schedule = self.repo.get(schedule_id)
        if schedule is None:
            return
        shift = timedelta(days=delta_days)
        old_start = datetime.combine(occ_date, schedule.start_at.time())
        new_start = old_start + shift
        new_end = new_start + (schedule.end_at - schedule.start_at) if schedule.end_at else None
        single = replace(schedule, id=None, start_at=new_start, end_at=new_end, recurrence=None, recurrence_until=None)
        recurring = schedule.recurrence is not None
        title = schedule.title if len(schedule.title) <= 14 else schedule.title[:13] + "…"
        try:
            if copy:
                new_id = self.repo.add(single)
                undo = lambda: self.repo.delete(new_id)  # noqa: E731
                message = f"'{title}'을(를) {new_start:%m/%d}에 복사했어요"
            elif recurring:
                new_id = self.repo.update_occurrence(schedule_id, occ_date, single)

                def undo():
                    self.repo.delete(new_id)
                    self.repo.restore_occurrence(schedule_id, occ_date)

                message = f"'{title}' {old_start:%m/%d} → {new_start:%m/%d} (이 날짜만 옮김)"
            else:
                self.repo.update(replace(single, id=schedule_id))
                undo = lambda: self.repo.update(schedule)  # noqa: E731
                message = f"'{title}' {old_start:%m/%d} → {new_start:%m/%d} 로 옮겼어요"
        except ValueError as exc:
            self._show_toast(f"옮기지 못했어요: {exc}", None)
            return
        self.refresh()

        def undo_and_refresh() -> None:
            undo()
            self.refresh()

        self._show_toast(message, undo_and_refresh)

    def _duplicate_schedule(self, occ: Occurrence) -> None:
        """수정 팝업의 복제: 같은 내용으로 새 일정 팝업을 열어, 날짜를 고쳐 저장하게 한다."""
        draft = replace(occ.schedule, id=None, start_at=occ.start_at, end_at=occ.end_at,
                        recurrence=None, recurrence_until=None)
        dialog = ScheduleDialog(self, draft=draft, notice="복제한 일정입니다. 날짜와 내용을 확인하고 저장하세요.")
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.action == "save":
            self.repo.add(dialog.schedule())
            self.refresh()

    def _ask_scope(self, verb: str) -> str | None:
        choice = ask_choice(
            self, "반복 일정", f"반복 일정을 {verb}합니다. 적용 범위를 선택하세요.",
            [("cancel", "취소", "normal"), ("this", "이 일정만", "normal"), ("following", "이후 전체", "primary")],
        )
        return choice if choice in ("this", "following") else None

    def _confirm_delete(self, title: str) -> bool:
        return confirm(self, "일정 삭제", f"'{title}' 일정을 삭제할까요?", yes="삭제", danger=True)
