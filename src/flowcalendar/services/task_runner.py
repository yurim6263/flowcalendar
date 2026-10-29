"""오래 걸리는 일(AI 호출)을 별도 스레드에서 돌리고, 결과는 항상 화면(메인) 스레드에서 받는다.
AI 가 응답하는 동안 창이 멈추지 않게 하려는 것이다."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Job(QRunnable):
    def __init__(self, job_id: int, fn: Callable[[], Any], deliver: Signal):
        super().__init__()
        self.job_id, self.fn, self.deliver = job_id, fn, deliver

    def run(self) -> None:
        try:
            self.deliver.emit(self.job_id, True, self.fn())
        except BaseException as exc:  # noqa: BLE001 - 어떤 오류든 화면 쪽으로 넘겨 안내하게 한다
            self.deliver.emit(self.job_id, False, exc)


class TaskRunner(QObject):
    """run(fn, on_success, on_error): fn 은 작업 스레드에서, 두 콜백은 이 객체가 속한 스레드(메인)에서 불린다."""

    _deliver = Signal(int, bool, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._callbacks: dict[int, tuple[Callable, Callable]] = {}
        self._next_id = 0
        self._deliver.connect(self._handle)  # 받는 쪽이 메인 스레드 객체라서 자동으로 큐를 거친다

    def run(self, fn: Callable[[], Any], on_success: Callable[[Any], None], on_error: Callable[[BaseException], None]) -> int:
        self._next_id += 1
        self._callbacks[self._next_id] = (on_success, on_error)
        self._pool.start(_Job(self._next_id, fn, self._deliver))
        return self._next_id

    def _handle(self, job_id: int, ok: bool, payload: Any) -> None:
        callbacks = self._callbacks.pop(job_id, None)
        if callbacks is not None:
            callbacks[0 if ok else 1](payload)

    def wait(self, msec: int = 5000) -> bool:
        return self._pool.waitForDone(msec)


class ImmediateRunner:
    """테스트용: 같은 스레드에서 바로 실행한다."""

    def run(self, fn, on_success, on_error) -> int:
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001
            on_error(exc)
        else:
            on_success(result)
        return 0
