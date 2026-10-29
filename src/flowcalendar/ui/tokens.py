"""테마 토큰. 색은 이 모듈의 전역 값으로 두고, apply(이름)으로 테마를 바꾼다 (NFR-006).

다른 모듈은 `tokens.ACCENT`처럼 쓸 때마다 읽으므로, apply() 뒤에 만들어지는 위젯과 STYLESHEET 는 새 색을 쓴다.
이미 떠 있는 창에 반영하는 일(스타일시트 다시 적용, 달력 다시 그리기)은 호출하는 쪽의 몫이다.
"""

import colorsys

# 위젯 모드 배경 투명도(%). 일반 창은 항상 불투명이다.
WIDGET_OPACITY_MIN = 50
WIDGET_OPACITY_DEFAULT = 65
WINDOW_RADIUS = 20  # 위젯 모드(테두리 없는 창)와 팝업의 바깥 모서리
FONT_FAMILY = "Malgun Gothic"

DEFAULT_THEME = "pink"


def _hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, min(max(l, 0), 1), min(max(s, 0), 1))
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


# 일정 색(칩)과 색상 선택 점. 밝은 테마는 파스텔, 어두운 테마는 같은 색을 눌러 둔다.
_CHIP_LIGHT = {
    "yellow": "#FFE7A8", "pink": "#F6BCD6", "green": "#C9EBDC", "blue": "#CFE2FB", "purple": "#DDD3F8",
}
_CHIP_DARK = {
    "yellow": "#6B5A2A", "pink": "#7A3F58", "green": "#2F5F4C", "blue": "#2F4D7A", "purple": "#4F4482",
}
_SWATCH = {
    "yellow": "#FFD35A", "pink": "#EE7FAE", "green": "#7CCDB0", "blue": "#5B9BF0", "purple": "#A98BF0",
}

# 밝은 테마의 공통 값. 테마별 값이 이 위에 덮어씌워진다.
_LIGHT_BASE = {
    "DARK": False,
    "SUNDAY": "#D13F55", "SATURDAY": "#3563C9", "DONE": "#5FC79B",
    "MEMO_BG": "#FFF5DA",
    "ON_ACCENT": "white",
    "FILL_SCALE": 1.0,          # 흰 반투명 면의 진하기 배율 (어두운 테마는 낮춘다)
    "SOLID": "white",           # 메뉴·팝업 목록 같은 불투명 면
    "EDGE": (255, 255, 255, 235),
    "CHECK_FILL": (255, 255, 255, 235),
    "CHIP": _CHIP_LIGHT, "SWATCH": _SWATCH,
}


def _tone(h: float, h2: float | None = None, *, accent_h: float | None = None, accent_s: float = 0.46,
          accent_l: float = 0.52, text_s: float = 0.20, bg_s: float = 0.70, blob_s: float = 1.0,
          **over) -> dict:
    """색조(h)에서 밝은 테마를 만든다. h2 는 배경 아래쪽(그라데이션)의 색조다."""
    h2 = h if h2 is None else h2
    ah = h if accent_h is None else accent_h
    text = _hex(ah, text_s, 0.24)
    r, g, b = _rgb(text)
    theme = {
        "TEXT": text, "TEXT_SOFT": _hex(ah, text_s * 0.6, 0.43), "TEXT_MUTED": _hex(ah, text_s * 0.9, 0.74),
        "ACCENT": _hex(ah, accent_s, accent_l), "ACCENT_HOVER": _hex(ah, accent_s, accent_l - 0.06),
        "CHECK_BORDER": _hex(ah, text_s * 1.7, 0.72),
        "BG_TOP": _hex(h, bg_s, 0.965), "BG_BOTTOM": _hex(h2, bg_s * 0.85, 0.915),
        "BLOBS": (
            (0.08, 0.05, 0.50, _hex(h, 0.80 * blob_s, 0.78)),
            (0.92, 0.95, 0.55, _hex(h2 + 30, 0.90 * blob_s, 0.87)),
            (0.78, 0.18, 0.35, _hex(h2 - 18, 0.70 * blob_s, 0.84)),
        ),
        "SELECTION": _hex(ah, 0.70 * blob_s, 0.85), "ACCENT_DISABLED": _hex(ah, accent_s * 0.8, 0.80),
        "UNDO_TEXT": _hex(ah, 0.90 * blob_s, 0.88), "SOLID_HOVER": _hex(ah, 1.0, 0.975),
        "TOAST_BG": f"rgba({r}, {g}, {b}, 0.94)",
    }
    theme.update(over)
    return theme


