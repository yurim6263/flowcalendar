"""앱을 켤 때 화면 오른쪽 아래에 잠깐 뜨는 브리핑 카드 (FR-AI-002). 몇 초 뒤 저절로 닫히고, 마우스를 올려 두면 닫히지 않는다."""

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from flowcalendar.ai import briefing
from flowcalendar.ui.backdrop import BackdropDialog

AUTO_CLOSE_MS = 25_000
MARGIN = 16


class BriefingCard(BackdropDialog):
    period_requested = Signal(str)  # "day" | "week"

    def __init__(self, parent=None, auto_close_ms: int = AUTO_CLOSE_MS):
        super().__init__(parent)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)  # 하던 입력을 가로채지 않는다
        self.setFixedWidth(380)
        self.setWindowTitle("브리핑")
        self.data: briefing.BriefingData | None = None

        self.heading = QLabel()
        self.heading.setObjectName("dialogTitle")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.counts = QLabel()
        self.counts.setObjectName("hint")
        self.overlap_title = QLabel("시간이 겹치는 일정")
        self.overlap_title.setObjectName("warn")
        self.overlap_text = QLabel()
        self.overlap_text.setWordWrap(True)
        self.notice = QLabel()
        self.notice.setObjectName("error")
        self.notice.setWordWrap(True)

        self.day_btn = QPushButton("오늘")
        self.week_btn = QPushButton("이번 주")
        for btn, period in ((self.day_btn, "day"), (self.week_btn, "week")):
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, p=period: self.period_requested.emit(p))
        close = QPushButton("닫기")
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.day_btn)
        buttons.addWidget(self.week_btn)
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(self.heading)
        layout.addWidget(self.summary)
        layout.addWidget(self.counts)
        layout.addWidget(self.overlap_title)
        layout.addWidget(self.overlap_text)
        layout.addWidget(self.notice)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(auto_close_ms)
        self._timer.timeout.connect(self.close)

    # ---- 내용 ------------------------------------------------------------------------

    def _fill(self, data: briefing.BriefingData) -> None:
        self.data = data
        self.heading.setText(data.title)
        self.counts.setText(f"일정 {len(data.occurrences)}개 · 남은 할 일 {len(data.todos)}개")
        lines = briefing.overlap_lines(data)
        self.overlap_title.setVisible(bool(lines))
        self.overlap_text.setVisible(bool(lines))
        self.overlap_text.setText("\n".join(lines))
        self.day_btn.setChecked(data.period == "day")
        self.week_btn.setChecked(data.period == "week")
        self.notice.hide()
        self._restart_timer()

    def show_loading(self, data: briefing.BriefingData) -> None:
        self._fill(data)
        self.summary.setText("AI가 요약하는 중입니다…")
        self._finish_layout()

    def show_summary(self, data: briefing.BriefingData, summary: str) -> None:
        self._fill(data)
        self.summary.setText(summary)
        self._finish_layout()

    def show_error(self, data: briefing.BriefingData, message: str) -> None:
        """AI 요약이 실패해도 코드로 계산한 요약과 겹침 안내는 보여 주고, 실패 이유는 숨기지 않는다."""
        self._fill(data)
        self.summary.setText(briefing.local_summary(data))
        self.notice.setText(f"AI 요약은 하지 못했습니다. {message}")
        self.notice.show()
        self._finish_layout()

    # ---- 위치/자동 닫힘 --------------------------------------------------------------------

    def _finish_layout(self) -> None:
        self.adjustSize()
        self.place()

    def place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - MARGIN, area.bottom() - self.height() - MARGIN)

    def _restart_timer(self) -> None:
        if self.isVisible() or self._timer.isActive():
            self._timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def enterEvent(self, event):
        self._timer.stop()  # 읽는 중에는 닫지 않는다
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._timer.start()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)
