# CAL-GUIDE-001 설치와 실행 방법

Flow Calendar v1.0.0을 설치하고 쓰기까지의 순서입니다. 1~6장은 **쓰는 사람**, 7~8장은 **만드는 사람(개발자)** 용입니다.

---

## 1. 설치하기

> 설치 마법사 화면은 작성자가 화면으로 직접 확인하지 못하고(자동 설치로만 시험), Inno Setup의 표준 화면을 기준으로 썼습니다. 버튼·창 이름이 조금 다를 수 있으니 처음 설치해 보시고 다른 부분은 이 문서를 고쳐 주세요.

**필요한 것**: Windows 10/11 (64비트), 설치 파일 `FlowCalendar-Setup-1.0.0.exe` (약 22MB). 관리자 권한은 필요 없습니다.

1. 설치 파일(`FlowCalendar-Setup-1.0.0.exe`)을 내려받아 원하는 폴더(예: 다운로드)에 둡니다.
2. 파일을 **더블클릭**합니다.
3. 파란 창 **"Windows의 PC 보호"(SmartScreen)** 가 뜨면 아래처럼 합니다. 설치 파일에 디지털 서명이 없어서 나오는 정상 경고입니다.
   1. **추가 정보**를 누릅니다.
   2. 나타난 **실행** 버튼을 누릅니다.
4. 먼저 **"설치 모드 선택"** 창이 나오면 **"현재 사용자만 설치"**(내 계정에만, 관리자 권한 불필요)를 고릅니다. 이 창이 안 나오면 이미 그 모드입니다.
   - "모든 사용자"를 고르면 관리자 권한(UAC) 확인이 뜨고 `Program Files`에 설치됩니다. 보통은 필요 없습니다.
5. 설치 마법사의 언어는 한국어입니다. **다음**을 눌러 진행합니다.
   - 설치 위치는 기본값(내 계정의 `AppData\Local\Programs\Flow Calendar`)을 권장합니다.
6. **추가 작업** 화면에서 원하는 것만 체크합니다(둘 다 기본은 꺼짐).
   - ☐ 바탕화면에 바로가기 만들기
   - ☐ Windows를 켤 때 트레이에서 자동으로 시작
7. **설치**를 누르고 끝날 때까지 기다립니다(수십 초).
8. 마지막 화면에서 **Flow Calendar 실행**을 체크한 채 **마침**을 누르면 바로 켜집니다.
9. 나중에 켜려면 **시작 메뉴 → Flow Calendar**(또는 만들어 둔 바탕화면 바로가기)를 누릅니다.

> 설치해도 이미 쓰던 일정·할 일·메모는 그대로 남아 있습니다(데이터는 설치 폴더가 아니라 `%APPDATA%\FlowCalendar`에 있습니다).

---

## 2. 처음 켠 뒤 해 볼 설정 (모두 선택)

설정은 화면 오른쪽 위 **☰ → 설정**에서 합니다. 바꾼 뒤 **저장**을 눌러야 유지됩니다.

1. **테마 고르기**: 맨 위 색 동그라미를 누르면 바로 바뀝니다. 마음에 들면 저장.
2. **알림**: "일정 시작 전 알림 표시"가 켜져 있는지 확인합니다. 알림 시간은 일정을 만들 때 일정마다 고릅니다.
3. **Windows 시작 시 자동 실행**: 켜 두면 로그인할 때 창 없이 트레이에서 조용히 시작합니다.
4. **위젯 모드**: ☰ → "위젯 모드 켜기". 테두리 없는 반투명 창이 되어 다른 창 뒤(바탕화면 위)에 떠 있습니다. 배경 투명도는 설정에서 조절합니다.
5. **데이터 관리**: 자동 백업(하루 한 번, 최근 7개)이 켜져 있는지, 완료한 할 일 보관 기간(기본 30일)이 괜찮은지 확인합니다.

### AI 기능 켜기 (선택, 본인의 API 키가 필요)

AI는 **키를 넣어야만** 화면에 나타납니다. 키가 없어도 나머지 기능은 모두 동작합니다.

1. 사용할 AI 제공사(Gemini / Claude / OpenAI)에서 **API 키를 발급**받습니다. (Gemini는 무료 사용량이 있습니다. 한도와 조건은 제공사 정책을 따릅니다.)
2. 앱의 **☰ → 설정 → AI**에서 **제공사**를 고릅니다.
3. **API 키**를 붙여넣습니다. 키는 파일이 아니라 **Windows 자격 증명 관리자**에만 저장됩니다.
4. (선택) **사용 가능한 모델 불러오기**를 눌러 모델을 고릅니다. 비워 두면 기본 모델을 씁니다.
5. **저장**을 누릅니다. 헤더에 **✨** 버튼이 생기고, 메모 카드에 **AI** 버튼이 생깁니다.
6. 시험해 보기: ✨를 눌러 `내일 오후 3시 팀 미팅 1시간`을 입력하면 일정이 등록되고, 5초 동안 **되돌리기**가 뜹니다.

