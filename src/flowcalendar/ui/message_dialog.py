"""QMessageBox 를 대신하는 확인/선택 팝업. 다른 팝업과 같은 Rose Glass 카드로 보인다."""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from flowcalendar.ui.backdrop import BackdropDialog

# (키, 버튼 글자, 종류) 종류: primary(강조) / danger(되돌리기 어려운 동작) / normal
Button = tuple[str, str, str]


class ChoiceDialog(BackdropDialog):
    def __init__(self, parent: QWidget | None, title: str, text: str, buttons: list[Button]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(340)
        self.choice: str | None = None  # × / Esc 로 닫으면 None

        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        body = QLabel(text)
        body.setWordWrap(True)

        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, kind in buttons:
            button = QPushButton(label)
            if kind != "normal":
                button.setObjectName(kind)
            button.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(button)
            self.buttons[key] = button
        default = next((k for k, _, kind in buttons if kind == "primary"), None)
        if default is not None:
            self.buttons[default].setDefault(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addSpacing(4)
        layout.addLayout(row)

    def _pick(self, key: str) -> None:
        self.choice = key
        self.accept()


def ask_choice(parent: QWidget | None, title: str, text: str, buttons: list[Button]) -> str | None:
    dialog = ChoiceDialog(parent, title, text, buttons)
    dialog.exec()
    return dialog.choice


def confirm(parent: QWidget | None, title: str, text: str, yes: str = "확인", no: str = "취소",
            danger: bool = False) -> bool:
    return ask_choice(parent, title, text, [
        ("no", no, "normal"),
        ("yes", yes, "danger" if danger else "primary"),
    ]) == "yes"
