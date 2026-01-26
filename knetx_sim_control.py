"""KnetX SoftPLC - Sim Control GUI (Windows)

Minimal PySide6 GUI to control LocalSim runtime:
- Ensures single instance of LocalSim by checking if 127.0.0.1:1963 is already listening.
- Can launch LocalSim as a separate process (python knetx_runtime_sim.py).
- Can send commands: PING/GET_STATUS/START/STOP/SHUTDOWN.
- Heartbeat every 1s to show ONLINE/OFFLINE and RUN/STOP/ERROR.
- On closing this GUI: attempts graceful SHUTDOWN of LocalSim to avoid orphan instances.

Prereqs (venv): PySide6, pyserial (already installed).

Files expected in the same folder:
- knetx_runtime_sim.py   (Software/1)

Run:
  python knetx_sim_control.py
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

from PySide6 import QtCore, QtWidgets


HOST = "127.0.0.1"
PORT = 1963


# ----------------------------
# TCP framed JSON client
# ----------------------------

def _send_cmd(host: str, port: int, cmd: str, payload: Dict[str, Any], timeout_s: float = 1.0) -> Dict[str, Any]:
    msg = {"cmd": cmd, "req_id": 1, "payload": payload}
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    framed = struct.pack("<I", len(raw)) + raw

    with socket.create_connection((host, port), timeout=timeout_s) as s:
        s.sendall(framed)

        # Read response header
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
    """Returns (online, runtime_state, uptime_ms)."""
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

    def start(self, python_exe: str, script_path: Path) -> None:
        if self.is_running():
            return

        if not script_path.exists():
            raise FileNotFoundError(f"Manca il file: {script_path}")

        logs_dir = script_path.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = logs_dir / "localsim.log"

        # Redirect stdout/stderr to a file, so we don't spawn extra consoles.
        # This keeps it "processo separato" but controllato dall'IDE.
        lf = open(self.log_file, "a", encoding="utf-8")

        cmd = [python_exe, str(script_path), "--host", HOST, "--port", str(PORT), "--log", "INFO"]

        # CREATE_NO_WINDOW avoids console popups on Windows
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self.popen = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=lf,
            cwd=str(script_path.parent),
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
        self.base_dir = Path(__file__).resolve().parent
        self.localsim_script = self.base_dir / "knetx_runtime_sim.py"

        # Widgets
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

        # Layout (minimal)
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

        # Connections
        self.btn_start_sim.clicked.connect(self.on_start_sim)
        self.btn_shutdown_sim.clicked.connect(self.on_shutdown_sim)
        self.btn_run.clicked.connect(self.on_run)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_open_log.clicked.connect(self.on_open_log)

        # Heartbeat timer
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

        # Initial refresh
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

        # Enable/disable buttons
        self.btn_shutdown_sim.setEnabled(online)
        self.btn_run.setEnabled(online)
        self.btn_stop.setEnabled(online)

    def on_start_sim(self) -> None:
        # If already online, do nothing (single-instance)
        online, _, _ = ping_status()
        if online:
            return

        try:
            self.proc.start(python_exe=sys.executable, script_path=self.localsim_script)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))
            return

        # Wait briefly for server to come up
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
            # If it doesn't respond, fallback: if we own the process, terminate
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
            # Open with default associated app
            QtGui = __import__("PySide6.QtGui", fromlist=["QtGui"]).QtGui
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.proc.log_file)))
        else:
            QtWidgets.QMessageBox.information(self, "Log", "Nessun log disponibile (avvia Sim prima).")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Default safety: if LocalSim is running, shut it down so no orphan instances remain.
        online, _, _ = ping_status()
        if online:
            try:
                _send_cmd(HOST, PORT, "SHUTDOWN", {}, timeout_s=1.0)
            except Exception:
                if self.proc.is_running():
                    self.proc.stop_force()
        super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    w = SimControlWindow()
    w.setFixedHeight(110)
    w.resize(520, 110)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
