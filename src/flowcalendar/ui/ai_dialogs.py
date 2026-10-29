"""AI 팝업 두 가지.
- QuickAddDialog: 한 문장(또는 메모에서 고른 글)을 AI 에 보내 일정/할 일 '후보'를 받아 온다. 저장은 하지 않는다.
- DraftListDialog: 후보를 보여 주고, 사용자가 체크한 것만 등록 대상으로 돌려준다 (FR-AI-001, FR-AI-005).
"""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from flowcalendar.ai.errors import AIError
from flowcalendar.ai.quick_add import Draft, describe
from flowcalendar.data.ai_inbox_repo import AIInboxRepository, InboxItem
from flowcalendar.domain.models import Schedule, Todo
from flowcalendar.services.ai_service import AIService
from flowcalendar.ui.backdrop import BackdropDialog
from flowcalendar.ui.widgets import RoseCheckBox

QUICK_NOTE = "AI 제공사로 보내는 것은 입력한 문장과 오늘 날짜·시각뿐입니다. 결과는 확인한 뒤에만 저장됩니다."
QUICK_NOTE_AUTO = ("AI 제공사로 보내는 것은 입력한 문장과 오늘 날짜·시각뿐입니다. 결과는 바로 등록되고, "
                   "등록 직후 5초 동안 되돌릴 수 있습니다.")
MEMO_NOTE = "AI 제공사로 보내는 것은 선택한 메모 내용뿐이며, 메모의 나머지는 보내지 않습니다. 결과는 확인한 뒤에만 저장됩니다."


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def error_text(exc: BaseException) -> str:
    """사용자에게 보여 줄 오류 안내. AI 오류는 원인별 문구, 그 밖의 예외도 숨기지 않고 종류를 알려 준다."""
    if isinstance(exc, AIError):
        return exc.user_message
    return f"예상하지 못한 오류가 났습니다 ({type(exc).__name__})."


INBOX_ROWS_VISIBLE = 3  # 목록이 길어져도 팝업이 커지지 않게 3줄만 보이고 나머지는 스크롤한다
INBOX_ROW_HEIGHT = 54
INBOX_ROW_GAP = 6

REASON_LABELS = {
    "no_key": "API 키 없음", "auth": "API 키 오류", "quota": "한도 초과", "model": "모델 오류",
    "network": "연결 실패", "timeout": "시간 초과", "server": "서버가 바쁨", "bad_request": "요청 거부됨",
    "bad_response": "응답을 이해하지 못함",
}
NOTHING_FOUND = "일정이나 할 일을 찾지 못함"


def short_reason(exc: BaseException) -> str:
    """미처리 목록에 남길 짧은 이유."""
    if isinstance(exc, AIError):
        return REASON_LABELS.get(exc.kind, "AI 오류")
    return "예상하지 못한 오류"


