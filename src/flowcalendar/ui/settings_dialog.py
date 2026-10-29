from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from flowcalendar import __version__
from flowcalendar.ai.providers import DEFAULT_PROVIDER, FREE_TIER_NOTICE, PROVIDERS
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.services.backup import BackupError
from flowcalendar.services.secrets import SecretError, SecretStore
from flowcalendar.ai.adapters import DEFAULT_MODELS
from flowcalendar.services.ai_service import model_setting_key
from flowcalendar.ui import tokens
from flowcalendar.ui.ai_dialogs import error_text
from flowcalendar.ui.backdrop import BackdropDialog
from flowcalendar.ui.message_dialog import confirm
from flowcalendar.ui.widgets import RoseCheckBox, RoseComboBox, RoseSlider


@dataclass
class SettingsBackend:
    """설정 화면이 바깥 세계(레지스트리, 단축키, 파일)와 이야기하는 통로. 테스트에서는 가짜로 바꾼다."""

    settings: SettingsRepository
    secrets: SecretStore
    autostart_enabled: Callable[[], bool]
    set_autostart: Callable[[bool], None]
    apply_hotkey: Callable[[str], tuple[bool, str]]
    export_data: Callable[[Path], None]
    import_data: Callable[[Path], Path]
    list_models: Callable[[str, str], list[str]] | None = None  # (제공사, 키) -> 모델 이름들. 별도 스레드에서 불린다
    runner: object | None = None  # TaskRunner: list_models 를 화면이 멈추지 않게 돌린다


def saved_opacity(settings: SettingsRepository) -> int:
    """저장된 투명도. 값이 이상하면 기본값으로 되돌린다."""
    try:
        value = int(settings.get("widget_opacity"))
    except ValueError:
        return tokens.WIDGET_OPACITY_DEFAULT
    return max(tokens.WIDGET_OPACITY_MIN, min(100, value))


def saved_theme(settings: SettingsRepository) -> str:
    """저장된 테마. 모르는 이름이면 기본(분홍)이다."""
    name = settings.get("theme")
    return name if name in tokens.THEMES else tokens.DEFAULT_THEME


DONE_KEEP_CHOICES = ((7, "7일"), (30, "30일 (기본)"), (90, "90일"), (0, "계속 보관"))


def saved_keep_days(settings: SettingsRepository) -> int:
    """완료한 할 일을 보관하는 일수. 값이 이상하면 기본(30일)이다. 0은 계속 보관."""
    try:
        value = int(settings.get("done_keep_days"))
    except ValueError:
        return 30
    return value if value >= 0 else 30


class ThemeSwatch(QPushButton):
    """테마 한 가지를 보여 주는 동그란 견본: 배경의 두 색을 대각선으로 섞고 가운데에 강조색 점을 찍는다."""

    SIZE = 34

    def __init__(self, key: str, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def paintEvent(self, event) -> None:
        values = tokens.THEMES[self.key][1]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(3, 3, self.SIZE - 6, self.SIZE - 6)
        blobs = values["BLOBS"]
        fill = QLinearGradient(box.topLeft(), box.bottomRight())
        fill.setColorAt(0, QColor(blobs[0][3]))
        fill.setColorAt(1, QColor(blobs[1][3]))
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        painter.drawEllipse(box)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(values["ACCENT"]))
        painter.drawEllipse(box.center(), box.width() * 0.17, box.width() * 0.17)
        if self.isChecked() or self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens.TEXT), 2))
            painter.drawEllipse(QRectF(1, 1, self.SIZE - 2, self.SIZE - 2))


