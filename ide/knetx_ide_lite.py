"""KnetX SoftPLC - IDE-lite (MVP) — Nuovo Progetto integrato

Adds:
- Toolbar action: "Nuovo progetto"
- Creates a minimal project skeleton (Init + Main, 1 sheet each) without using PowerShell.
- After creation, auto-opens the project.

Single-instance:
- Uses QtCore.QLockFile (per-user).

Build EXE (no console):
  pyinstaller --noconsole --onefile --name knetx_ide .\ide\knetx_ide_lite.py
"""

from __future__ import annotations

import json
import socket
import struct
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets


APP_NAME = "KnetX IDE-lite"
SCHEMA_VERSION_PROJECT = 1


# ----------------------------
# Runtime TCP client (framed JSON)
# ----------------------------

@dataclass
class RuntimeProfile:
    name: str
    host: str
    port: int


class RuntimeClient:
    def __init__(self) -> None:
        self.profile = RuntimeProfile("LocalSim", "127.0.0.1", 1963)

    def set_profile(self, p: RuntimeProfile) -> None:
        self.profile = p

    def _send_cmd(self, cmd: str, payload: Dict[str, Any], timeout_s: float = 0.7) -> Dict[str, Any]:
        msg = {"cmd": cmd, "req_id": 1, "payload": payload}
        raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        framed = struct.pack("<I", len(raw)) + raw

        with socket.create_connection((self.profile.host, self.profile.port), timeout=timeout_s) as s:
            s.sendall(framed)
            hdr = s.recv(4)
            if len(hdr) != 4:
                raise RuntimeError("Header incompleto")
            (ln,) = struct.unpack("<I", hdr)
            data = b""
            while len(data) < ln:
                chunk = s.recv(ln - len(data))
                if not chunk:
                    raise RuntimeError("Connessione chiusa")
                data += chunk
        return json.loads(data.decode("utf-8"))

    def ping(self) -> Tuple[bool, str]:
        try:
            r = self._send_cmd("PING", {})
            if not r.get("ok", False):
                return False, "OFFLINE"
            st = (r.get("payload") or {}).get("runtime_state", "?")
            return True, str(st)
        except Exception:
            return False, "OFFLINE"


# ----------------------------
# Project model + I/O
# ----------------------------

@dataclass
class Project:
    root: Path
    name: str
    project_json: Dict[str, Any]
    pages_json: Dict[str, Any]
    vars_json: Dict[str, Any]
    monitors_json: Dict[str, Any]


def load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, obj: Dict[str, Any]) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_project(folder: Path) -> Project:
    pj = load_json(folder / "project.json")
    pages = load_json(folder / "pages.json")
    varsj = load_json(folder / "vars.json")
    mon = load_json(folder / "monitors.json")
    name = str(pj.get("name", folder.name))
    return Project(root=folder, name=name, project_json=pj, pages_json=pages, vars_json=varsj, monitors_json=mon)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def st_sheet_template(pou_name: str, human_title: str) -> str:
    return (
        f"(* {human_title} — {pou_name} *)\n"
        f"FUNCTION_BLOCK {pou_name}\n"
        f"VAR\n"
        f"  (* locals here *)\n"
        f"END_VAR\n\n"
        f"(* user code here *)\n\n"
        f"END_FUNCTION_BLOCK\n"
    )


def st_wrapper_template(wrapper_name: str, sheet_pou_names: list[str]) -> str:
    decl = "\n".join([f"  fb_{n} : {n};" for n in sheet_pou_names])
    calls = "\n".join([f"fb_{n}();" for n in sheet_pou_names])
    return (
        "(* AUTO-GENERATED — DO NOT EDIT BY HAND *)\n"
        f"FUNCTION_BLOCK {wrapper_name}\n"
        "VAR\n"
        f"{decl}\n"
        "END_VAR\n\n"
        f"{calls}\n\n"
        "END_FUNCTION_BLOCK\n"
    )