# 기본(분홍)은 처음부터 쓰던 값 그대로다.
_PINK = {
    "TEXT": "#4A3238", "TEXT_SOFT": "#7C646A", "TEXT_MUTED": "#C9B0B6",
    "ACCENT": "#C2506A", "ACCENT_HOVER": "#AD4259", "CHECK_BORDER": "#D6A3B0",
    "BG_TOP": "#FDF2F4", "BG_BOTTOM": "#F7E1E7",
    "BLOBS": (
        (0.08, 0.05, 0.50, "#F4A7B9"),
        (0.92, 0.95, 0.55, "#FFD8C6"),
        (0.78, 0.18, 0.35, "#F6C3DA"),
    ),
    "SELECTION": "#F6BCD6", "ACCENT_DISABLED": "#E3BDC7", "UNDO_TEXT": "#FFC9D5",
    "SOLID_HOVER": "#FFF0F3", "TOAST_BG": "rgba(74, 50, 56, 0.94)",
}

_BLACK = {
    "DARK": True,
    "TEXT": "#ECE8F2", "TEXT_SOFT": "#B3ACC0", "TEXT_MUTED": "#6F6880",
    "SUNDAY": "#FF8A9B", "SATURDAY": "#8FB0FF", "DONE": "#5FC79B",
    "ACCENT": "#9B80EA", "ACCENT_HOVER": "#8A6BDD", "ON_ACCENT": "white", "CHECK_BORDER": "#6F6880",
    "MEMO_BG": "#3A3629",
    "BG_TOP": "#1B1823", "BG_BOTTOM": "#0E0C13",
    "BLOBS": (
        (0.08, 0.05, 0.50, "#3C2B66"),
        (0.92, 0.95, 0.55, "#1F3B5C"),
        (0.78, 0.18, 0.35, "#4A2B58"),
    ),
    "FILL_SCALE": 0.16, "SOLID": "#2A2535", "SOLID_HOVER": "#38324A",
    "SELECTION": "rgba(155, 128, 234, 0.45)", "ACCENT_DISABLED": "#463E5E", "UNDO_TEXT": "#C9B8FF",
    "TOAST_BG": "rgba(8, 6, 12, 0.95)",
    "GRID_LINE": "rgba(255, 255, 255, 0.07)", "FIELD_BORDER": "rgba(255, 255, 255, 0.20)",
    "EDGE": (255, 255, 255, 40), "CHECK_FILL": (255, 255, 255, 22),
    "CHIP": _CHIP_DARK, "SWATCH": _SWATCH,
}

