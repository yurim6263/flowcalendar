# Flow Calendar 배포 파일 만들기.
#   1) 아이콘 파일 만들기  2) PyInstaller 로 실행 폴더(dist\FlowCalendar)  3) Inno Setup 으로 설치 파일(dist\FlowCalendar-Setup-버전.exe)
# 사용:  powershell -File packaging\build.ps1            (설치 파일까지)
#        powershell -File packaging\build.ps1 -NoInstaller   (실행 폴더까지만)
param([switch]$NoInstaller)

$ErrorActionPreference = 'Continue'  # PyInstaller 가 진행 상황을 stderr 로 써도 오류로 보지 않는다. 실패는 종료 코드로 확인한다
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'

Write-Host '1/3 아이콘 만드는 중...'
& $python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw '아이콘을 만들지 못했습니다.' }

Write-Host '2/3 실행 폴더 만드는 중 (몇 분 걸립니다)...'
& $python -m PyInstaller packaging\flowcalendar.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 가 실패했습니다.' }
Write-Host "   -> $root\dist\FlowCalendar\FlowCalendar.exe"

if ($NoInstaller) { return }

Write-Host '3/3 설치 파일 만드는 중...'
$candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 가 없습니다. (winget install JRSoftware.InnoSetup)' }
& $iscc packaging\flowcalendar.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup 이 실패했습니다.' }
Write-Host '완료: dist 폴더를 확인하세요.'
