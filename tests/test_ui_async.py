from PySide6.QtCore import QCoreApplication, QEventLoop, QThreadPool, QTimer

from app.ui.main_window import MainWindow


class AsyncHarness:
    """Minimal state needed to exercise MainWindow._run_async without a GUI."""

    def __init__(self) -> None:
        self.thread_pool = QThreadPool()
        self._active_workers = set()

    @staticmethod
    def _task_error(description: str, message: str, trace: str) -> None:
        raise AssertionError(f"{description}: {message}\n{trace}")


def test_async_worker_is_retained_until_queued_result_is_delivered() -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    harness = AsyncHarness()
    loop = QEventLoop()
    results: list[str] = []
    timed_out = False

    def timeout() -> None:
        nonlocal timed_out
        timed_out = True
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(timeout)
    timer.start(3000)
    MainWindow._run_async(
        harness,
        lambda: "0x0000",
        results.append,
        description="Prueba asíncrona",
        on_finished=loop.quit,
    )
    loop.exec()

    assert not timed_out
    assert results == ["0x0000"]
    assert harness._active_workers == set()
    harness.thread_pool.waitForDone()
    application.processEvents()
