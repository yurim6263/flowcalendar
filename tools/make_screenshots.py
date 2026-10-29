"""README 용 화면 캡처(docs/images/*.png)를 만든다.

내 실제 데이터는 쓰지 않는다. 메모리 DB에 가짜(데모) 일정·할 일·메모를 넣고, 화면 없이(offscreen) 위젯을 그려서 저장한다.
실행:  .venv\\Scripts\\python.exe tools\\make_screenshots.py
"""

import os
import sys
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = ROOT / "docs" / "images"
TODAY = date(2026, 10, 28)


class DemoSecrets:
    """설정 화면용: 키 저장소 대신 메모리만 쓴다."""

    def has(self, provider):
        return False

    def get(self, provider):
        return None

    def set(self, provider, value):
        pass

    def delete(self, provider):
        pass


def demo_window():
    from flowcalendar.data import db
    from flowcalendar.data.memo_repo import MemoRepository
    from flowcalendar.data.schedule_repo import ScheduleRepository
    from flowcalendar.data.todo_repo import TodoRepository
    from flowcalendar.domain.models import Schedule, Todo
    from flowcalendar.ui.main_window import MainWindow

    conn = db.connect(":memory:")
    s, t, m = ScheduleRepository(conn), TodoRepository(conn), MemoRepository(conn)
    d = datetime
    s.add(Schedule("주간 회의", d(2026, 10, 5, 10), d(2026, 10, 5, 11), color="green", recurrence="weekly"))
    s.add(Schedule("치과 예약", d(2026, 10, 8, 14), d(2026, 10, 8, 15), color="purple"))
    s.add(Schedule("제주 여행", d(2026, 10, 12), d(2026, 10, 14), all_day=True, color="blue"))
    s.add(Schedule("프로젝트 마감", d(2026, 10, 16, 18), d(2026, 10, 16, 19), color="pink"))
    s.add(Schedule("워크숍", d(2026, 10, 21, 9), d(2026, 10, 23, 18), color="green"))
    s.add(Schedule("중간 발표 준비", d(2026, 10, 26), d(2026, 10, 30), all_day=True, color="yellow"))
    s.add(Schedule("팀 회의", d(2026, 10, 28, 10), d(2026, 10, 28, 11), color="pink"))
    s.add(Schedule("점심 약속", d(2026, 10, 28, 12), d(2026, 10, 28, 13), color="yellow"))
    s.add(Schedule("코드 리뷰", d(2026, 10, 29, 15), d(2026, 10, 29, 16), color="blue"))
    s.add(Schedule("운동", d(2026, 10, 30, 19), d(2026, 10, 30, 20), color="green"))
    for title, day in (("발표 자료 정리", TODAY), ("PR 리뷰 답변", TODAY), ("장보기", date(2026, 10, 29))):
        t.add(Todo(title, day=day))
    for title in ("책 반납하기", "영양제 주문", "여권 사진 찍기"):
        t.add(Todo(title))
    m.set("읽을 것 / 아이디어\n달력 위젯 디자인 참고\n이번 주 회고 쓰기\n다음 달 여행 예약")
    window = MainWindow(s, t, m, today=TODAY)
    window.resize(1280, 800)
    window.memo_card.edit.set_content(m.get())
    return window, (s, t, m, conn)


def save(widget, name: str) -> QImage:
    QApplication.processEvents()
    image = widget.grab().toImage()
    image.save(str(OUT / name), "PNG")
    print("저장:", OUT / name, f"{(OUT / name).stat().st_size // 1024} KB")
    return image


def main() -> None:
    app = QApplication([])
    for font in ("malgun.ttf", "malgunbd.ttf"):
        path = Path("C:/Windows/Fonts") / font
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    from flowcalendar.domain.models import Occurrence
    from flowcalendar.services.search import search_all
    from flowcalendar.ui import tokens
    from flowcalendar.ui.ai_dialogs import QuickAddDialog
    from flowcalendar.ui.dialogs import ScheduleDialog
    from flowcalendar.ui.search_dialog import SearchDialog
    from flowcalendar.ui.settings_dialog import SettingsBackend, SettingsDialog

    OUT.mkdir(parents=True, exist_ok=True)
    tokens.apply("pink")
    app.setStyleSheet(tokens.STYLESHEET)
    window, (s, t, m, conn) = demo_window()
    window.show()
    save(window, "main.png")

    # 테마 모음 (2x2)
    shots = []
    for key in ("sky", "black", "gradient_sunset", "lime"):
        tokens.apply(key)
        app.setStyleSheet(tokens.STYLESHEET)
        w, _ = demo_window()
        w.show()
        QApplication.processEvents()
        shots.append((tokens.THEMES[key][0], w.grab().toImage()))
        w.close()
    tw, th = 640, 400
    sheet = QImage(tw * 2 + 30, th * 2 + 30 + 2 * 28, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#FFFFFF"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    font = QFont("Malgun Gothic")
    font.setPixelSize(16)
    font.setBold(True)
    painter.setFont(font)
    for i, (label, image) in enumerate(shots):
        x, y = 10 + (i % 2) * (tw + 10), 10 + (i // 2) * (th + 38)
        painter.setPen(QColor("#444444"))
        painter.drawText(x, y + 16, label)
        painter.drawImage(x, y + 24, image.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
    painter.end()
    sheet.save(str(OUT / "themes.png"), "PNG")
    print("저장:", OUT / "themes.png")

    tokens.apply("pink")
    app.setStyleSheet(tokens.STYLESHEET)

    # 여러 날 일정 수정 팝업
    occ = next(o for o in s.list_occurrences(date(2026, 10, 26), date(2026, 10, 26)) if o.title == "중간 발표 준비")
    dialog = ScheduleDialog(window, occurrence=Occurrence(occ.schedule, occ.date, occ.start_at, occ.end_at))
    dialog.show()
    save(dialog, "schedule-dialog.png")
    dialog.close()

    # 검색
    search = SearchDialog(window, lambda q: search_all(s, t, m, q, TODAY))
    search.show()
    search.input.setText("회")
    save(search, "search.png")
    search.close()

    # AI 빠른 추가 (입력 예시만 보여 준다. 실제 AI 호출은 없다)
    quick = QuickAddDialog(window, object(), None, auto_register=True)
    quick.show()
    quick.input.setText("내일 오후 3시 팀 미팅 1시간")
    save(quick, "ai-quick-add.png")
    quick.close()

    # 설정
    from flowcalendar.data.settings_repo import SettingsRepository

    backend = SettingsBackend(
        settings=SettingsRepository(conn), secrets=DemoSecrets(), autostart_enabled=lambda: False,
        set_autostart=lambda on: None, apply_hotkey=lambda text: (True, ""),
        export_data=lambda path: None, import_data=lambda path: path,
    )
    settings = SettingsDialog(backend, window)
    settings.resize(560, 760)
    settings.show()
    save(settings, "settings.png")
    settings.close()
    window.close()
    app.quit()


if __name__ == "__main__":
    main()