---

## 3. 업데이트하기

1. 새 버전의 설치 파일을 받습니다.
2. 앱이 켜져 있어도 상관없습니다. 설치 파일을 **더블클릭**해 1장과 같은 순서로 진행하면 **같은 위치에 덮어써서** 업데이트됩니다(설치기가 실행 중인 앱을 닫습니다).
3. 일정·할 일·메모와 설정은 그대로 유지됩니다. 데이터 구조가 바뀌는 버전이면 앱이 처음 켤 때 `backups` 폴더에 자동으로 복사본(`before-schema…db`)을 만들어 둡니다.

---

## 4. 제거하기

1. **Windows 설정 → 앱 → 설치된 앱**에서 **Flow Calendar**를 찾아 **제거**를 누릅니다.
2. 프로그램 파일, 시작 메뉴/바탕화면 바로가기, 자동 실행 항목이 지워집니다.
3. **내 일정·할 일·메모는 지워지지 않습니다.** 나중에 다시 설치하면 그대로 이어서 쓸 수 있습니다.

데이터까지 **완전히 지우려면** (되돌릴 수 없으니 먼저 6장 백업을 권장):

1. 앱을 끕니다(트레이 아이콘 우클릭 → 종료).
2. 탐색기 주소창에 `%APPDATA%\FlowCalendar`를 입력해 열고, 그 폴더를 삭제합니다.
3. AI 키도 지우려면 **제어판 → 자격 증명 관리자 → Windows 자격 증명**에서 `FlowCalendar`로 시작하는 항목을 삭제합니다(앱 설정의 **키 삭제**로도 지울 수 있습니다).

---

## 5. 데이터 위치

| 무엇 | 위치 |
| --- | --- |
| 일정·할 일·메모·설정 | `%APPDATA%\FlowCalendar\flowcalendar.db` |
| 자동 백업 | `%APPDATA%\FlowCalendar\backups\auto-날짜.db` (최근 7개) |
| 구조 변경 전 복사본 | `%APPDATA%\FlowCalendar\backups\before-schema…db` |
| AI API 키 | Windows 자격 증명 관리자 (파일에는 없음) |

`%APPDATA%`는 탐색기 주소창에 그대로 입력하면 열립니다(보통 `C:\Users\내이름\AppData\Roaming`).

---

## 6. 백업하고 복원하기, 다른 컴퓨터로 옮기기

### 방법 A. 내보내기/가져오기 (추천, 다른 컴퓨터로 옮길 때도 이 방법)

1. 옛 컴퓨터에서 **☰ → 설정 → 데이터 백업 → 내보내기…**를 눌러 JSON 파일을 저장합니다.
2. 그 파일을 새 컴퓨터로 옮깁니다(USB, 클라우드 등).
3. 새 컴퓨터에 Flow Calendar를 설치하고 **☰ → 설정 → 데이터 백업 → 가져오기…**로 그 파일을 고릅니다.
4. 확인 창에서 진행하면 **현재 데이터가 파일 내용으로 교체**됩니다. 교체 직전에 현재 데이터를 자동으로 `backups`에 복사해 둡니다.
5. AI 키는 파일에 들어 있지 않으므로 새 컴퓨터에서 다시 넣습니다(2장).

### 방법 B. 자동 백업 파일로 되돌리기 (앱이 이상하거나 데이터를 잘못 지웠을 때)

1. 앱을 끕니다(트레이 아이콘 우클릭 → 종료).
2. `%APPDATA%\FlowCalendar`를 엽니다.
3. 현재 `flowcalendar.db`를 안전하게 **다른 이름으로 복사**해 둡니다(예: `flowcalendar-문제있음.db`).
4. `backups` 폴더에서 돌아가고 싶은 날짜의 `auto-날짜.db`를 복사해 상위 폴더에 붙여 넣고, 이름을 `flowcalendar.db`로 바꿉니다(기존 파일 덮어쓰기).
5. 앱을 켭니다.

---

## 7. (개발자) 소스에서 실행하고 설치 파일 만들기

**필요한 것**: Windows, Python 3.13, (설치 파일을 만들 때만) Inno Setup 6.

1. 프로젝트 폴더에서 가상환경을 만들고 패키지를 설치합니다.
   ```powershell
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   .venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
   ```
2. 실행해 봅니다: `.venv\Scripts\python.exe -m flowcalendar`
3. 테스트를 돌립니다: `.venv\Scripts\python.exe -m pytest -q` (실제 AI를 호출하지 않고, 실제 키 저장소도 읽지 않습니다. 이 컴퓨터에서는 10분 넘게 걸릴 수 있습니다.)
4. 설치 파일을 만들 준비(처음 한 번): `winget install JRSoftware.InnoSetup`
5. 빌드: `powershell -File packaging\build.ps1`
   - 아이콘 생성 → PyInstaller 실행 폴더(`dist\FlowCalendar`) → Inno Setup 설치 파일(`dist\FlowCalendar-Setup-1.0.0.exe`) 순서로 진행합니다.
   - 실행 폴더까지만: `powershell -File packaging\build.ps1 -NoInstaller`
