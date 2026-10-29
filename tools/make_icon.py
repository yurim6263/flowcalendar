"""앱 아이콘 파일(assets/flowcalendar.ico, .png)을 만든다.

아이콘 그림은 ui/icons.py 의 _draw()가 크기마다 직접 그린다(작은 크기를 줄여서 쓰지 않아 또렷하다).
실행:  .venv\\Scripts\\python.exe tools\\make_icon.py
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(pixmap) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(data)


def build_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """PNG 프레임들로 .ico 를 만든다 (Windows Vista 이후 지원). 너비/높이 256 은 0 으로 적는다."""
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries, body = b"", b""
    for size, data in frames:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return header + entries + body


def main() -> None:
    QGuiApplication.instance() or QGuiApplication([])
    from flowcalendar.ui.icons import _draw

    frames = [(size, png_bytes(_draw(size))) for size in SIZES]
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    (out / "flowcalendar.ico").write_bytes(build_ico(frames))
    (out / "flowcalendar.png").write_bytes(frames[-1][1])
    print(f"만듦: {out / 'flowcalendar.ico'} ({len(SIZES)}개 크기)")


if __name__ == "__main__":
    main()
