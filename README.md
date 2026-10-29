# Flow Calendar

컴퓨터를 켜는 순간부터 함께하는 **Windows 데스크톱 달력**입니다. 월간 달력을 중심으로 일정, 할 일(To-Do), 메모를 한 화면에서 관리하고, 원하면 AI로 입력을 줄일 수 있습니다.
**데이터는 내 컴퓨터에만 저장**됩니다(서버·로그인·계정 없음, 인터넷이 없어도 AI를 뺀 모든 기능이 동작).

![앱 아이콘](assets/flowcalendar.png)

## 주요 기능

- **월간 달력**: 일정(색 5가지, 반복, 알림, **여러 날에 걸친 일정**), 칩/막대를 **끌어서 다른 날로 이동**(Ctrl = 복사), 수정 팝업의 복제
- **To-Do**: 날짜별 Daily To-Do, 날짜 없는 Quick To-Do, 완료 체크, 우선순위, 삭제 되돌리기. 완료한 할 일은 설정한 기간(기본 30일) 뒤 자동 정리
- **Quick Memo**: 줄마다 불릿이 붙는 한 장 메모, 자동 저장
- **검색** (Ctrl+F): 일정·할 일 제목과 메모 내용을 한 번에
- **바탕화면 위젯 모드**: 테두리 없는 반투명 창으로 다른 창 뒤에 고정. 트레이 상주, Windows 알림, 전역 단축키, 시작 시 자동 실행
- **AI (선택, 내 API 키 필요)**: 문장으로 일정/할 일 만들기(`내일 오후 3시 팀 미팅 1시간`), 메모에서 고른 줄을 일정으로, 오늘/이번 주 브리핑. Gemini · Claude · OpenAI 중 선택
- **테마 11가지**: 분홍, 보라, 노랑, 하늘, 연두, 회색, 흰색, 검정(다크), 그라데이션 3종. 고르면 바로 적용
- **데이터 안전**: 하루 한 번 자동 백업(최근 7개), 구조 변경 전 자동 복사, JSON 내보내기/가져오기

## 설치해서 쓰기

자세한 순서와 화면별 설명은 [설치와 실행 방법](docs/CAL-GUIDE-001_설치와실행방법.md)에 있습니다.

1. `FlowCalendar-Setup-1.0.0.exe`를 실행합니다(관리자 권한 필요 없음, 내 계정에만 설치).
2. 설치가 끝나면 시작 메뉴의 **Flow Calendar**로 켭니다. 바탕화면 바로가기와 Windows 시작 시 자동 실행은 설치 중에 고를 수 있고, 나중에 앱 설정에서도 바꿀 수 있습니다.
3. 제거하려면 Windows 설정 → 앱에서 Flow Calendar를 지웁니다. **내 일정·할 일·메모는 지워지지 않습니다**(아래 데이터 위치).

> 설치 파일에는 디지털 서명이 없어서 Windows가 "알 수 없는 게시자" 경고(SmartScreen)를 보여 줄 수 있습니다.
> **추가 정보 → 실행**을 누르면 설치됩니다.

## 데이터와 개인정보

| 무엇 | 어디에 |
| --- | --- |
| 일정, 할 일, 메모, 설정 | `%APPDATA%\FlowCalendar\flowcalendar.db` (SQLite 파일 하나) |
| 자동 백업 | `%APPDATA%\FlowCalendar\backups\auto-날짜.db` (최근 7개) |
| AI API 키 | **Windows 자격 증명 관리자**에만. 파일, DB, 백업, 내보내기에 들어가지 않음 |

AI를 쓰면 **요청한 문장(또는 고른 메모 줄), 대상 기간 일정·할 일의 제목과 시간, 오늘 날짜**만 선택한 제공사로 보냅니다. 메모 전체와 완료한 할 일은 보내지 않습니다.
키는 설정에서 직접 넣을 때만 사용되며, 키가 없으면 AI 화면은 보이지 않습니다.

## 개발

필요: Python 3.13, Windows.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .

.venv\Scripts\python.exe -m flowcalendar          # 실행
.venv\Scripts\python.exe -m pytest -q             # 테스트
powershell -File packaging\build.ps1              # 실행 폴더 + 설치 파일 (dist\)
.venv\Scripts\python.exe tools\measure_perf.py --exe dist\FlowCalendar\FlowCalendar.exe   # 성능 측정
```

- 설치 파일을 만들려면 [Inno Setup 6](https://jrsoftware.org/isinfo.php)가 필요합니다(`winget install JRSoftware.InnoSetup`). 없으면 `packaging\build.ps1 -NoInstaller`로 실행 폴더까지만 만듭니다.
- 내 데이터를 건드리지 않고 시험하려면 환경 변수 `FLOWCALENDAR_DATA_DIR`로 다른 폴더를 지정합니다.
- 테스트는 실제 AI를 호출하지 않고(가짜 응답), 실제 자격 증명 관리자도 읽지 않습니다.

### 구조

```
src/flowcalendar/
  domain/     일정·할 일 모델, 반복 규칙 (순수 파이썬)
  data/       SQLite 저장소와 마이그레이션 (data/db.py MIGRATIONS 에 항목을 추가하는 방식)
  services/   알림, 자동 실행, 백업, 검색, AI 호출, 위젯 모드 등
  ai/         제공사별 어댑터, 자연어 변환, 브리핑
  ui/         PySide6 화면 (테마는 ui/tokens.py)
packaging/    PyInstaller 설정, Inno Setup 스크립트, 빌드 스크립트
tools/        아이콘 생성, 성능 측정
docs/         정의서(CAL-DOC-001), 실사용 점검표, 성능 측정 기록
tests/        pytest
```

규칙: `ui`는 SQLite를 직접 열지 않고 `data`/`services`를 거칩니다. 스키마를 바꿀 때는 기존 마이그레이션을 고치지 않고 새 항목을 추가합니다.

## 문서

노션은 더 이상 쓰지 않고, 아래 문서가 기준입니다.

- [설치와 실행 방법 CAL-GUIDE-001](docs/CAL-GUIDE-001_설치와실행방법.md): 설치, 설정, 업데이트, 제거, 백업, 빌드, GitHub 올리기 순서
- [프로젝트 개요와 진행 상태 CAL-DOC-002](docs/CAL-DOC-002_프로젝트개요와진행상태.md): 개요, 기술 스택, 진행 상태, 이후 계획, 변경 이력
- [정의서 CAL-DOC-001](docs/CAL-DOC-001_Ver1.0_정의서.md): 요구사항과 결정 기록(기준 문서)
- [실사용 점검표 CAL-CHECK-001](docs/CAL-CHECK-001_실사용점검표.md): 실제 컴퓨터에서 직접 확인할 항목
- [성능 측정 CAL-PERF-001](docs/CAL-PERF-001_성능측정.md): 방법과 결과
