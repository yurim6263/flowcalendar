# 사용한 오픈소스 (Third-party notices)

Flow Calendar 자체는 [MIT 라이선스](LICENSE)입니다. 아래는 실행·배포에 쓰이는 주요 구성 요소입니다. 라이선스 정보는 설치된 패키지의 메타데이터(`importlib.metadata`)를 2026-10-29에 확인한 것이며, 정확한 조건은 각 프로젝트의 원문을 따릅니다.

| 구성 요소 | 용도 | 라이선스 |
| --- | --- | --- |
| [Qt for Python (PySide6 Essentials, Shiboken)](https://doc.qt.io/qtforpython/) 6.12 | 화면(UI) | LGPL-3.0 또는 GPL-2.0/3.0 (이 프로젝트는 LGPL-3.0 조건으로 사용) |
| [keyring](https://github.com/jaraco/keyring) 25.7 | API 키를 Windows 자격 증명 관리자에 저장 | MIT |
| [pywin32-ctypes](https://github.com/enthought/pywin32-ctypes) 0.2.3 | keyring이 Windows API를 부르는 데 사용 | BSD-3-Clause |
| jaraco.classes / .functools / .context, more-itertools | keyring의 의존 패키지 | MIT |
| Python 3.13 | 실행 환경 | PSF License |
| [PyInstaller](https://pyinstaller.org/) 6.22 (빌드 도구) | 실행 파일 묶기 | GPL-2.0 이상 + 묶은 프로그램에는 라이선스 제한을 두지 않는 예외 조항 |
| [Inno Setup](https://jrsoftware.org/isinfo.php) 6 (빌드 도구) | 설치 파일 만들기 | Inno Setup License (무료, 설치 파일 배포 가능) |
| pytest (개발용) | 테스트 | MIT |

## Qt(LGPL) 관련

설치 폴더(`_internal\PySide6`)의 Qt 라이브러리는 **별도 DLL 파일**로 들어 있어 사용자가 교체할 수 있습니다(one-folder 방식). Qt 소스와 LGPL 조건은 https://www.qt.io/licensing/ 에서 받을 수 있습니다.

## AI 제공사

Gemini, Claude, OpenAI는 사용자가 **직접 발급한 API 키**로 각 제공사의 공개 API를 호출할 뿐이며, 어떤 SDK도 포함하지 않습니다(표준 라이브러리 `urllib` 사용). 사용 조건과 요금은 각 제공사의 정책을 따릅니다.
