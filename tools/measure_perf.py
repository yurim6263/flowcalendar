"""성능 측정: 처음 켜는 시간, 월 이동 시간, 메모리.

측정 방법
  - 내 데이터를 건드리지 않도록 임시 폴더에 가짜 데이터(일정 약 450건, 할 일 약 160개, 메모)를 만들어 FLOWCALENDAR_DATA_DIR 로 지정한다.
  - 앱을 `--benchmark` 로 실행한다. 첫 화면이 실제로 그려지면 앱이 표시 파일을 만들고, 이 도구는 프로세스를 시작한 순간부터
    그 파일이 생길 때까지의 시계 시간을 잰다(파이썬/Qt 불러오기, 창 만들기, 첫 그리기까지 모두 포함).
  - 이어서 앱이 다음 달로 24번 이동하며 한 번 이동 + 화면 다시 그리기에 걸린 시간을 잰다.
  - 표시 파일이 생겼을 때와 월 이동이 끝났을 때, 그 프로세스의 메모리(작업 집합 / 전용)를 읽는다.
  - 같은 실행을 여러 번 반복해 가장 느린 것과 가운데 값을 보고한다. 첫 번째 실행은 디스크 캐시가 차갑다.

사용:  .venv\\Scripts\\python.exe tools\\measure_perf.py [--exe dist\\FlowCalendar\\FlowCalendar.exe] [--runs 6] [--empty]
"""

import argparse
import ctypes
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


class _Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def memory_mb(pid: int) -> tuple[float, float] | None:
    """(작업 집합 MB, 전용 MB). 작업 관리자의 '메모리'는 전용 메모리에 가깝다."""
    handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, pid)  # QUERY_LIMITED_INFORMATION | QUERY_INFORMATION
    if not handle:
        return None
    try:
        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return (counters.WorkingSetSize / 2**20, counters.PrivateUsage / 2**20) if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def seed(data_dir: Path) -> dict:
    """현실적인 양의 가짜 데이터를 넣는다."""
    from flowcalendar.data import db
    from flowcalendar.data.memo_repo import MemoRepository
    from flowcalendar.data.schedule_repo import ScheduleRepository
    from flowcalendar.data.todo_repo import TodoRepository
    from flowcalendar.domain.models import COLORS, Schedule, Todo

    rng = random.Random(7)
    conn = db.connect(data_dir / db.DB_FILE_NAME)
    schedules, todos = ScheduleRepository(conn), TodoRepository(conn)
    today = date.today()
    counts = {"schedules": 0, "todos": 0}
    for i in range(420):
        day = today + timedelta(days=rng.randint(-200, 400))
        start = datetime.combine(day, datetime.min.time()) + timedelta(hours=rng.randint(7, 20))
        span = rng.choice([0, 0, 0, 0, 0, 1, 2, 4])
        schedules.add(Schedule(f"일정 {i} 팀 회의와 준비", start, start + timedelta(days=span, hours=1),
                               color=rng.choice(COLORS), remind_before_min=rng.choice([None, 10, 30])))
        counts["schedules"] += 1
    for i, rule in enumerate(["daily", "weekly", "monthly"] * 10):
        start = datetime.combine(today - timedelta(days=rng.randint(0, 60)), datetime.min.time()) + timedelta(hours=9)
        schedules.add(Schedule(f"반복 {i}", start, start + timedelta(hours=1), color=rng.choice(COLORS), recurrence=rule))
        counts["schedules"] += 1
    for i in range(160):
        day = today + timedelta(days=rng.randint(-20, 40)) if i % 4 else None
        todos.add(Todo(f"할 일 {i} 보고서 정리", day=day))
        counts["todos"] += 1
    MemoRepository(conn).set("\n".join(f"메모 줄 {i}" for i in range(30)))
    conn.close()
    return counts