def _elide(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class QuickAddDialog(BackdropDialog):
    """AI 빠른 추가. outcome: "drafts"(후보를 받음) | "manual"(직접 입력으로) | "settings"(설정 열기) | None(취소).

    inbox 가 있으면(메모 모드 제외) 처리하지 못한 입력을 남겨 두고, 아래 목록에서 다시 시도/직접 입력/삭제할 수 있다.
    """

    def __init__(self, parent, service: AIService, runner, *, memo_text: str | None = None,
                 inbox: AIInboxRepository | None = None, auto_register: bool = False):
        super().__init__(parent)
        self.service, self.runner = service, runner
        self.memo_text = memo_text
        self.inbox = None if memo_text is not None else inbox
        self.drafts: list[Draft] = []
        self.source_text = ""  # 후보를 만든 입력 글 (등록에 실패하면 미처리 목록에 남기는 데 쓴다)
        self.outcome: str | None = None
        self.manual_text = ""
        self._alive = True
        self._busy = False
        self._started = False
        self._pending_text = ""
        memo_mode = memo_text is not None
        self.setWindowTitle("메모에서 찾기" if memo_mode else "AI 빠른 추가")
        self.setMinimumWidth(480)

        heading = QLabel("메모에서 일정·할 일 찾기" if memo_mode else "AI 빠른 추가")
        heading.setObjectName("dialogTitle")
        self.input: QLineEdit | None = None
        if memo_mode:
            flat = " ".join(memo_text.split())
            shown = flat if len(flat) <= 90 else flat[:89] + "…"
            self.preview = QLabel(f"선택한 메모 ({len(memo_text.strip())}글자): {shown}")
            self.preview.setWordWrap(True)
            first = self.preview
        else:
            self.input = QLineEdit()
            self.input.setPlaceholderText("예: 내일 오후 3시 팀 미팅 1시간")
            self.input.returnPressed.connect(self._convert)
            first = self.input
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)  # 서버 메시지를 복사할 수 있게
        self.status.hide()  # 할 말이 있을 때만 보여서 입력창 아래가 휑하지 않게
        if memo_mode:
            note_text = MEMO_NOTE
        else:
            note_text = QUICK_NOTE_AUTO if auto_register else QUICK_NOTE
        note = QLabel(note_text)
        note.setObjectName("note")
        note.setWordWrap(True)

        # 처리하지 못한 입력 목록 (3줄만 보이고 스크롤)
        self.inbox_title = QLabel()
        self.inbox_title.setObjectName("sectionTitle")
        self._inbox_body = QWidget()
        self._inbox_layout = QVBoxLayout(self._inbox_body)
        self._inbox_layout.setContentsMargins(0, 0, 6, 0)
        self._inbox_layout.setSpacing(INBOX_ROW_GAP)
        self._inbox_layout.addStretch(1)
        self.inbox_area = QScrollArea()
        self.inbox_area.setWidgetResizable(True)
        self.inbox_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inbox_area.setWidget(self._inbox_body)
        self.inbox_rows: list[QWidget] = []

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.reject)
        self.manual_btn = QPushButton("직접 입력")
        self.manual_btn.setToolTip("AI 없이 직접 일정/할 일을 입력합니다")
        self.manual_btn.clicked.connect(self._manual)
        self.settings_btn = QPushButton("설정 열기")  # 모델 이름/API 키 오류일 때만 보인다
        self.settings_btn.setToolTip("모델 이름이나 API 키를 설정에서 확인합니다")
        self.settings_btn.clicked.connect(self._open_settings)
        self.settings_btn.hide()
        self.convert_btn = QPushButton("찾기" if memo_mode else "변환")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setDefault(True)
        self.convert_btn.clicked.connect(self._convert)
        buttons = QHBoxLayout()
        buttons.addWidget(self.manual_btn)
        buttons.addWidget(self.settings_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.convert_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(first)
        layout.addWidget(self.status)
        layout.addWidget(self.inbox_title)
        layout.addWidget(self.inbox_area)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self._reload_inbox()

    # ---- 미처리 목록 ---------------------------------------------------------------------

    def _reload_inbox(self) -> None:
        for row in self.inbox_rows:  # 숨기기만 하면 레이아웃에 계속 남아 쌓인다. 완전히 떼어 낸다
            self._inbox_layout.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.inbox_rows = []
        items = self.inbox.list() if self.inbox is not None else []
        visible = bool(items)
        self.inbox_title.setVisible(visible)
        self.inbox_area.setVisible(visible)
        if not visible:
            return
        self.inbox_title.setText(f"처리하지 못한 입력 ({len(items)})")
        for item in items:
            row = self._make_inbox_row(item)
            self._inbox_layout.insertWidget(self._inbox_layout.count() - 1, row)
            self.inbox_rows.append(row)
        # 본문 높이를 줄 수에 맞춰 고정한다. (표시 중에 다시 만들면 스크롤 영역이 본문을 키워 주지 않아 줄이 포개진다)
        total = len(items) * INBOX_ROW_HEIGHT + (len(items) - 1) * INBOX_ROW_GAP
        self._inbox_body.setMinimumHeight(total)
        self._inbox_body.resize(self.inbox_area.viewport().width(), max(total, self.inbox_area.viewport().height()))
        shown = min(len(items), INBOX_ROWS_VISIBLE)
        self.inbox_area.setFixedHeight(shown * INBOX_ROW_HEIGHT + (shown - 1) * INBOX_ROW_GAP + 4)

    def _make_inbox_row(self, item: InboxItem) -> QWidget:
        row = QFrame()
        row.setObjectName("inboxRow")
        row.setFixedHeight(INBOX_ROW_HEIGHT)
        text = QLabel(_elide(item.text, 34))
        text.setToolTip(item.text)
        reason = QLabel(item.reason or "처리하지 못함")
        reason.setObjectName("note")
        retry = QPushButton("다시 시도")
        retry.clicked.connect(lambda _=False, i=item: self._retry_item(i))
        manual = QPushButton("직접 입력")
        manual.clicked.connect(lambda _=False, i=item: self._manual_item(i))
        delete = QPushButton("삭제")
        delete.setObjectName("danger")
        delete.clicked.connect(lambda _=False, i=item: self._delete_item(i))
        for button in (retry, manual, delete):
            button.setProperty("compact", True)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(text)
        texts.addWidget(reason)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 4, 8, 4)
        layout.addLayout(texts, 1)
        layout.addWidget(retry)
        layout.addWidget(manual)
        layout.addWidget(delete)
        row.retry_btn, row.manual_btn, row.delete_btn = retry, manual, delete  # 테스트와 이후 제어를 위해 달아 둔다
        row.item = item
        return row

    def _remember(self, text: str, reason: str) -> None:
        """처리하지 못한 입력을 목록에 남긴다 (사용자가 쓴 글을 잃지 않게)."""
        if self.inbox is not None and text.strip():
            self.inbox.add(text, reason)
            self._reload_inbox()
            self._fit()

    def _retry_item(self, item: InboxItem) -> None:
        if self._busy or self.input is None:
            return
        self.input.setText(item.text)
        self._convert()

    def _manual_item(self, item: InboxItem) -> None:
        if self.inbox is not None:
            self.inbox.delete(item.id)  # 직접 입력으로 넘어가면 사용자가 직접 처리하는 것이므로 목록에서 뺀다
        self.manual_text = item.text
        self.outcome = "manual"
        self.accept()

    def _delete_item(self, item: InboxItem) -> None:
        if self.inbox is not None:
            self.inbox.delete(item.id)
            self._reload_inbox()

    # ---- 흐름 ---------------------------------------------------------------------

    def text(self) -> str:
        return self.memo_text if self.input is None else self.input.text()

    def showEvent(self, event):
        super().showEvent(event)
        if self.input is not None:
            self.input.setFocus()
        elif not self._started:  # 메모에서 고른 글은 바로 AI 에 묻는다
            self._started = True
            QTimer.singleShot(0, self._convert)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setObjectName("error" if error else "hint")
        _repolish(self.status)
        self.status.setVisible(bool(text))
        self._fit()

    def _fit(self) -> None:
        """안내 글이 길어져 줄이 늘어나면 팝업도 그만큼 키운다 (안 그러면 아래 글과 겹치고 잘린다)."""
        layout = self.layout()
        layout.activate()
        margins = self.contentsMargins()
        needed = layout.totalHeightForWidth(self.width()) + margins.top() + margins.bottom()
        if needed > self.height():
            self.resize(self.width(), needed)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if self.input is not None:
            self.input.setEnabled(not busy)
        self.convert_btn.setEnabled(not busy)
        self.manual_btn.setEnabled(not busy)
        self.settings_btn.setEnabled(not busy)
        for row in self.inbox_rows:
            row.retry_btn.setEnabled(not busy)

    def _convert(self) -> None:
        if self._busy:
            return
        text = self.text().strip()
        if not text:
            self._set_status("문장을 입력하세요.", error=True)
            return
        self._pending_text = text
        try:
            call = self.service.prepare()  # 설정/키 읽기는 화면 스레드에서 (SQLite 는 다른 스레드에서 쓸 수 없다)
        except AIError as exc:
            self._on_error(exc)
            return
        self._set_busy(True)
        self._set_status("AI가 읽는 중입니다… 잠시만 기다려 주세요.")
        self.runner.run(lambda: self.service.parse_text_with(call, text), self._on_result, self._on_error)

    def _on_result(self, drafts: list[Draft]) -> None:
        if not self._alive:  # 기다리는 동안 창을 닫았다
            return
        self._set_busy(False)
        if not drafts:
            self._set_status("일정이나 할 일로 보이는 내용을 찾지 못했어요. 문장을 바꿔 보거나 '직접 입력'을 쓰세요.")
            self._remember(self._pending_text, NOTHING_FOUND)
            return
        if self.inbox is not None:
            self.inbox.delete_text(self._pending_text)  # 다시 시도해서 성공했으면 목록에서 지운다
        self.drafts, self.source_text, self.outcome = drafts, self._pending_text, "drafts"
        self.accept()

    def _on_error(self, exc: BaseException) -> None:
        if not self._alive:
            return
        self._set_busy(False)
        self._set_status(error_text(exc), error=True)
        self._remember(self._pending_text, short_reason(exc))
        # 오류는 숨기지 않고 안내하되, 막히지 않도록 수동 입력으로 바로 넘어갈 수 있게 한다 (FR-AI-004)
        # 모델 이름/키 문제는 다시 시도해도 같으니, 고치러 가는 '설정 열기'를 가장 눈에 띄게 둔다.
        kind = exc.kind if isinstance(exc, AIError) else ""
        fix_in_settings = kind in ("model", "auth", "no_key")
        temporary = kind in ("server", "timeout", "network", "quota")  # 잠시 뒤 다시 하면 될 수 있는 오류
        self.convert_btn.setText("다시 시도")
        self.manual_btn.setText("직접 입력으로 전환")
        # 서버가 바쁠 땐 다른 모델로 바꿔 보는 길도 열어 둔다
        self.settings_btn.setVisible(fix_in_settings or kind in ("server", "timeout"))
        primary = {self.settings_btn: fix_in_settings, self.convert_btn: temporary,
                   self.manual_btn: not fix_in_settings and not temporary}
        for button, is_primary in primary.items():
            button.setObjectName("primary" if is_primary else "")
            _repolish(button)
        default = next(button for button, is_primary in primary.items() if is_primary)
        for button in primary:  # Enter 로 눌리는 버튼도 강조된 버튼과 같게
            button.setDefault(button is default)
        self._fit()

    def _open_settings(self) -> None:
        self.outcome = "settings"
        self.accept()

    def _manual(self) -> None:
        self.manual_text = self.text().strip()
        self.outcome = "manual"
        self.accept()

    def done(self, result: int) -> None:
        self._alive = False
        super().done(result)


