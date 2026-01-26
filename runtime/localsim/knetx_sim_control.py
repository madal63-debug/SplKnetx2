"""KnetX SoftPLC - Sim Control GUI (EXE-ready) — single-instance robust

Fix:
- Enforce ONE Sim Control instance (per-user) using QtCore.QLockFile.
- In EXE mode, it launches knetx_runtime_sim.exe from the same folder.
- In DEV mode, it launches knetx_runtime_sim.py from the same folder.

Build EXE (no console):
  pyinstaller --noconsole --onefile --name knetx_sim_control .\runtime\localsim\knetx_sim_control.py
"""

from __future__ import annotations

import json
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets


HOST = "127.0.0.1"
PORT = 1963


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# ----------------------------
# TCP framed JSON client
# ----------------------------

def _send_cmd(host: str, port: int, cmd: str, payload: Dict[str, Any], timeout_s: float = 1.0) -> Dict[str, Any]:
    msg = {"cmd": cmd, "req_id": 1, "payload": payload}
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    framed = struct.pack("<I", len(raw)) + raw

    with socket.create_connection((host, port), timeout=timeout_s) as s:
        s.sendall(framed)
        hdr = s.recv(4)
        if len(hdr) != 4:
            raise RuntimeError("Header incompleto")
        (ln,) = struct.unpack("<I", hdr)
        if ln <= 0 or ln > 10_000_000:
            raise RuntimeError(f"Lunghezza risposta non valida: {ln}")

        data = b""
        while len(data) < ln:
            chunk = s.recv(ln - len(data))
            if not chunk:
                raise RuntimeError("Connessione chiusa")
            data += chunk

    return json.loads(data.decode("utf-8"))


def ping_status() -> Tuple[bool, str, int]:
    try:
        resp = _send_cmd(HOST, PORT, "PING", {}, timeout_s=0.5)
        if not resp.get("ok", False):
            return False, "OFFLINE", 0
        payload = resp.get("payload", {}) or {}
        return True, str(payload.get("runtime_state", "?")), int(payload.get("uptime_ms", 0))
    except Exception:
        return False, "OFFLINE", 0


# ----------------------------
# LocalSim process manager
# ----------------------------

@dataclass
class LocalSimProcess:
    popen: Optional[subprocess.Popen] = None
    log_file: Optional[Path] = None

    def is_running(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def start(self) -> None:
        if self.is_running():
            return

        bdir = base_dir()
        logs_dir = bdir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = logs_dir / "localsim.log"

        lf = open(self.log_file, "a", encoding="utf-8")

        if is_frozen():
            localsim_exe = bdir / "knetx_runtime_sim.exe"
            if not localsim_exe.exists():
                raise FileNotFoundError(f"Manca {localsim_exe}. Metti knetx_runtime_sim.exe nella stessa cartella.")
            cmd = [str(localsim_exe), "--host", HOST, "--port", str(PORT), "--log", "INFO"]
            cwd = str(bdir)
        else:
            script = bdir / "knetx_runtime_sim.py"
            if not script.exists():
                raise FileNotFoundError(f"Manca il file: {script}")
            cmd = [sys.executable, str(script), "--host", HOST, "--port", str(PORT), "--log", "INFO"]
            cwd = str(bdir)

        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self.popen = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=lf,
            cwd=cwd,
            creationflags=creationflags,
        )

    def stop_force(self) -> None:
        if self.popen is None:
            return
        try:
            self.popen.terminate()
        except Exception:
            pass


# ----------------------------
# UI
# ----------------------------

class SimControlWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KnetX LocalSim Control")

        self.proc = LocalSimProcess()

        self.led = QtWidgets.QLabel(" ")
        self.led.setFixedSize(12, 12)
        self.led.setStyleSheet("border: 1px solid #777; border-radius: 6px; background: #888;")

        self.lbl_online = QtWidgets.QLabel("OFFLINE")
        self.lbl_state = QtWidgets.QLabel("STATE: ?")
        self.lbl_uptime = QtWidgets.QLabel("Uptime: 0 ms")

        self.btn_start_sim = QtWidgets.QPushButton("Start Sim")
        self.btn_shutdown_sim = QtWidgets.QPushButton("Shutdown Sim")
        self.btn_run = QtWidgets.QPushButton("RUN")
        self.btn_stop = QtWidgets.QPushButton("STOP")
        self.btn_open_log = QtWidgets.QPushButton("Apri log")

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.led)
        top.addWidget(self.lbl_online)
        top.addStretch(1)
        top.addWidget(self.lbl_state)

        mid = QtWidgets.QHBoxLayout()
        mid.addWidget(self.lbl_uptime)
        mid.addStretch(1)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_start_sim)
        row.addWidget(self.btn_shutdown_sim)
        row.addSpacing(10)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_stop)
        row.addStretch(1)
        row.addWidget(self.btn_open_log)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.addLayout(top)
        root.addLayout(mid)
        root.addLayout(row)

        self.btn_start_sim.clicked.connect(self.on_start_sim)
        self.btn_shutdown_sim.clicked.connect(self.on_shutdown_sim)
        self.btn_run.clicked.connect(self.on_run)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_open_log.clicked.connect(self.on_open_log)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

        self.refresh()

    def set_led(self, online: bool) -> None:
        if online:
            self.led.setStyleSheet("border: 1px solid #555; border-radius: 6px; background: #2ecc71;")
            self.lbl_online.setText("ONLINE")
        else:
            self.led.setStyleSheet("border: 1px solid #777; border-radius: 6px; background: #888;")
            self.lbl_online.setText("OFFLINE")

    def refresh(self) -> None:
        online, state, uptime = ping_status()
        self.set_led(online)
        self.lbl_state.setText(f"STATE: {state}")
        self.lbl_uptime.setText(f"Uptime: {uptime} ms")

        self.btn_shutdown_sim.setEnabled(online)
        self.btn_run.setEnabled(online)
        self.btn_stop.setEnabled(online)

    def on_start_sim(self) -> None:
        online, _, _ = ping_status()
        if online:
            return

        try:
            self.proc.start()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))
            return

        t0 = time.time()
        while time.time() - t0 < 2.0:
            online, _, _ = ping_status()
            if online:
                break
            QtCore.QThread.msleep(80)
        self.refresh()

    def on_shutdown_sim(self) -> None:
        try:
            _send_cmd(HOST, PORT, "SHUTDOWN", {}, timeout_s=1.0)
        except Exception:
            if self.proc.is_running():
                self.proc.stop_force()
        self.refresh()

    def on_run(self) -> None:
        try:
            _send_cmd(HOST, PORT, "START", {}, timeout_s=1.0)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Avviso", str(e))
        self.refresh()

    def on_stop(self) -> None:
        try:
            _send_cmd(HOST, PORT, "STOP", {}, timeout_s=1.0)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Avviso", str(e))
        self.refresh()

    def on_open_log(self) -> None:
        if self.proc.log_file and self.proc.log_file.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.proc.log_file)))
        else:
            QtWidgets.QMessageBox.information(self, "Log", "Nessun log disponibile (avvia Sim prima).")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        online, _, _ = ping_status()
        if online:
            try:
                _send_cmd(HOST, PORT, "SHUTDOWN", {}, timeout_s=1.0)
            except Exception:
                if self.proc.is_running():
                    self.proc.stop_force()
        super().closeEvent(event)


_lock_file: Optional[QtCore.QLockFile] = None


def acquire_sim_lock() -> bool:
    global _lock_file
    appdata = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppLocalDataLocation)
    p = Path(appdata)
    p.mkdir(parents=True, exist_ok=True)
    lock_path = str(p / "knetx_sim_control.lock")

    lf = QtCore.QLockFile(lock_path)
    lf.setStaleLockTime(5_000)
    ok = lf.tryLock(100)
    if ok:
        _lock_file = lf
        return True
    return False


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)

    if not acquire_sim_lock():
        QtWidgets.QMessageBox.information(None, "KnetX Sim Control", "Sim Control già in esecuzione (single-instance).")
        return 2

    w = SimControlWindow()
    w.setFixedHeight(110)
    w.resize(520, 110)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
