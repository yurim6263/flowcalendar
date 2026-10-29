"""단일 인스턴스. 이미 실행 중이면 그 창을 앞으로 가져오게 하고 두 번째 프로세스는 종료한다."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MESSAGE = b"show"


class SingleInstance(QObject):
    activated = Signal()  # 다른 프로세스가 "창을 보여 달라"고 요청했다

    def __init__(self, name: str, parent: QObject | None = None):
        super().__init__(parent)
        self.name = name
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """내가 첫 인스턴스면 True. 이미 실행 중이면 그쪽에 알리고 False."""
        if self._notify_running_instance():
            return False
        QLocalServer.removeServer(self.name)  # 비정상 종료로 남은 소켓 정리
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        return self._server.listen(self.name)

    def _notify_running_instance(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(300):
            return False
        socket.write(MESSAGE)
        socket.waitForBytesWritten(300)
        socket.waitForReadyRead(500)  # 첫 인스턴스의 확인 응답을 받고 끊는다 (바로 끊으면 요청이 유실될 수 있다)
        socket.disconnectFromServer()
        return True

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():  # 보내고 바로 끊은 경우 readyRead 는 이미 지나갔다
                self._read(socket)

    def _read(self, socket: QLocalSocket) -> None:
        if bytes(socket.readAll()) == MESSAGE:
            socket.write(b"ok")
            socket.flush()
            self.activated.emit()
