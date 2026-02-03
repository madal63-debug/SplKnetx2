# parte 10/10 — ide/knetx_ide_lite.py
# Entry point (quello che passi a PyInstaller)

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets

from ide.config import APP_NAME
from ide.main_window import MainWindow


# ----------------------------
# Single-instance lock
# ----------------------------
_lock_file: Optional[QtCore.QLockFile] = None


def acquire_ide_lock() -> bool:
    global _lock_file
    appdata = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppLocalDataLocation)
    p = Path(appdata)
    p.mkdir(parents=True, exist_ok=True)

    lf = QtCore.QLockFile(str(p / "knetx_ide.lock"))
    lf.setStaleLockTime(5_000)
    if lf.tryLock(100):
        _lock_file = lf
        return True
    return False


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setOrganizationName("SplKnetx")
    app.setApplicationName(APP_NAME)

    if not acquire_ide_lock():
        QtWidgets.QMessageBox.information(None, APP_NAME, "IDE già in esecuzione (single-instance).")
        return 2

    w = MainWindow()
    w.resize(1120, 740)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
