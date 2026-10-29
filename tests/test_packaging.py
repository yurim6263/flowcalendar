"""배포 파일(버전, 아이콘, 빌드 설정)이 서로 맞는지 확인한다. 실제 빌드는 packaging\\build.ps1 이 한다."""

import re
import struct
import tomllib
from pathlib import Path

import flowcalendar

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_version_is_the_same_everywhere():
    version = flowcalendar.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert tomllib.loads(read("pyproject.toml"))["project"]["version"] == version
    info = read("packaging/version_info.txt")
    assert f"StringStruct('FileVersion', '{version}')" in info
    assert f"StringStruct('ProductVersion', '{version}')" in info
    numbers = ", ".join(version.split(".") + ["0"])
    assert f"filevers=({numbers})" in info and f"prodvers=({numbers})" in info
    assert f'#define AppVersion "{version}"' in read("packaging/flowcalendar.iss")


def test_icon_file_has_all_sizes_as_png_frames():
    data = (ROOT / "assets" / "flowcalendar.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 7)
    sizes = []
    for i in range(count):
        width, height, _, _, _, bits, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        sizes.append(width or 256)
        assert bits == 32 and data[offset:offset + 4] == b"\x89PNG"
    assert sizes == [16, 24, 32, 48, 64, 128, 256]


def test_installer_script_keeps_user_data_and_uses_per_user_install():
    iss = read("packaging/flowcalendar.iss")
    assert "PrivilegesRequired=lowest" in iss  # 관리자 권한 없이 설치
    assert "AppId={{6F3C8E1A-4B7D-4E52-9A36-5D1F2C0B7E91}" in iss  # 업데이트가 같은 앱으로 인식되게 ID 고정
    delete_lines = [line for line in iss.split("[UninstallDelete]")[1].split("[Code]")[0].splitlines()
                    if line.strip() and not line.lstrip().startswith(";")]
    assert delete_lines == ['Type: filesandordirs; Name: "{app}"']  # 설치 폴더만 지운다. 내 데이터 폴더는 건드리지 않는다
    assert 'ValueData: """{app}\\{#AppExe}"" --tray"' in iss  # 설정 화면의 자동 실행과 같은 값


def test_spec_bundles_keyring_and_drops_unused_qt_parts():
    spec = read("packaging/flowcalendar.spec")
    assert "collect_submodules(\"keyring.backends\")" in spec  # 키 저장소(Windows 자격 증명 관리자)를 묶는다
    assert "console=False" in spec
    for unused in ("QtWebEngineCore", "QtQuick", "QtMultimedia", "QtSql"):
        assert unused in spec
    for needed in ("QtCore", "QtGui", "QtWidgets", "QtNetwork"):
        assert f'"{needed}"' not in spec.split("UNUSED_QT = [")[1].split("]")[0]  # 앱이 쓰는 모듈은 빼지 않는다


def test_every_imported_qt_module_is_still_bundled():
    """앱 소스가 가져오는 PySide6 모듈이 spec 의 제외 목록에 들어 있지 않은지 (묶은 앱이 시작하자마자 죽는 것을 막는다)."""
    used = set()
    for path in (ROOT / "src" / "flowcalendar").rglob("*.py"):
        used |= set(re.findall(r"from PySide6\.(Qt\w+) import", path.read_text(encoding="utf-8")))
    excluded = set(re.findall(r'"(Qt\w+)"', read("packaging/flowcalendar.spec").split("UNUSED_QT = [")[1].split("]")[0]))
    assert used and not (used & excluded), used & excluded


def test_build_script_and_entry_point_exist():
    assert (ROOT / "packaging" / "build.ps1").exists()
    assert "run()" in read("packaging/run_flowcalendar.py")
    assert (ROOT / "tools" / "make_icon.py").exists() and (ROOT / "tools" / "measure_perf.py").exists()


def test_data_dir_override_is_used_for_database_path(monkeypatch, tmp_path):
    from flowcalendar.data import db

    monkeypatch.setenv(db.DATA_DIR_ENV, str(tmp_path))
    assert db.default_db_path() == tmp_path / db.DB_FILE_NAME
    monkeypatch.delenv(db.DATA_DIR_ENV)
    assert db.default_db_path().name == db.DB_FILE_NAME and tmp_path not in db.default_db_path().parents