def create_project_skeleton(out_dir: Path, name: str) -> None:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RuntimeError(f"Cartella non vuota: {out_dir}")

    ensure_dir(out_dir)
    ensure_dir(out_dir / "pages")
    ensure_dir(out_dir / "data")

    project = {
        "schema_version": SCHEMA_VERSION_PROJECT,
        "name": name,
        "created_utc": utc_now_iso(),
        "languages": ["ST"],
        "targets": {
            "localsim": {"host": "127.0.0.1", "port": 1963},
            "linux_runtime": {"host": "<set in IDE settings>", "port": 1963},
        },
        "memory": {"plc_bytes": 1048576, "retain_bytes": 65536},
    }

    pages = {
        "schema_version": 1,
        "init": {
            "id": "INIT",
            "name": "Init",
            "sheets": [
                {"id": "S001", "name": "Foglio1", "file": "pages/INIT/S001.st", "pou": "INIT_S001"}
            ],
        },
        "pages": [
            {
                "id": "P001",
                "name": "Main",
                "enabled": True,
                "sheets": [
                    {"id": "S001", "name": "Foglio1", "file": "pages/P001/S001.st", "pou": "P001_S001"}
                ],
            }
        ],
    }

    vars_json = {
        "schema_version": 1,
        "var_global": [],
        "types": {"builtins": ["BOOL", "BYTE", "INT", "UINT", "UDINT", "REAL"]},
    }

    monitors_json = {"schema_version": 1, "presets": []}

    write_json(out_dir / "project.json", project)
    write_json(out_dir / "pages.json", pages)
    write_json(out_dir / "vars.json", vars_json)
    write_json(out_dir / "monitors.json", monitors_json)

    init_dir = out_dir / "pages" / "INIT"
    p001_dir = out_dir / "pages" / "P001"
    ensure_dir(init_dir)
    ensure_dir(p001_dir)

    (init_dir / "S001.st").write_text(st_sheet_template("INIT_S001", "Init / Foglio1"), encoding="utf-8")
    (p001_dir / "S001.st").write_text(st_sheet_template("P001_S001", "Main / Foglio1"), encoding="utf-8")

    (out_dir / "pages" / "INIT.st").write_text(st_wrapper_template("INIT", ["INIT_S001"]), encoding="utf-8")
    (out_dir / "pages" / "P001.st").write_text(st_wrapper_template("P001", ["P001_S001"]), encoding="utf-8")


# ----------------------------
# UI
# ----------------------------

class SettingsWidget(QtWidgets.QWidget):
    profile_changed = QtCore.Signal(RuntimeProfile)

    def __init__(self) -> None:
        super().__init__()
        self.profiles = [
            RuntimeProfile("LocalSim", "127.0.0.1", 1963),
            RuntimeProfile("RaspberryRuntime", "192.168.0.10", 1963),
        ]

        self.cbo = QtWidgets.QComboBox()
        for p in self.profiles:
            self.cbo.addItem(p.name)

        self.ed_host = QtWidgets.QLineEdit(self.profiles[0].host)
        self.ed_port = QtWidgets.QSpinBox()
        self.ed_port.setRange(1, 65535)
        self.ed_port.setValue(self.profiles[0].port)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(6, 6, 6, 6)
        form.addRow("Profilo", self.cbo)
        form.addRow("Host/IP", self.ed_host)
        form.addRow("Porta", self.ed_port)
        self.setLayout(form)

        self.cbo.currentIndexChanged.connect(self.on_profile_sel)
        self.ed_host.editingFinished.connect(self.emit_changed)
        self.ed_port.valueChanged.connect(lambda _: self.emit_changed())

    def on_profile_sel(self, idx: int) -> None:
        p = self.profiles[idx]
        self.ed_host.setText(p.host)
        self.ed_port.setValue(p.port)
        self.emit_changed()

    def emit_changed(self) -> None:
        p = RuntimeProfile(self.cbo.currentText(), self.ed_host.text().strip(), int(self.ed_port.value()))
        self.profile_changed.emit(p)


class NewProjectDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nuovo progetto")

        self.ed_name = QtWidgets.QLineEdit("Demo2")
        self.ed_base = QtWidgets.QLineEdit(str(Path.home() / "SplKnetxProjects"))
        self.btn_pick = QtWidgets.QPushButton("...")
        self.btn_pick.setFixedWidth(28)

        row_base = QtWidgets.QHBoxLayout()
        row_base.addWidget(self.ed_base)
        row_base.addWidget(self.btn_pick)

        form = QtWidgets.QFormLayout()
        form.addRow("Nome progetto", self.ed_name)
        form.addRow("Cartella base", row_base)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addLayout(form)
        root.addWidget(btns)

        self.btn_pick.clicked.connect(self.pick_base)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

    def pick_base(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Scegli cartella base", self.ed_base.text())
        if d:
            self.ed_base.setText(d)

    def get_values(self) -> Tuple[str, Path]:
        name = self.ed_name.text().strip()
        base = Path(self.ed_base.text().strip()).expanduser().resolve()
        return name, base


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)

        self.project: Optional[Project] = None
        self.client = RuntimeClient()

        tb = QtWidgets.QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(16, 16))
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        act_new = QtGui.QAction("Nuovo progetto", self)
        act_open = QtGui.QAction("Apri progetto", self)
        act_settings = QtGui.QAction("Settings", self)
        act_connect = QtGui.QAction("Connetti", self)
        act_compile = QtGui.QAction("Compila", self)
        act_download = QtGui.QAction("Download", self)

        tb.addAction(act_new)
        tb.addAction(act_open)
        tb.addSeparator()
        tb.addAction(act_settings)
        tb.addAction(act_connect)
        tb.addSeparator()
        tb.addAction(act_compile)
        tb.addAction(act_download)

        act_new.triggered.connect(self.new_project)
        act_open.triggered.connect(self.open_project)
        act_settings.triggered.connect(lambda: self.tabs.setCurrentWidget(self.tab_settings))
        act_connect.triggered.connect(self.refresh_status)
        act_compile.triggered.connect(self.stub_compile)
        act_download.triggered.connect(self.stub_download)

        self.split = QtWidgets.QSplitter()
        self.split.setChildrenCollapsible(False)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setStyleSheet("QTreeWidget{font-size:11px;}")
        self.split.addWidget(self.tree)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.split.addWidget(self.tabs)

        self.setCentralWidget(self.split)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([220, 900])

        self.tab_pages = QtWidgets.QWidget()
        self.tab_settings = QtWidgets.QWidget()
        self.tab_output = QtWidgets.QWidget()

        self.tabs.addTab(self.tab_pages, "Pagine")
        self.tabs.addTab(self.tab_settings, "Settings")
        self.tabs.addTab(self.tab_output, "Output")

        self.pages_label = QtWidgets.QLabel("Apri o crea un progetto per vedere Pagine/Fogli.")
        self.pages_label.setStyleSheet("font-size:11px;")
        lay_pages = QtWidgets.QVBoxLayout(self.tab_pages)
        lay_pages.setContentsMargins(6, 6, 6, 6)
        lay_pages.addWidget(self.pages_label)
        lay_pages.addStretch(1)

        self.settings = SettingsWidget()
        lay_set = QtWidgets.QVBoxLayout(self.tab_settings)
        lay_set.setContentsMargins(0, 0, 0, 0)
        lay_set.addWidget(self.settings)
        lay_set.addStretch(1)
        self.settings.profile_changed.connect(self.on_profile_changed)

        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("font-size:11px;")
        lay_out = QtWidgets.QVBoxLayout(self.tab_output)
        lay_out.setContentsMargins(6, 6, 6, 6)
        lay_out.addWidget(self.output)

        self.lbl_status = QtWidgets.QLabel("OFFLINE")
        self.lbl_monitors = QtWidgets.QLabel("MONITORS: 0")
        self.btn_show_monitors = QtWidgets.QPushButton("Visualizza nascosti")
        self.btn_show_monitors.setEnabled(False)
        self.btn_show_monitors.setFixedHeight(22)

        sb = self.statusBar()
        sb.addWidget(self.lbl_status)
        sb.addPermanentWidget(self.lbl_monitors)
        sb.addPermanentWidget(self.btn_show_monitors)

        self.setStyleSheet(
            "QMainWindow{font-size:11px;}"
            "QToolBar{spacing:4px;}"
            "QToolButton{padding:2px 6px;}"
            "QTabBar::tab{padding:4px 8px; margin:1px;}"
            "QSplitter::handle{background:#ddd;}"
        )

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start()

        self.refresh_status()
        self.populate_tree_empty()

    def log(self, s: str) -> None:
        self.output.appendPlainText(s)

    def populate_tree_empty(self) -> None:
        self.tree.clear()
        root_vars = QtWidgets.QTreeWidgetItem(["Variabili"])
        root_pages = QtWidgets.QTreeWidgetItem(["Pagine"])
        root_bus = QtWidgets.QTreeWidgetItem(["Bus"])
        self.tree.addTopLevelItem(root_vars)
        self.tree.addTopLevelItem(root_pages)
        self.tree.addTopLevelItem(root_bus)
        root_vars.setExpanded(True)
        root_pages.setExpanded(True)

    def populate_tree_from_project(self) -> None:
        if not self.project:
            self.populate_tree_empty()
            return
        self.tree.clear()

        root_vars = QtWidgets.QTreeWidgetItem(["Variabili"])
        root_pages = QtWidgets.QTreeWidgetItem(["Pagine"])
        root_bus = QtWidgets.QTreeWidgetItem(["Bus"])
        self.tree.addTopLevelItem(root_vars)
        self.tree.addTopLevelItem(root_pages)
        self.tree.addTopLevelItem(root_bus)

        vlist = (self.project.vars_json.get("var_global") or [])
        for v in vlist:
            name = v.get("name", "?")
            vtype = v.get("type", "?")
            root_vars.addChild(QtWidgets.QTreeWidgetItem([f"{name} : {vtype}"]))

        init = self.project.pages_json.get("init")
        if init:
            it = QtWidgets.QTreeWidgetItem([f"Init ({init.get('name','Init')})"])
            root_pages.addChild(it)
            for sh in init.get("sheets", []):
                it.addChild(QtWidgets.QTreeWidgetItem([f"{sh.get('id')} - {sh.get('name')} (ST)"]))
        for p in self.project.pages_json.get("pages", []):
            pt = QtWidgets.QTreeWidgetItem([f"{p.get('id')} ({p.get('name')})"])
            root_pages.addChild(pt)
            for sh in p.get("sheets", []):
                pt.addChild(QtWidgets.QTreeWidgetItem([f"{sh.get('id')} - {sh.get('name')} (ST)"]))

        root_vars.setExpanded(True)
        root_pages.setExpanded(True)
        root_bus.setExpanded(True)

    def _open_project_path(self, folder: Path) -> None:
        self.project = load_project(folder)
        self.setWindowTitle(f"{APP_NAME} — {self.project.name}")
        self.populate_tree_from_project()
        self.pages_label.setText(f"Progetto aperto: {self.project.name}\n(placeholder editor ST/FBD)")
        self.log(f"OK: aperto progetto {self.project.root}")

    def new_project(self) -> None:
        dlg = NewProjectDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        name, base = dlg.get_values()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Nuovo progetto", "Nome progetto vuoto.")
            return

        out_dir = base / name
        try:
            ensure_dir(base)
            create_project_skeleton(out_dir, name)
            self.log(f"OK: creato progetto {out_dir}")
            self._open_project_path(out_dir)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    def open_project(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Seleziona cartella progetto")
        if not folder:
            return
        try:
            self._open_project_path(Path(folder))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    def on_profile_changed(self, p: RuntimeProfile) -> None:
        self.client.set_profile(p)
        self.log(f"Profilo runtime: {p.name} → {p.host}:{p.port}")
        self.refresh_status()

    def refresh_status(self) -> None:
        online, st = self.client.ping()
        if online:
            self.lbl_status.setText(f"ONLINE — {st}")
            self.lbl_status.setStyleSheet("color:#0a0; font-weight:600;")
        else:
            self.lbl_status.setText("OFFLINE")
            self.lbl_status.setStyleSheet("color:#777; font-weight:600;")

    def stub_compile(self) -> None:
        QtWidgets.QMessageBox.information(self, "Compila", "MVP: compilazione non ancora implementata.")

    def stub_download(self) -> None:
        QtWidgets.QMessageBox.information(self, "Download", "MVP: download/activate build non ancora implementato.")


# ----------------------------
# Single-instance lock
# ----------------------------

_lock_file: Optional[QtCore.QLockFile] = None


def acquire_ide_lock() -> bool:
    global _lock_file
    appdata = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppLocalDataLocation)
    p = Path(appdata)
    p.mkdir(parents=True, exist_ok=True)
    lock_path = str(p / "knetx_ide.lock")

    lf = QtCore.QLockFile(lock_path)
    lf.setStaleLockTime(5_000)
    ok = lf.tryLock(100)
    if ok:
        _lock_file = lf
        return True
    return False


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)

    if not acquire_ide_lock():
        QtWidgets.QMessageBox.information(None, APP_NAME, "IDE già in esecuzione (single-instance).")
        return 2

    w = MainWindow()
    w.resize(1080, 680)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
