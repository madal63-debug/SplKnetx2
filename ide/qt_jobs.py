from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6 import QtCore


class JobSignals(QtCore.QObject):
    ok = QtCore.Signal(object)
    err = QtCore.Signal(str)


class Job(QtCore.QRunnable):
    """Esegue fn(*args, **kwargs) su threadpool e ritorna in UI via signals."""

    def __init__(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = JobSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            res = self.fn(*self.args, **self.kwargs)
            self.signals.ok.emit(res)
        except Exception as e:
            self.signals.err.emit(str(e))


def run_job(
    fn: Callable[..., Any],
    *args: Any,
    on_ok: Optional[Callable[[Any], None]] = None,
    on_err: Optional[Callable[[str], None]] = None,
    **kwargs: Any,
) -> Job:
    """Lancia un job su QThreadPool e collega callback."""
    job = Job(fn, args=args, kwargs=kwargs)
    if on_ok:
        job.signals.ok.connect(on_ok)
    if on_err:
        job.signals.err.connect(on_err)
    QtCore.QThreadPool.globalInstance().start(job)
    return job