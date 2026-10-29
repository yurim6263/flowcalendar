# -*- mode: python ; coding: utf-8 -*-
# Flow Calendar 실행 폴더(one-folder) 만들기. 사용: packaging\build.ps1  (또는 pyinstaller packaging\flowcalendar.spec)
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

# 앱이 쓰는 Qt 모듈은 QtCore, QtGui, QtWidgets, QtNetwork(단일 실행 확인용) 뿐이다. 나머지는 빼서 크기와 메모리를 줄인다.
UNUSED_QT = [
    "QtQml", "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtPdf", "QtPdfWidgets", "QtSvg", "QtSvgWidgets",
    "QtOpenGL", "QtOpenGLWidgets", "QtSql", "QtTest", "QtDBus", "QtDesigner", "QtHelp", "QtConcurrent",
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets",
    "QtMultimedia", "QtMultimediaWidgets", "QtBluetooth", "QtNfc", "QtPositioning", "QtSensors",
    "QtSerialPort", "QtCharts", "QtDataVisualization", "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic",
    "Qt3DAnimation", "Qt3DExtras", "QtXml", "QtStateMachine", "QtScxml", "QtRemoteObjects", "QtSpatialAudio",
    "QtTextToSpeech", "QtHttpServer", "QtGraphs", "QtLocation", "QtNetworkAuth", "QtUiTools", "QtAxContainer",
]
EXCLUDES = [f"PySide6.{name}" for name in UNUSED_QT] + [
    "tkinter", "unittest", "pydoc", "doctest", "test", "distutils", "setuptools", "pip", "pytest", "PyInstaller",
    "numpy", "pandas", "matplotlib", "PIL",
]

a = Analysis(
    [str(ROOT / "packaging" / "run_flowcalendar.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    # keyring 은 실행 중에 백엔드를 이름으로 찾기 때문에 분석기가 못 본다 -> 직접 넣는다
    hiddenimports=collect_submodules("keyring.backends") + collect_submodules("win32ctypes"),
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

# 앱이 쓰지 않는 Qt 부품(소프트웨어 OpenGL 19MB, SVG, 쓰지 않는 이미지 형식, 네트워크 TLS 등)은 묶지 않는다.
# 달력은 위젯(래스터) 화면이라 OpenGL 이 필요 없고, 이미지 파일을 읽지도 않는다. 창 표시에 쓰는 qwindows 와 스타일은 그대로 둔다.
DROP = (
    "opengl32sw.dll", "qt6svg", "qsvg", "qicns", "qtga", "qtiff", "qwbmp", "qwebp", "qdirect2d", "qoffscreen", "qminimal",
    "qtuiotouchplugin", "qnetworklistmanager", "qcertonlybackend", "qopensslbackend", "qschannelbackend",
)
a.binaries = [item for item in a.binaries if not any(part in item[0].lower() for part in DROP)]

# Qt 번역 파일(수십 개 언어)은 앱이 읽지 않는다. 화면 글자는 모두 앱 안에 한국어로 들어 있다.
a.datas = [item for item in a.datas if "translations" not in item[0].lower().replace("\\", "/").split("/")]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FlowCalendar",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # 콘솔 창 없이 실행
    icon=str(ROOT / "assets" / "flowcalendar.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FlowCalendar")
