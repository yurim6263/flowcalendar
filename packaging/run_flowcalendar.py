"""PyInstaller 가 묶을 때 쓰는 시작 파일. `python -m flowcalendar` 와 같은 동작이다."""

from flowcalendar.app import run

if __name__ == "__main__":
    raise SystemExit(run())