class DraftListDialog(BackdropDialog):
    """후보 목록. 체크한 것만 등록하고, '수정'으로 내용을 고칠 수 있다. 이미 있는 항목은 기본으로 체크하지 않는다."""

    def __init__(self, parent, items: list[Schedule | Todo], duplicates: list[bool], *, notice: str,
                 edit_item: Callable[[Schedule | Todo], Schedule | Todo | None]):
        super().__init__(parent)
        self.setWindowTitle("AI가 찾은 항목")
        self.setMinimumWidth(520)
        self._items = list(items)
        self._edit_item = edit_item

        heading = QLabel("AI가 찾은 항목")
        heading.setObjectName("dialogTitle")
        note = QLabel(notice)
        note.setObjectName("note")
        note.setWordWrap(True)

        self.checks: list[RoseCheckBox] = []
        self.labels: list[QLabel] = []
        rows = QVBoxLayout()
        rows.setSpacing(8)
        for index, (item, duplicate) in enumerate(zip(items, duplicates)):
            row = QHBoxLayout()
            check = RoseCheckBox()
            check.setChecked(not duplicate)
            check.toggled.connect(self._update_register)
            label = QLabel(describe(item))
            label.setWordWrap(True)
            row.addWidget(check)
            row.addWidget(label, 1)
            if duplicate:
                tag = QLabel("이미 있음")
                tag.setObjectName("note")
                tag.setToolTip("같은 제목이 같은 날에 이미 있어서 기본으로 선택하지 않았습니다")
                row.addWidget(tag)
            edit = QPushButton("수정")
            edit.clicked.connect(lambda _=False, i=index: self._edit(i))
            row.addWidget(edit)
            rows.addLayout(row)
            self.checks.append(check)
            self.labels.append(label)

        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        self.register_btn = QPushButton()
        self.register_btn.setObjectName("primary")
        self.register_btn.setDefault(True)
        self.register_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.register_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(note)
        layout.addLayout(rows)
        layout.addLayout(buttons)
        self._update_register()

    def _update_register(self) -> None:
        count = sum(c.isChecked() for c in self.checks)
        self.register_btn.setText(f"{count}개 등록")
        self.register_btn.setEnabled(count > 0)

    def _edit(self, index: int) -> None:
        edited = self._edit_item(self._items[index])
        if edited is not None:
            self._items[index] = edited
            self.labels[index].setText(describe(edited))

    def chosen(self) -> list[Schedule | Todo]:
        return [item for item, check in zip(self._items, self.checks) if check.isChecked()]