# (이름, 설정에 보이는 이름, 값) 순서 그대로 설정의 목록이 된다.
THEMES: dict[str, tuple[str, dict]] = {
    "pink": ("분홍", _PINK),
    "purple": ("보라", _tone(265)),
    "yellow": ("노랑", _tone(44, accent_s=0.62, accent_l=0.42, bg_s=0.85)),
    "sky": ("하늘", _tone(205, accent_s=0.52, accent_l=0.48)),
    "lime": ("연두", _tone(95, accent_s=0.45, accent_l=0.38, bg_s=0.65)),
    "gray": ("회색", _tone(
        220, accent_s=0.10, accent_l=0.34, text_s=0.05, bg_s=0.06, blob_s=0.10,
        BG_TOP="#D8D9DD", BG_BOTTOM="#BDBFC5", TEXT_SOFT="#505359", TEXT_MUTED="#8B8E95", CHECK_BORDER="#8B8E95",
        BLOBS=((0.08, 0.05, 0.50, "#B3B6BD"), (0.92, 0.95, 0.55, "#C7C9CE"), (0.78, 0.18, 0.35, "#AEB2BA")),
    )),
    "white": ("흰색", _tone(
        220, accent_s=0.12, accent_l=0.38, text_s=0.06, bg_s=0.10, blob_s=0.12,
        BG_TOP="#FFFFFF", BG_BOTTOM="#F1F2F6",
        BLOBS=((0.08, 0.05, 0.50, "#EEF0F6"), (0.92, 0.95, 0.55, "#F4F1F6"), (0.78, 0.18, 0.35, "#EAEFF6")),
    )),
    "black": ("검정", _BLACK),
    "gradient_sunset": ("그라데이션 · 노을", _tone(
        22, 335, accent_h=350, accent_s=0.52, accent_l=0.52, bg_s=0.95, blob_s=1.15)),
    "gradient_lavender": ("그라데이션 · 라벤더", _tone(
        330, 255, accent_h=285, accent_s=0.45, accent_l=0.55, bg_s=0.85, blob_s=1.1)),
    "gradient_mint": ("그라데이션 · 민트", _tone(
        200, 100, accent_h=165, accent_s=0.40, accent_l=0.40, bg_s=0.80, blob_s=1.05)),
}


def theme_names() -> list[tuple[str, str]]:
    return [(key, label) for key, (label, _) in THEMES.items()]


CURRENT = DEFAULT_THEME


def fill(alpha: float) -> str:
    """카드·버튼·입력칸 같은 반투명 면의 색. 밝은 테마는 흰색, 어두운 테마는 옅은 흰색이다."""
    return f"rgba(255,255,255,{round(alpha * FILL_SCALE, 3):g})"


def tint(alpha: float) -> str:
    """강조색을 옅게 깐 색 (Hover, 스크롤 막대 등)."""
    r, g, b = _rgb(ACCENT)
    return f"rgba({r},{g},{b},{alpha:g})"


def apply(name: str) -> None:
    """테마를 바꾼다. 모르는 이름이면 기본(분홍)을 쓴다."""
    global CURRENT, STYLESHEET
    if name not in THEMES:
        name = DEFAULT_THEME
    values = dict(_LIGHT_BASE)
    values.update(THEMES[name][1])
    globals().update(values)
    CURRENT = name
    g = globals()
    g["GLASS"], g["GLASS_HOVER"], g["GLASS_BORDER"] = fill(0.55), fill(0.85), fill(0.90)
    g.setdefault("GRID_LINE", None)
    if "GRID_LINE" not in THEMES[name][1]:
        g["GRID_LINE"], g["FIELD_BORDER"] = tint(0.10), tint(0.22)
    STYLESHEET = build_stylesheet()