class SettingsDialog(BackdropDialog):
    """설정 (FR-SET-002): 알림, 자동 시작, AI 제공자·키, 단축키, 백업."""

    data_imported = Signal()
    opacity_preview = Signal(int)  # 슬라이더를 움직이는 동안 위젯에 바로 보여 준다 (저장 전)
    theme_preview = Signal(str)  # 테마를 고르는 즉시 앱 전체에 보여 준다 (저장 전, 닫으면 저장된 테마로 돌아간다)

    def __init__(self, backend: SettingsBackend, parent=None, *, warning: str = ""):
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle("설정")
        self.setMinimumWidth(520)

        title = QLabel("설정")
        title.setObjectName("dialogTitle")

        self.notify = RoseCheckBox("일정 시작 전 알림 표시 (알림 시간은 일정마다 설정)")
        self.autostart = RoseCheckBox("Windows 시작 시 자동 실행")
        autostart_note = QLabel("켜면 로그인 후 창 없이 트레이에서 시작합니다. 기본값은 꺼짐입니다.")
        autostart_note.setObjectName("note")

        self.auto_backup = RoseCheckBox("하루 한 번 데이터를 자동으로 백업 (최근 7개만 보관)")
        backup_where = QLabel("백업 파일은 데이터 폴더의 backups 폴더에 저장됩니다. 문제가 생기면 그 파일로 되돌릴 수 있어요.")
        backup_where.setObjectName("note")
        backup_where.setWordWrap(True)
        self.keep_days = RoseComboBox()
        for days, label in DONE_KEEP_CHOICES:
            self.keep_days.addItem(label, days)
        keep_note = QLabel("완료한 할 일은 완료한 날부터 이 기간이 지나면 자동으로 지워집니다. 완료를 취소하면 다시 세지 않습니다.")
        keep_note.setObjectName("note")
        keep_note.setWordWrap(True)
        self.theme_group = QButtonGroup(self)
        self.theme_swatches: dict[str, ThemeSwatch] = {}
        theme_grid = QGridLayout()
        theme_grid.setHorizontalSpacing(8)
        theme_grid.setVerticalSpacing(8)
        for i, (key, label) in enumerate(tokens.theme_names()):
            swatch = ThemeSwatch(key, label)
            swatch.clicked.connect(lambda _=False, k=key: self._on_theme_clicked(k))
            self.theme_group.addButton(swatch)
            self.theme_swatches[key] = swatch
            theme_grid.addWidget(swatch, i // 6, i % 6)
        theme_grid.setColumnStretch(6, 1)
        self.theme_name = QLabel()
        theme_note = QLabel("고르면 바로 바뀌고, 저장하면 다음에 켤 때도 유지됩니다. 닫으면 저장된 테마로 돌아갑니다.")
        theme_note.setObjectName("note")
        theme_note.setWordWrap(True)

        self.opacity = RoseSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(tokens.WIDGET_OPACITY_MIN, 100)
        self.opacity.setSingleStep(5)
        self.opacity.setPageStep(5)
        self.opacity_label = QLabel()
        self.opacity_label.setMinimumWidth(44)
        self.opacity.valueChanged.connect(self._on_opacity_changed)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity, 1)
        opacity_row.addWidget(self.opacity_label)
        opacity_note = QLabel("배경 색의 투명도입니다 (카드는 그대로). 위젯 모드에서만 적용되고, 일반 창은 항상 불투명합니다.")
        opacity_note.setObjectName("note")
        opacity_note.setWordWrap(True)

        self.hotkey = QKeySequenceEdit()
        self.hotkey.setMaximumSequenceLength(1)
        clear_hotkey = QPushButton("지우기")
        clear_hotkey.clicked.connect(self.hotkey.clear)
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.hotkey, 1)
        hotkey_row.addWidget(clear_hotkey)
        hotkey_note = QLabel(
            "AI 빠른 추가 팝업을 여는 전역 단축키입니다. Ctrl/Alt/Shift 중 하나 이상과 키를 함께 누르세요. "
            "다른 프로그램이 쓰는 조합은 등록되지 않을 수 있습니다."
        )
        hotkey_note.setObjectName("note")
        hotkey_note.setWordWrap(True)

        self.provider = RoseComboBox()
        for provider_id, label in PROVIDERS:
            self.provider.addItem(label, provider_id)
        self.provider.currentIndexChanged.connect(self._refresh_key_status)
        self.model = QLineEdit()
        self.model.setPlaceholderText("비워 두면 기본 모델")
        self.model.setToolTip("제공사가 모델 이름을 바꾸면 여기서 직접 바꿀 수 있습니다")
        self.models_btn = QPushButton("사용 가능한 모델 불러오기")
        self.models_btn.setToolTip("내 키로 쓸 수 있는 모델 목록을 제공사에서 받아 옵니다 (키만 보내며, 눌렀을 때만 실행됩니다)")
        self.models_btn.clicked.connect(self._load_models)
        self.models_menu: QMenu | None = None
        self._alive = True
        self.auto_register = RoseCheckBox("AI 빠른 추가는 확인 없이 바로 등록 (등록 후 5초 동안 되돌릴 수 있음)")
        self.briefing = RoseCheckBox("앱을 켤 때 오늘 브리핑 보여 주기")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("API 키 붙여넣기")
        self.key_status = QLabel()
        self.delete_key_btn = QPushButton("키 삭제")
        self.delete_key_btn.clicked.connect(self._delete_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_status, 1)
        key_row.addWidget(self.delete_key_btn)
        key_note = QLabel("키는 Windows 자격 증명 관리자에만 저장되며 파일·내보내기에 포함되지 않습니다.")
        key_note.setObjectName("note")
        key_note.setWordWrap(True)
        free_tier = QLabel(FREE_TIER_NOTICE)
        free_tier.setObjectName("note")
        free_tier.setWordWrap(True)

        export_btn = QPushButton("내보내기…")
        export_btn.clicked.connect(self._on_export)
        import_btn = QPushButton("가져오기…")
        import_btn.clicked.connect(self._on_import)
        backup_row = QHBoxLayout()
        backup_row.addWidget(export_btn)
        backup_row.addWidget(import_btn)
        backup_row.addStretch(1)
        backup_note = QLabel(
            "일정·할 일·메모를 JSON 파일로 저장하거나 불러옵니다. 가져오기는 현재 데이터를 모두 교체하며, "
            "그 전에 현재 데이터를 자동으로 백업합니다. API 키는 포함되지 않습니다."
        )
        backup_note.setObjectName("note")
        backup_note.setWordWrap(True)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName("error")

        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        save = QPushButton("저장")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(save)

        # 내용은 스크롤 영역에 두고, 메시지와 버튼은 항상 보이도록 아래에 고정한다.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(self._section("테마"))
        layout.addLayout(theme_grid)
        layout.addWidget(self.theme_name)
        layout.addWidget(theme_note)
        layout.addWidget(self._section("알림 · 시작"))
        layout.addWidget(self.notify)
        layout.addWidget(self.autostart)
        layout.addWidget(autostart_note)
        layout.addWidget(self._section("데이터 관리"))
        layout.addWidget(self.auto_backup)
        layout.addWidget(backup_where)
        layout.addWidget(QLabel("완료한 할 일 보관 기간"))
        layout.addWidget(self.keep_days)
        layout.addWidget(keep_note)
        layout.addWidget(self._section("위젯 모드 배경 투명도"))
        layout.addLayout(opacity_row)
        layout.addWidget(opacity_note)
        layout.addWidget(self._section("단축키"))
        layout.addLayout(hotkey_row)
        layout.addWidget(hotkey_note)
        layout.addWidget(self._section("AI"))
        layout.addWidget(self.provider)
        layout.addWidget(self.api_key)
        layout.addWidget(self.model)
        layout.addWidget(self.models_btn)
        layout.addWidget(self.auto_register)
        layout.addWidget(self.briefing)
        layout.addLayout(key_row)
        layout.addWidget(key_note)
        layout.addWidget(free_tier)
        layout.addWidget(self._section("데이터 백업"))
        layout.addLayout(backup_row)
        layout.addWidget(backup_note)
        layout.addWidget(self._section("정보"))
        about = QLabel(f"Flow Calendar v{__version__}")
        about.setToolTip("데이터는 이 컴퓨터의 로컬 파일(SQLite)에만 저장됩니다")
        about.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(about)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.addWidget(scroll, 1)
        outer.addWidget(self.message)
        outer.addLayout(buttons)

        # 줄바꿈되는 안내문의 높이까지 반영하되, 작은 화면에서는 화면 안에 들어오게 제한한다.
        width = 520
        wanted = layout.totalHeightForWidth(width) + 90
        screen = self.screen().availableGeometry().height() if self.screen() else 800
        self.resize(width, min(wanted, int(screen * 0.9)))

        self._load()
        if warning:  # 시작할 때 단축키 등록에 실패했다면 여기서 안내한다
            self._say(f"단축키 안내: {warning}")

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    # ---- 불러오기 ---------------------------------------------------------

    def _load(self) -> None:
        s = self.backend.settings
        self.notify.setChecked(s.get_bool("notifications_enabled"))
        self.autostart.setChecked(self.backend.autostart_enabled())
        self.hotkey.setKeySequence(QKeySequence(s.get("hotkey")))
        self._select_theme(saved_theme(s))
        self.auto_backup.setChecked(s.get_bool("auto_backup"))
        keep_index = self.keep_days.findData(saved_keep_days(s))
        if keep_index < 0:  # 목록에 없는 값(직접 바꾼 값)도 그대로 보여 준다
            self.keep_days.addItem(f"{saved_keep_days(s)}일", saved_keep_days(s))
            keep_index = self.keep_days.count() - 1
        self.keep_days.setCurrentIndex(keep_index)
        self.opacity.blockSignals(True)
        self.opacity.setValue(saved_opacity(s))
        self.opacity.blockSignals(False)
        self.opacity_label.setText(f"{self.opacity.value()}%")
        index = self.provider.findData(s.get("ai_provider"))
        self.provider.setCurrentIndex(index if index >= 0 else self.provider.findData(DEFAULT_PROVIDER))
        self._refresh_key_status()
        self.briefing.setChecked(s.get_bool("ai_briefing"))
        self.auto_register.setChecked(s.get_bool("ai_auto_register"))

    def selected_theme(self) -> str:
        return next((k for k, b in self.theme_swatches.items() if b.isChecked()), tokens.DEFAULT_THEME)

    def _select_theme(self, key: str) -> None:
        self.theme_swatches[key].setChecked(True)
        self.theme_name.setText(f"선택: {tokens.THEMES[key][0]}")

    def _on_theme_clicked(self, key: str) -> None:
        self._select_theme(key)
        self.theme_preview.emit(key)
        for swatch in self.theme_swatches.values():
            swatch.update()

    def _on_opacity_changed(self, value: int) -> None:
        value = round(value / 5) * 5  # 5% 단위로만 움직이게 맞춘다
        if value != self.opacity.value():
            self.opacity.setValue(value)
            return
        self.opacity_label.setText(f"{value}%")
        self.opacity_preview.emit(value)

    # ---- 모델 목록 -----------------------------------------------------------------

    def _load_models(self) -> None:
        provider = self.current_provider()
        # 아직 저장하지 않은 새 키도 바로 확인해 볼 수 있게, 입력칸에 쓴 키를 먼저 쓴다 (읽기는 화면 스레드에서)
        key = self.api_key.text().strip()
        if not key:
            try:
                key = self.backend.secrets.get(provider) or ""
            except SecretError as exc:
                self._say(str(exc))
                return
        if not key:
            self._say("API 키를 먼저 입력하세요.")
            return
        if self.backend.list_models is None or self.backend.runner is None:
            self._say("이 환경에서는 모델 목록을 불러올 수 없습니다.")
            return
        self.models_btn.setEnabled(False)
        self._say("모델 목록을 불러오는 중입니다…", ok=True)
        self.backend.runner.run(
            lambda: self.backend.list_models(provider, key), self._on_models, self._on_models_error
        )

    def _on_models(self, names: list[str]) -> None:
        if not self._alive:
            return
        self.models_btn.setEnabled(True)
        if not names:
            self._say("이 키로 쓸 수 있는 모델을 찾지 못했습니다. 키와 제공사를 확인하세요.")
            return
        self._say(f"쓸 수 있는 모델 {len(names)}개를 찾았습니다. 목록에서 고르세요.", ok=True)
        self.models_menu = QMenu(self)
        for name in names[:40]:
            self.models_menu.addAction(name).triggered.connect(lambda _=False, n=name: self.model.setText(n))
        self.models_menu.popup(self.models_btn.mapToGlobal(self.models_btn.rect().bottomLeft()))

    def _on_models_error(self, exc: BaseException) -> None:
        if not self._alive:
            return
        self.models_btn.setEnabled(True)
        self._say(error_text(exc))

    def done(self, result: int) -> None:
        self._alive = False
        super().done(result)

    def current_provider(self) -> str:
        return self.provider.currentData()

    def _refresh_key_status(self) -> None:
        self.api_key.clear()
        provider = self.current_provider()
        self.model.setPlaceholderText(f"기본 모델: {DEFAULT_MODELS.get(provider, '')}")
        self.model.setText(self.backend.settings.get(model_setting_key(provider)))
        try:
            has_key = self.backend.secrets.has(self.current_provider())
        except SecretError as exc:
            self.key_status.setText(str(exc))
            self.key_status.setObjectName("error")
            self.delete_key_btn.setEnabled(False)
            return
        self.key_status.setText("API 키가 저장되어 있습니다" if has_key else "저장된 API 키가 없습니다 (AI 기능이 숨겨집니다)")
        self.key_status.setObjectName("ok" if has_key else "note")
        self.key_status.style().unpolish(self.key_status)
        self.key_status.style().polish(self.key_status)
        self.delete_key_btn.setEnabled(has_key)

    def _delete_key(self) -> None:
        try:
            self.backend.secrets.delete(self.current_provider())
        except SecretError as exc:
            self._say(str(exc))
        self._refresh_key_status()

    # ---- 저장 -------------------------------------------------------------

    def hotkey_text(self) -> str:
        return self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)

    def _on_save(self) -> None:
        s = self.backend.settings
        self._say("")

        new_hotkey = self.hotkey_text()
        if new_hotkey != s.get("hotkey"):
            ok, hint = self.backend.apply_hotkey(new_hotkey)
            if not ok:  # 실패하면 설정은 그대로 두고 안내만 한다 (쓰던 단축키는 유지됨)
                self._say(hint)
                return
            s.set("hotkey", new_hotkey)

        try:
            self.backend.set_autostart(self.autostart.isChecked())
        except OSError as exc:
            self._say(f"자동 실행 설정을 바꾸지 못했습니다: {exc}")
            return

        typed_key = self.api_key.text().strip()
        if typed_key:
            try:
                self.backend.secrets.set(self.current_provider(), typed_key)
            except SecretError as exc:
                self._say(str(exc))
                return

        s.set("theme", self.selected_theme())
        s.set_bool("auto_backup", self.auto_backup.isChecked())
        s.set("done_keep_days", str(self.keep_days.currentData()))
        s.set("widget_opacity", str(self.opacity.value()))
        s.set_bool("notifications_enabled", self.notify.isChecked())
        s.set("ai_provider", self.current_provider())
        s.set(model_setting_key(self.current_provider()), self.model.text().strip())
        s.set_bool("ai_briefing", self.briefing.isChecked())
        s.set_bool("ai_auto_register", self.auto_register.isChecked())
        self.accept()

    # ---- 백업 -------------------------------------------------------------
    # 파일 선택과 확인창은 메서드로 분리해 테스트에서 바꿔 끼울 수 있게 한다.

    def _ask_save_path(self) -> str:
        default = f"FlowCalendar-{datetime.now():%Y%m%d}.json"
        path, _ = QFileDialog.getSaveFileName(self, "내보내기", default, "JSON (*.json)")
        return path

    def _ask_open_path(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "가져오기", "", "JSON (*.json)")
        return path

    def _confirm_import(self) -> bool:
        return confirm(
            self, "가져오기",
            "현재 일정·할 일·메모가 파일 내용으로 모두 교체됩니다.\n"
            "교체 전에 현재 데이터를 자동으로 백업합니다. 계속할까요?",
            yes="가져오기", danger=True,
        )

    def _on_export(self) -> None:
        path = self._ask_save_path()
        if not path:
            return
        try:
            self.backend.export_data(Path(path))
        except OSError as exc:
            self._say(f"내보내지 못했습니다: {exc}")
            return
        self._info(f"내보냈습니다: {path}")

    def _on_import(self) -> None:
        path = self._ask_open_path()
        if not path or not self._confirm_import():
            return
        try:
            saved = self.backend.import_data(Path(path))
        except BackupError as exc:
            self._say(str(exc))
            return
        self.data_imported.emit()
        self._info(f"가져왔습니다. 이전 데이터는 {saved} 에 백업했습니다.")

    def _info(self, text: str) -> None:
        self._say(text, ok=True)

    def _say(self, text: str, ok: bool = False) -> None:
        """하단 메시지. 성공은 초록, 오류는 빨강으로 보여 준다."""
        self.message.setObjectName("ok" if ok else "error")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text)