6. 성능 측정(선택): `.venv\Scripts\python.exe tools\measure_perf.py --exe dist\FlowCalendar\FlowCalendar.exe`
7. **버전을 올릴 때는 4곳을 같이 고칩니다**: `src\flowcalendar\__init__.py`, `pyproject.toml`, `packaging\version_info.txt`, `packaging\flowcalendar.iss`(`AppVersion`). `tests\test_packaging.py`가 서로 같은지 확인해 줍니다.
8. 설치 파일을 직접 시험하려면: 다른 폴더로 조용히 설치해 본 뒤 제거할 수 있습니다.
   ```powershell
   dist\FlowCalendar-Setup-1.0.0.exe /VERYSILENT /CURRENTUSER /DIR="C:\Temp\fc-test" /TASKS=""
   C:\Temp\fc-test\unins000.exe /VERYSILENT
   ```
   (제거 때 `Run` 키의 `FlowCalendar` 자동 실행 값도 같이 지워지니, 개발용 자동 실행을 쓰고 있다면 다시 켜 주세요.)

---

## 8. (개발자) GitHub

저장소: https://github.com/yurim6263/flowcalendar (**Public**, 2026-10-29 공개). 디자인 시안 폴더(`ui_design`)와 빌드 결과(`dist`, `build`), 가상환경(`.venv`)은 `.gitignore`로 제외되어 올라가지 않습니다.
커밋 작성자는 이 저장소에만 GitHub noreply 주소(`ID+yurim6263@users.noreply.github.com`)로 설정되어 있어, 공개해도 개인 이메일이 기록에 보이지 않습니다.

### 8.1 평소에 변경을 올리기

```powershell
git status                      # 올라갈 파일 확인 (키·비밀번호가 없는지 훑어보기)
git add .
git commit -m "변경 내용 설명"
git push
```

### 8.2 새 버전을 배포하기 (Releases)

1. 버전을 올립니다(7장 7번의 4곳) → 테스트 → `powershell -File packaging\build.ps1`
2. 커밋하고 푸시합니다.
3. 릴리스를 만들어 설치 파일을 첨부합니다.
   ```powershell
   gh release create v1.1.0 dist\FlowCalendar-Setup-1.1.0.exe --title "Flow Calendar v1.1.0" --notes "변경 내용과 SHA256"
   ```
   (웹에서는 저장소 → **Releases → Draft a new release**에 태그를 입력하고 설치 파일을 끌어다 놓은 뒤 Publish)
4. 설치 파일은 저장소에 커밋하지 않고 **Releases에만** 올립니다.

> Public 저장소의 Releases는 누구나(로그인 없이) 내려받을 수 있습니다. 릴리스 설명에 설치 파일의 SHA256 값(`Get-FileHash`로 구함)을 같이 적습니다.

### 8.3 Public(공개)으로 바꾸기 전 점검

- [x] `LICENSE`(MIT) 파일이 있다 — **MIT는 누구나 쓰고 고치고 팔 수 있는 라이선스입니다. 다른 조건을 원하면 공개 전에 바꾸세요.**
- [x] 사용한 오픈소스 고지(`THIRD_PARTY_NOTICES.md`)가 있다
- [x] README에 화면 캡처와 설명이 있다 (캡처는 데모 데이터)
- [x] 커밋 이메일이 noreply 주소다
- [x] 비밀키·토큰 패턴 검색에서 발견된 것이 없다
- [x] **개인 정보 최종 확인**: 정의서의 작성자 이름(`이유림`)과 LICENSE의 이름 공개 — 본인이 공개해도 된다고 확인함
- [x] **커밋 기록 확인**: 모든 커밋에서 키·토큰·개인 이메일·내 PC 경로 패턴을 검색했고 발견된 것이 없음(Public이 되면 과거 기록도 모두 보입니다)
- [x] Issues는 켜 두고, Wiki·Projects는 껐다
- [x] 저장소 About 설명과 Topics 설정

### 8.4 공개로 전환하는 방법

1. 저장소 → **Settings → 맨 아래 Danger Zone → Change repository visibility → Make public**
   (2026-10-29에 공개로 전환했다. 아래는 다시 바꿀 때 참고)
2. 확인 창에서 저장소 이름을 입력합니다.
3. 전환 후 로그아웃한 브라우저(시크릿 창)에서 저장소 주소와 Releases 링크가 열리는지 확인합니다.
4. 되돌리려면 같은 곳에서 Make private (이미 공개된 동안 복제·저장된 것은 되돌릴 수 없습니다).