def build_stylesheet() -> str:
    return f"""

QWidget {{ color: {TEXT}; font-family: "{FONT_FAMILY}"; font-size: 13px; }}
QToolTip {{ background: {SOLID}; color: {TEXT}; border: 1px solid {FIELD_BORDER}; padding: 4px; }}

QPushButton {{
    background: {fill(0.70)}; border: 1px solid {GLASS_BORDER};
    border-radius: 10px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {fill(0.95)}; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; }}
/* 키보드(Tab)로 옮겨 다닐 때만 보이는 포커스 표시. 마우스로 누른 버튼에는 포커스가 가지 않는다(ui/widgets.py keyboard_focus_only) */
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#primary:focus {{ border: 2px solid {TEXT}; }}
QPushButton#headerBtn:focus, QPushButton#nav:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ON_ACCENT}; border: 0; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#danger {{ color: {SUNDAY}; }}
QPushButton#nav {{ padding: 0; min-width: 34px; max-width: 34px; }}

QLabel#title {{ font-size: 22px; font-weight: 600; }}
QLabel#error {{ color: {SUNDAY}; }}
QLabel#weekday {{ background: transparent; color: {TEXT_SOFT}; padding: 10px 0 6px 0; }}
QLabel#cardTitle {{ font-weight: 600; letter-spacing: 1px; color: {TEXT_SOFT}; }}

QFrame#card {{
    background: {GLASS}; border: 1px solid {GLASS_BORDER}; border-radius: 20px;
}}
QFrame#dayCell {{
    background: {fill(0.35)};
    border-right: 1px solid {GRID_LINE}; border-bottom: 1px solid {GRID_LINE};
}}
QFrame#dayCell[hover="true"] {{ background: {GLASS_HOVER}; }}
QPushButton#cellPlus {{
    background: {SOLID}; border: 1px solid {FIELD_BORDER}; border-radius: 7px;
    padding: 0; font-size: 15px; color: {ACCENT};
}}
QPushButton#more {{
    background: transparent; border: 0; color: {TEXT_SOFT}; text-align: left;
    padding: 0 0 0 8px; font-size: 12px;
}}

QPushButton#cardPlus {{
    background: {fill(0.80)}; border: 1px solid {FIELD_BORDER}; border-radius: 12px;
    padding: 0; font-size: 16px; color: {ACCENT};
}}
QPushButton#cardPlus:hover {{ background: {SOLID}; }}
QPushButton#todoTitle {{
    background: transparent; border: 0; border-radius: 0; padding: 0; text-align: left;
}}
QPushButton#todoDelete {{
    background: {fill(0.92)}; border: 1px solid {FIELD_BORDER}; border-radius: 8px;
    padding: 0 0 2px 0; color: {SUNDAY}; font-size: 15px; font-weight: 600;
}}
QPushButton#todoDelete:hover {{ background: {SUNDAY}; color: white; }}
QPushButton#undo {{
    background: transparent; border: 0; color: {UNDO_TEXT}; font-weight: 600; padding: 4px 8px;
}}
QPushButton#undo:hover {{ color: white; }}
QFrame#toast {{ background: {TOAST_BG}; border-radius: 12px; }}
QFrame#toast QLabel {{ color: white; background: transparent; }}

QPushButton#headerBtn {{ font-size: 15px; font-weight: 600; padding: 0; min-width: 38px; }}
QFrame#overlayPanel {{ background: {SOLID}; border: 1px solid {FIELD_BORDER}; border-radius: 16px; }}
QPushButton#menuItem {{
    background: transparent; border: 0; border-radius: 10px; text-align: left; padding: 10px 16px;
}}
QPushButton#menuItem:hover {{ background: {tint(0.12)}; }}
QPushButton#menuItem:disabled {{ color: {TEXT_MUTED}; }}
QFrame#menuSeparator {{ background: {GRID_LINE}; border: 0; }}

QPushButton#cardAi {{
    background: {fill(0.80)}; border: 1px solid {ACCENT}; border-radius: 12px;
    padding: 0 10px; min-height: 24px; max-height: 24px; font-size: 12px; font-weight: 700; color: {ACCENT};
}}
QPushButton#cardAi:hover {{ background: {SOLID}; }}
QPushButton#cardAi:disabled {{ border-color: {FIELD_BORDER}; color: {TEXT_MUTED}; background: {fill(0.45)}; }}
QPushButton#primary:disabled {{ background: {ACCENT_DISABLED}; color: {ON_ACCENT}; }}
QPushButton:checked {{ background: {SOLID}; border: 1px solid {ACCENT}; color: {ACCENT}; }}
QFrame#inboxRow {{
    background: {fill(0.62)}; border: 1px solid {GLASS_BORDER}; border-radius: 12px;
}}
QFrame#inboxRow QLabel {{ background: transparent; }}
QPushButton[compact="true"] {{ padding: 3px 10px; font-size: 12px; border-radius: 8px; }}
QLabel#warn {{ color: #B9672B; font-weight: 600; }}

QLabel#sectionTitle {{ font-weight: 600; color: {ACCENT}; padding-top: 6px; }}
QLabel#note {{ color: {TEXT_SOFT}; font-size: 12px; }}
QLabel#ok {{ color: #2E9E73; }}
QKeySequenceEdit {{ background: transparent; }}

QLabel#dialogTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#hint {{ color: {TEXT_SOFT}; }}
QLabel#empty {{ color: {TEXT_MUTED}; }}

QLineEdit, QDateEdit, QTimeEdit, QComboBox {{
    background: {fill(0.85)}; border: 1px solid {FIELD_BORDER};
    border-radius: 10px; padding: 6px 8px;
    selection-background-color: {SELECTION}; selection-color: {TEXT};
}}
QComboBox, QDateEdit {{ padding-right: 32px; }}
QAbstractSpinBox QLineEdit {{ background: transparent; border: 0; padding: 0; }}  /* 안쪽 편집기에 입력창 스타일이 겹치지 않게 */
/* 시간 입력칸의 위아래 화살표는 없앤다. NoButtons 는 스타일시트와 함께 쓰면 글자 영역이 1px 로 줄어서,
   버튼 영역의 너비를 0 으로 두는 방식을 쓴다 (휠, ↑↓ 키로 계속 바꿀 수 있다). */
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0px; height: 0px; border: 0; padding: 0; margin: 0; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 30px; border: 0; background: transparent;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: {SOLID}; border: 1px solid {FIELD_BORDER}; padding: 4px; outline: 0;
    selection-background-color: {tint(0.14)}; selection-color: {TEXT};
}}
QComboBox QAbstractItemView::item {{ padding: 6px 10px; min-height: 22px; border-radius: 6px; }}
QPushButton#dialogClose {{
    background: {fill(0.65)}; border: 0; border-radius: 14px; padding: 0 0 2px 0;
    font-size: 17px; color: {TEXT_SOFT};
}}
QPushButton#dialogClose:hover {{ background: {SOLID}; color: {ACCENT}; }}
QLineEdit:focus, QDateEdit:focus, QTimeEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}
QTextEdit#memo {{
    background: {MEMO_BG}; border: 1px solid {fill(0.9)}; border-radius: 14px;
    padding: 10px 8px; selection-background-color: {SELECTION}; selection-color: {TEXT};
}}
QTextEdit#memo:focus {{ border: 1px solid {FIELD_BORDER}; }}

QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background: {fill(0.75)}; border-top-left-radius: 10px; border-top-right-radius: 10px;
}}
QCalendarWidget QToolButton {{
    color: {TEXT}; background: transparent; border: 0; border-radius: 8px; padding: 4px 8px;
    font-weight: 600;
}}
QCalendarWidget QToolButton:hover {{ background: {tint(0.12)}; }}
QCalendarWidget QMenu {{ background: {SOLID}; }}
QCalendarWidget QSpinBox {{ background: {SOLID}; border: 1px solid {FIELD_BORDER}; border-radius: 6px; }}
QCalendarWidget QAbstractItemView:enabled {{
    background-color: {SOLID}; alternate-background-color: {SOLID}; color: {TEXT}; outline: 0;
    selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}
QCalendarWidget QAbstractItemView:disabled {{ color: {TEXT_MUTED}; }}

QSlider:horizontal {{ min-height: 24px; }}
QSlider::groove:horizontal {{ height: 6px; background: {tint(0.18)}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0; border-radius: 9px; background: {SOLID};
    border: 2px solid {ACCENT};
}}
QSlider::handle:horizontal:hover {{ background: {SOLID_HOVER}; }}

QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {tint(0.25)}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QMenu {{
    background: {SOLID}; border: 1px solid {FIELD_BORDER}; padding: 6px;
}}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {tint(0.12)}; }}
QMenu::separator {{ height: 1px; background: {GRID_LINE}; margin: 4px 8px; }}
"""


apply(DEFAULT_THEME)