def one_run(command: list[str], data_dir: Path) -> dict:
    out = data_dir / "bench.json"
    for leftover in (out, Path(str(out) + ".ready")):
        leftover.unlink(missing_ok=True)
    env = dict(os.environ, FLOWCALENDAR_DATA_DIR=str(data_dir), FLOWCALENDAR_BENCH_OUT=str(out))
    begin = time.perf_counter()
    proc = subprocess.Popen(command, env=env, cwd=str(ROOT))
    result: dict = {}
    mem_ready = None
    deadline = begin + 60
    while time.perf_counter() < deadline and not out.exists():
        if mem_ready is None and Path(str(out) + ".ready").exists():
            result["start_ms"] = round((time.perf_counter() - begin) * 1000)
            mem_ready = memory_mb(proc.pid)
        if proc.poll() is not None:
            break
        time.sleep(0.005)
    mem_end = memory_mb(proc.pid)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    if out.exists():
        result.update(json.loads(out.read_text(encoding="utf-8")))
    result["mem_ready"] = mem_ready
    result["mem_end"] = mem_end
    return result


def summarize(label: str, runs: list[dict]) -> None:
    starts = [r["start_ms"] for r in runs if "start_ms" in r]
    warm = starts[1:] or starts
    navs_avg = [r["nav_avg_ms"] for r in runs if "nav_avg_ms" in r]
    navs_max = [r["nav_max_ms"] for r in runs if "nav_max_ms" in r]
    mem_end = [r["mem_end"] for r in runs if r.get("mem_end")]
    print(f"\n== {label} ==")
    print(f"처음 켜기(프로세스 시작 -> 첫 화면): 첫 실행 {starts[0]} ms | 이후 가운데 {int(statistics.median(warm))} ms, "
          f"가장 느림 {max(warm)} ms  (목표 2000 ms)")
    print(f"월 이동 1회(이동 + 다시 그리기): 평균 {statistics.mean(navs_avg):.1f} ms, 가장 느린 이동 {max(navs_max):.1f} ms  (목표 100 ms)")
    mem_end = [m for m in mem_end if m[0] > 30]  # 가상환경의 python.exe 는 실제 앱을 자식으로 띄우는 작은 실행기라 메모리가 아주 작게 읽힌다
    if mem_end:
        print(f"메모리(월 이동 뒤): 작업 집합 {statistics.median(m[0] for m in mem_end):.0f} MB, "
              f"전용 {statistics.median(m[1] for m in mem_end):.0f} MB")
    print(f"백엔드: keyring={runs[-1].get('keyring_backend')}, 묶은 실행 파일={runs[-1].get('frozen')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", help="묶은 FlowCalendar.exe 경로 (없으면 개발 환경의 python -m flowcalendar 를 잰다)")
    parser.add_argument("--runs", type=int, default=6)
    parser.add_argument("--empty", action="store_true", help="가짜 데이터 없이 빈 상태로 잰다 (처음 설치한 사람의 모습)")
    args = parser.parse_args()

    data_dir = Path(tempfile.mkdtemp(prefix="flowcalendar-bench-"))
    try:
        if args.empty:
            from flowcalendar.data import db

            db.connect(data_dir / db.DB_FILE_NAME).close()
            print(f"측정용 데이터: 비어 있음 ({data_dir})")
        else:
            counts = seed(data_dir)
            print(f"측정용 데이터: 일정 {counts['schedules']}건(반복 30 포함), 할 일 {counts['todos']}개 ({data_dir})")
        if args.exe:
            exe = str(Path(args.exe).resolve())
            command, label = [exe, "--benchmark"], f"묶은 실행 파일 ({exe})"
        else:
            command = [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "flowcalendar", "--benchmark"]
            label = "개발 환경 (python -m flowcalendar)"
        runs = [one_run(command, data_dir) for _ in range(args.runs)]
        for i, r in enumerate(runs, 1):
            print(f"  실행 {i}: 시작 {r.get('start_ms')} ms, 이동 평균 {r.get('nav_avg_ms')} / 최대 {r.get('nav_max_ms')} ms")
        summarize(label, runs)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
