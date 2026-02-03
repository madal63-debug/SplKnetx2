# parte 1/3 — v6
# --- knetx_ide_lite.py ---
from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

APP_NAME = "KnetX IDE-lite v6"
SCHEMA_VERSION_PROJECT = 1

# Tree item data roles
ROLE_FILE = int(QtCore.Qt.UserRole)
ROLE_PAGE_ID = int(QtCore.Qt.UserRole + 1)
ROLE_PAGE_NAME = int(QtCore.Qt.UserRole + 2)
ROLE_SHEET_INDEX0 = int(QtCore.Qt.UserRole + 3)
ROLE_NODE_KIND = int(QtCore.Qt.UserRole + 10)  # 'PAGES_ROOT' | 'PAGE' | 'SHEET'

# Editor defaults (richieste Mario)
CODE_FONT_FAMILY = "Verdana"
CODE_FONT_SIZE_PT = 8
LINE_NUMBER_GAP_CM = 0.5
LINE_SPACING_PCT = 200  # 200% (doppia)


# ----------------------------
# Helpers
# ----------------------------
def default_projects_dir() -> Path:
    candidates = [
        Path(r"C:\\SplKnetx\\projects"),
        (Path.cwd() / "projects"),
        (Path(__file__).resolve().parent.parent / "projects"),
        (Path.home() / "SplKnetxProjects"),
    ]
    for c in candidates:
        try:
            if c.exists() and c.is_dir():
                return c
        except Exception:
            continue
    return Path.home()


def folder_effectively_empty(p: Path) -> bool:
    if not p.exists() or not p.is_dir():
        return True
    ignore = {"desktop.ini", "thumbs.db"}
    for x in p.iterdir():
        if x.name.lower() in ignore:
            continue
        return False
    return True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, obj: Dict[str, Any]) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def next_page_id(pages_json: Dict[str, Any]) -> str:
    mx = 0
    for p in pages_json.get("pages", []):
        pid = str(p.get("id", ""))
        if pid.startswith("P"):
            try:
                mx = max(mx, int(pid[1:]))
            except Exception:
                pass
    return f"P{mx + 1:03d}"


def make_fbd_placeholder(page_id: str, sheet_id: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "FBD",
        "page_id": page_id,
        "sheet_id": sheet_id,
        "blocks": [],
        "wires": [],
        "meta": {"created_utc": utc_now_iso()},
    }


def rewrite_st_pou(file_path: Path, new_pou: str) -> None:
    """Replace FUNCTION_BLOCK name with new_pou (keep user body)."""
    txt = file_path.read_text(encoding="utf-8", errors="replace")
    lines = txt.splitlines(True)
    out: list[str] = []
    done = False
    for ln in lines:
        if not done and ln.strip().upper().startswith("FUNCTION_BLOCK "):
            out.append(f"FUNCTION_BLOCK {new_pou}\n")
            done = True
        else:
            out.append(ln)
    file_path.write_text("".join(out), encoding="utf-8")


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


def apply_line_spacing(editor: QtWidgets.QPlainTextEdit) -> None:
    """Applica interlinea (se supportata) senza crash su diverse versioni PySide."""
    try:
        lht = getattr(QtGui.QTextBlockFormat, "LineHeightTypes", None)
        if lht is not None:
            typ = lht.ProportionalHeight
        else:
            typ = getattr(QtGui.QTextBlockFormat, "ProportionalHeight", None)
        if typ is None:
            return

        fmt = QtGui.QTextBlockFormat()
        # signature: setLineHeight(height:int, heightType:LineHeightTypes)
        fmt.setLineHeight(int(LINE_SPACING_PCT), typ)

        doc = editor.document()
        cur = QtGui.QTextCursor(doc)
        cur.beginEditBlock()
        cur.select(QtGui.QTextCursor.Document)
        cur.mergeBlockFormat(fmt)
        cur.endEditBlock()

        c2 = editor.textCursor()
        c2.mergeBlockFormat(fmt)
        editor.setTextCursor(c2)
    except Exception:
        # Se qualcosa non va, semplicemente non applico interlinea
        pass


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
# Project model
# ----------------------------
@dataclass
class Project:
    root: Path
    name: str
    project_json: Dict[str, Any]
    pages_json: Dict[str, Any]
    vars_json: Dict[str, Any]
    monitors_json: Dict[str, Any]


def load_project(folder: Path) -> Project:
    pj = load_json(folder / "project.json")
    pages = load_json(folder / "pages.json")
    varsj = load_json(folder / "vars.json")
    mon = load_json(folder / "monitors.json")
    name = str(pj.get("name", folder.name))
    return Project(root=folder, name=name, project_json=pj, pages_json=pages, vars_json=varsj, monitors_json=mon)


def create_project_skeleton(out_dir: Path, name: str) -> None:
    if out_dir.exists() and not folder_effectively_empty(out_dir):
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

    # Default: 2 fogli per pagina
    pages = {
        "schema_version": 1,
        "init": {
            "id": "INIT",
            "name": "Init",
            "sheets": [
                {"id": "S001", "name": "Foglio1", "file": "pages/INIT/S001.st", "pou": "INIT_S001"},
                {"id": "S002", "name": "Foglio2", "file": "pages/INIT/S002.st", "pou": "INIT_S002"},
            ],
        },
        "pages": [
            {
                "id": "P001",
                "name": "Main",
                "enabled": True,
                "language": "ST",
                "sheets": [
                    {"id": "S001", "name": "Foglio1", "file": "pages/P001/S001.st", "pou": "P001_S001"},
                    {"id": "S002", "name": "Foglio2", "file": "pages/P001/S002.st", "pou": "P001_S002"},
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

    (init_dir / "S001.st").write_text(st_sheet_template("INIT_S001", "Init"), encoding="utf-8")
    (init_dir / "S002.st").write_text(st_sheet_template("INIT_S002", "Init"), encoding="utf-8")

    (p001_dir / "S001.st").write_text(st_sheet_template("P001_S001", "Main"), encoding="utf-8")
    (p001_dir / "S002.st").write_text(st_sheet_template("P001_S002", "Main"), encoding="utf-8")

    (out_dir / "pages" / "INIT.st").write_text(st_wrapper_template("INIT", ["INIT_S001", "INIT_S002"]), encoding="utf-8")
    (out_dir / "pages" / "P001.st").write_text(st_wrapper_template("P001", ["P001_S001", "P001_S002"]), encoding="utf-8")


def add_page_to_project(project: Project, page_name: str, language: str) -> str:
    language = (language or "ST").upper()
    if language not in {"ST", "FBD"}:
        language = "ST"

    pages_json = project.pages_json
    pid = next_page_id(pages_json)

    ensure_dir(project.root / "pages" / pid)

    if language == "ST":
        sheets = [
            {"id": "S001", "name": "Foglio1", "file": f"pages/{pid}/S001.st", "pou": f"{pid}_S001"},
            {"id": "S002", "name": "Foglio2", "file": f"pages/{pid}/S002.st", "pou": f"{pid}_S002"},
        ]
        (project.root / sheets[0]["file"]).write_text(st_sheet_template(sheets[0]["pou"], page_name), encoding="utf-8")
        (project.root / sheets[1]["file"]).write_text(st_sheet_template(sheets[1]["pou"], page_name), encoding="utf-8")
        (project.root / "pages" / f"{pid}.st").write_text(
            st_wrapper_template(pid, [sheets[0]["pou"], sheets[1]["pou"]]), encoding="utf-8"
        )
    else:
        sheets = [
            {"id": "S001", "name": "Foglio1", "file": f"pages/{pid}/S001.fbd.json"},
            {"id": "S002", "name": "Foglio2", "file": f"pages/{pid}/S002.fbd.json"},
        ]
        write_json(project.root / sheets[0]["file"], make_fbd_placeholder(pid, "S001"))
        write_json(project.root / sheets[1]["file"], make_fbd_placeholder(pid, "S002"))

    page_entry: Dict[str, Any] = {"id": pid, "name": page_name, "enabled": True, "language": language, "sheets": sheets}
    pages_json.setdefault("pages", []).append(page_entry)
    write_json(project.root / "pages.json", pages_json)
    project.pages_json = load_json(project.root / "pages.json")
    return pid


# ----------------------------
# Dialogs
# ----------------------------
class ProjectPickerDialog(QtWidgets.QDialog):
    def __init__(self, base_dir: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apri progetto")
        self.setModal(True)
        self._selected: Optional[Path] = None

        self.ed_base = QtWidgets.QLineEdit(str(base_dir))
        self.btn_browse = QtWidgets.QPushButton("...")
        self.btn_browse.setFixedWidth(28)
        self.btn_refresh = QtWidgets.QPushButton("Aggiorna")

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Cartella progetti:"))
        top.addWidget(self.ed_base)
        top.addWidget(self.btn_browse)
        top.addWidget(self.btn_refresh)

        self.list = QtWidgets.QListWidget()
        self.list.setStyleSheet("font-size:11px;")

        hint = QtWidgets.QLabel("Doppio click su un progetto per aprirlo")
        hint.setStyleSheet("color:#666; font-size:11px;")

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addLayout(top)
        root.addWidget(self.list, 1)
        root.addWidget(hint)
        root.addWidget(btns)

        btns.rejected.connect(self.reject)
        self.btn_browse.clicked.connect(self.browse)
        self.btn_refresh.clicked.connect(self.refresh)
        self.list.itemDoubleClicked.connect(self.on_double)

        self.refresh()

    def browse(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Scegli cartella progetti", self.ed_base.text())
        if d:
            self.ed_base.setText(d)
            self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        base = Path(self.ed_base.text().strip()).expanduser()
        if not base.exists() or not base.is_dir():
            self.list.addItem("(cartella non valida)")
            return

        projects: list[tuple[str, Path]] = []
        for sub in sorted(base.iterdir()):
            if not sub.is_dir():
                continue
            pj = sub / "project.json"
            if pj.exists():
                display = sub.name
                try:
                    name = str(load_json(pj).get("name", sub.name))
                    if name and name != sub.name:
                        display = f"{name}  ({sub.name})"
                except Exception:
                    pass
                projects.append((display, sub))

        if not projects:
            self.list.addItem("(nessun progetto trovato)")
            return

        for display, path in projects:
            it = QtWidgets.QListWidgetItem(display)
            it.setData(QtCore.Qt.UserRole, str(path))
            self.list.addItem(it)

    def on_double(self, item: QtWidgets.QListWidgetItem) -> None:
        p = item.data(QtCore.Qt.UserRole)
        if not p:
            return
        path = Path(str(p))
        if (path / "project.json").exists():
            self._selected = path
            self.accept()

    def selected_folder(self) -> Optional[Path]:
        return self._selected


class NewProjectDialog(QtWidgets.QDialog):
    def __init__(self, default_base: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nuovo progetto")

        self.ed_name = QtWidgets.QLineEdit("Demo")
        self.ed_base = QtWidgets.QLineEdit(str(default_base))
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


class AddPageDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aggiungi pagina")

        self.ed_name = QtWidgets.QLineEdit("Nuova Pagina")
        self.ed_name.setFocus()
        self.ed_name.selectAll()

        self.rb_st = QtWidgets.QRadioButton("ST")
        self.rb_fbd = QtWidgets.QRadioButton("FBD")
        self.rb_st.setChecked(True)

        row_lang = QtWidgets.QHBoxLayout()
        row_lang.addWidget(self.rb_st)
        row_lang.addWidget(self.rb_fbd)
        row_lang.addStretch(1)

        form = QtWidgets.QFormLayout()
        form.addRow("Nome pagina", self.ed_name)
        form.addRow("Linguaggio", row_lang)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addLayout(form)
        root.addWidget(btns)

        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

    def get_values(self) -> Tuple[str, str]:
        name = self.ed_name.text().strip()
        lang = "ST" if self.rb_st.isChecked() else "FBD"
        return name, lang


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


# ----------------------------
# ST editor with line numbers
# ----------------------------
class LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor: "StEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self._editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        self._editor.lineNumberAreaPaintEvent(event)


class StEditor(QtWidgets.QPlainTextEdit):
    def __init__(self, file_path: Path) -> None:
        super().__init__()
        self.file_path = file_path
        self._dirty = False

        f = QtGui.QFont(CODE_FONT_FAMILY, CODE_FONT_SIZE_PT)
        self.setFont(f)
        self.document().setDefaultFont(f)

        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setTabStopDistance(4 * QtGui.QFontMetrics(self.font()).horizontalAdvance(" "))

        self.textChanged.connect(self._on_changed)

        self._ln_area = LineNumberArea(self)
        self._ln_area.setFont(self.font())

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()

        self.load_from_disk()

    def _gap_px(self) -> int:
        dpi = float(self.logicalDpiX() or 96.0)
        return int((LINE_NUMBER_GAP_CM * dpi) / 2.54)

    def _on_changed(self) -> None:
        self._dirty = True

    def is_dirty(self) -> bool:
        return self._dirty

    def load_from_disk(self) -> None:
        txt = self.file_path.read_text(encoding="utf-8", errors="replace")
        self.blockSignals(True)
        self.setPlainText(txt)
        apply_line_spacing(self)
        self.blockSignals(False)
        self._dirty = False

    def save_to_disk(self) -> None:
        self.file_path.write_text(self.toPlainText(), encoding="utf-8")
        self._dirty = False

    def lineNumberAreaWidth(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        fm = self.fontMetrics()
        return 8 + fm.horizontalAdvance("9") * digits

    def updateLineNumberAreaWidth(self, _newBlockCount: int) -> None:
        self.setViewportMargins(self.lineNumberAreaWidth() + self._gap_px(), 0, 0, 0)

    def updateLineNumberArea(self, rect: QtCore.QRect, dy: int) -> None:
        if dy:
            self._ln_area.scroll(0, dy)
        else:
            self._ln_area.update(0, rect.y(), self._ln_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._ln_area.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaPaintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self._ln_area)
        painter.fillRect(event.rect(), QtGui.QColor(245, 245, 245))
        painter.setPen(QtGui.QColor(120, 120, 120))

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                h = int(self.blockBoundingRect(block).height())
                if (top + h) >= event.rect().top():
                    painter.drawText(
                        0,
                        top,
                        self._ln_area.width() - 4,
                        h,
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                        str(blockNumber + 1),
                    )
                top += h
            block = block.next()
            blockNumber += 1

    def highlightCurrentLine(self) -> None:
        extraSelections: list[QtWidgets.QTextEdit.ExtraSelection] = []
        if not self.isReadOnly():
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.format.setBackground(QtGui.QColor(250, 250, 230))
            selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extraSelections.append(selection)
        self.setExtraSelections(extraSelections)


# prosegue su canvas successivo (parte 2/3)
# parte 2/3 — v6
# (incolla questa parte subito sotto la parte 1/3 nello stesso file)


class PageEditorTab(QtWidgets.QWidget):
    """Un tab in alto = UNA PAGINA.

    Dentro il tab si carica (a richiesta) il foglio ST selezionato.
    Cambiare foglio NON crea tab nuovi.
    """

    def __init__(self, mw: "MainWindow", page_id: str, page_name: str) -> None:
        super().__init__()
        self.mw = mw
        self.page_id = page_id
        self.page_name = page_name
        self.current_sheet_index0 = 0

        self._editor: Optional[StEditor] = None
        self._current_file: Optional[Path] = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.placeholder = QtWidgets.QLabel("Seleziona un foglio (in basso o dall'albero a sinistra).")
        self.placeholder.setStyleSheet("color:#666; padding:8px;")
        lay.addWidget(self.placeholder, 1)

        self._lay = lay

    def is_dirty(self) -> bool:
        return bool(self._editor and self._editor.is_dirty())

    def save_current(self) -> None:
        if self._editor:
            self._editor.save_to_disk()

    def current_file(self) -> Optional[Path]:
        return self._current_file

    def open_sheet(self, file_path: Path, sheet_index0: int) -> bool:
        file_path = file_path.resolve()

        if self._current_file and self._current_file.resolve() == file_path:
            self.current_sheet_index0 = sheet_index0
            return True

        if self._editor and self._editor.is_dirty():
            r = QtWidgets.QMessageBox.question(
                self.mw,
                "Foglio modificato",
                "Il foglio corrente è stato modificato.\nVuoi salvare prima di cambiare foglio?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
            )
            if r == QtWidgets.QMessageBox.Cancel:
                return False
            if r == QtWidgets.QMessageBox.Yes:
                try:
                    self._editor.save_to_disk()
                except Exception:
                    pass

        if not file_path.exists():
            QtWidgets.QMessageBox.critical(self.mw, "Errore", f"File non trovato: {file_path}")
            return False

        if self._editor:
            self._lay.removeWidget(self._editor)
            self._editor.deleteLater()
            self._editor = None

        self.placeholder.hide()

        try:
            self._editor = StEditor(file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self.mw, "Errore", f"Impossibile aprire {file_path.name}\n{e}")
            return False

        self._lay.addWidget(self._editor, 1)
        self._current_file = file_path
        self.current_sheet_index0 = sheet_index0
        return True


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.qs = QtCore.QSettings()
        self.project: Optional[Project] = None
        self.client = RuntimeClient()

        self._page_tabs: Dict[str, PageEditorTab] = {}

        # Bottom sheet tabs (Fogli)
        self._sheetbar_files: list[Path] = []
        self._sheetbar_page_id: Optional[str] = None
        self._sheetbar_page_name: Optional[str] = None

        self._build_ui()
        self._build_menus()
        self._apply_style()

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start()

        self.refresh_status()
        self.populate_tree_empty()
        self.clear_sheetbar()

        self.log("BOOT v6")

    # ----------------
    # UI
    # ----------------
    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)

        # Toolbar (senza comandi fogli)
        tb = QtWidgets.QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(16, 16))
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        self.act_new = QtGui.QAction("Nuovo progetto", self)
        self.act_open = QtGui.QAction("Apri progetto", self)
        self.act_close_project = QtGui.QAction("Chiudi progetto", self)
        self.act_add_page = QtGui.QAction("Aggiungi pagina", self)
        self.act_save = QtGui.QAction("Salva", self)
        self.act_save_all = QtGui.QAction("Salva tutto", self)
        self.act_settings = QtGui.QAction("Settings", self)
        self.act_connect = QtGui.QAction("Connetti", self)
        self.act_compile = QtGui.QAction("Compila", self)
        self.act_download = QtGui.QAction("Download", self)

        self.act_save.setShortcut(QtGui.QKeySequence.Save)

        for a in (self.act_new, self.act_open, self.act_close_project, self.act_add_page, self.act_save, self.act_save_all):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_settings, self.act_connect, self.act_compile, self.act_download):
            tb.addAction(a)

        self.act_new.triggered.connect(self.new_project)
        self.act_open.triggered.connect(self.open_project)
        self.act_close_project.triggered.connect(self.close_project)
        self.act_add_page.triggered.connect(self.add_page)
        self.act_save.triggered.connect(self.save_current)
        self.act_save_all.triggered.connect(self.save_all)
        self.act_settings.triggered.connect(lambda: self.tabs.setCurrentWidget(self.tab_settings))
        self.act_connect.triggered.connect(self.refresh_status)
        self.act_compile.triggered.connect(self.stub_compile)
        self.act_download.triggered.connect(self.stub_download)

        # Layout principale
        self.split = QtWidgets.QSplitter()
        self.split.setChildrenCollapsible(False)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setStyleSheet("QTreeWidget{font-size:11px;}")
        self.tree.itemClicked.connect(self.on_tree_clicked)

        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tree_context_menu)

        self.split.addWidget(self.tree)

        # Right container (tabs + sheetbar)
        self.right = QtWidgets.QWidget()
        self.right_layout = QtWidgets.QVBoxLayout(self.right)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.on_close_tab)
        self.tabs.currentChanged.connect(self.on_top_tab_changed)

        # Bottom-right sheet tab bar
        self.sheetbar_wrap = QtWidgets.QWidget()
        self.sheetbar_wrap.setFixedHeight(28)
        hb = QtWidgets.QHBoxLayout(self.sheetbar_wrap)
        hb.setContentsMargins(6, 2, 6, 2)
        hb.setSpacing(4)
        hb.addStretch(1)

        self.sheetbar = QtWidgets.QTabBar()
        self.sheetbar.setExpanding(False)
        self.sheetbar.setMovable(False)
        self.sheetbar.setDrawBase(False)
        self.sheetbar.setElideMode(QtCore.Qt.ElideNone)
        self.sheetbar.setUsesScrollButtons(True)
        self.sheetbar.currentChanged.connect(self.on_sheetbar_changed)

        self.sheetbar.setStyleSheet(
            "QTabBar::tab{font-size:10px; padding:2px 10px; margin-left:2px;"
            "background:#d9d9d9; border:1px solid #b8b8b8; border-top-left-radius:3px; border-top-right-radius:3px;}"
            "QTabBar::tab:selected{background:#f2c180; border-color:#c9a36c;}"
            "QTabBar::tab:!selected{color:#222;}"
        )

        hb.addWidget(self.sheetbar, 0, QtCore.Qt.AlignRight)

        self.right_layout.addWidget(self.tabs, 1)
        self.right_layout.addWidget(self.sheetbar_wrap, 0)

        self.split.addWidget(self.right)
        self.setCentralWidget(self.split)
        self.split.setSizes([260, 900])

        # Fixed tabs
        self.tab_settings = QtWidgets.QWidget()
        self.tab_output = QtWidgets.QWidget()
        self.tabs.addTab(self.tab_settings, "Settings")
        self.tabs.addTab(self.tab_output, "Output")

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
        sb = self.statusBar()
        sb.addWidget(self.lbl_status)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        menu_file = mb.addMenu("&File")

        a_new = menu_file.addAction("Nuovo progetto...")
        a_open = menu_file.addAction("Apri progetto...")
        a_close = menu_file.addAction("Chiudi progetto")
        menu_file.addSeparator()
        a_save = menu_file.addAction("Salva")
        a_save_all = menu_file.addAction("Salva tutto")
        a_save_as = menu_file.addAction("Salva progetto con nome...")
        menu_file.addSeparator()
        a_delete = menu_file.addAction("Elimina progetto...")
        menu_file.addSeparator()
        a_exit = menu_file.addAction("Esci")

        a_new.triggered.connect(self.new_project)
        a_open.triggered.connect(self.open_project)
        a_close.triggered.connect(self.close_project)
        a_save.triggered.connect(self.save_current)
        a_save_all.triggered.connect(self.save_all)
        a_save_as.triggered.connect(self.save_project_as)
        a_delete.triggered.connect(self.delete_project)
        a_exit.triggered.connect(self.close)

        menu_proj = mb.addMenu("&Progetto")
        a_add_page = menu_proj.addAction("Aggiungi pagina...")
        a_add_page.triggered.connect(self.add_page)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QMainWindow{font-size:11px;}"
            "QToolBar{spacing:4px;}"
            "QToolButton{padding:2px 6px;}"
            "QTabBar::tab{padding:4px 8px; margin:1px;}"
            "QSplitter::handle{background:#ddd;}"
        )

    # ----------------
    # Logging
    # ----------------
    def log(self, s: str) -> None:
        self.output.appendPlainText(s)

    # ----------------
    # Tree / Sheetbar
    # ----------------
    def populate_tree_empty(self) -> None:
        self.tree.clear()
        root = QtWidgets.QTreeWidgetItem(["Nessun progetto aperto"])
        self.tree.addTopLevelItem(root)
        root.setExpanded(True)

    def _add_sheet_item(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        page_id: str,
        page_name: str,
        sh: Dict[str, Any],
        sheet_index_0: int,
    ) -> None:
        sheet_id = str(sh.get("id", ""))
        sheet_name = str(sh.get("name", sheet_id or "Foglio"))
        label = f"{sheet_id} - {sheet_name}" if sheet_id else sheet_name
        child = QtWidgets.QTreeWidgetItem([label])

        file_rel = sh.get("file")
        if file_rel:
            child.setData(0, ROLE_FILE, str(file_rel))
            child.setData(0, ROLE_PAGE_ID, page_id)
            child.setData(0, ROLE_PAGE_NAME, page_name)
            child.setData(0, ROLE_SHEET_INDEX0, sheet_index_0)
            child.setData(0, ROLE_NODE_KIND, "SHEET")

        parent.addChild(child)

    def populate_tree_from_project(self) -> None:
        if not self.project:
            self.populate_tree_empty()
            return

        self.tree.clear()
        root_proj = QtWidgets.QTreeWidgetItem([self.project.name])
        self.tree.addTopLevelItem(root_proj)

        root_vars = QtWidgets.QTreeWidgetItem(["Variabili"])
        root_pages = QtWidgets.QTreeWidgetItem(["Pagine"])
        root_bus = QtWidgets.QTreeWidgetItem(["Bus"])
        root_proj.addChild(root_vars)
        root_proj.addChild(root_pages)
        root_proj.addChild(root_bus)

        root_pages.setData(0, ROLE_NODE_KIND, "PAGES_ROOT")

        init = self.project.pages_json.get("init")
        if init:
            init_id = str(init.get("id", "INIT"))
            init_name = str(init.get("name", "Init"))
            it = QtWidgets.QTreeWidgetItem([f"Init ({init_name})"])
            it.setData(0, ROLE_NODE_KIND, "PAGE")
            it.setData(0, ROLE_PAGE_ID, init_id)
            it.setData(0, ROLE_PAGE_NAME, init_name)
            root_pages.addChild(it)

            for idx, sh in enumerate(init.get("sheets", [])):
                self._add_sheet_item(it, init_id, init_name, sh, idx)

        for p in self.project.pages_json.get("pages", []):
            page_id = str(p.get("id", "P???"))
            page_name = str(p.get("name", page_id))
            pt = QtWidgets.QTreeWidgetItem([f"{page_id} ({page_name})"])
            pt.setData(0, ROLE_NODE_KIND, "PAGE")
            pt.setData(0, ROLE_PAGE_ID, page_id)
            pt.setData(0, ROLE_PAGE_NAME, page_name)
            root_pages.addChild(pt)

            for idx, sh in enumerate(p.get("sheets", [])):
                self._add_sheet_item(pt, page_id, page_name, sh, idx)

        root_proj.setExpanded(True)
        root_pages.setExpanded(True)

    def _sheetbar_clear_tabs(self) -> None:
        while self.sheetbar.count() > 0:
            self.sheetbar.removeTab(0)

    def clear_sheetbar(self) -> None:
        self.sheetbar.blockSignals(True)
        self._sheetbar_clear_tabs()
        self.sheetbar.blockSignals(False)
        self._sheetbar_files = []
        self._sheetbar_page_id = None
        self._sheetbar_page_name = None
        self.sheetbar.setEnabled(False)

    def set_sheetbar_page(self, page_id: str, page_name: str, selected_sheet_index_0: int = 0) -> None:
        if not self.project:
            self.clear_sheetbar()
            return

        sheets: list[Dict[str, Any]] = []
        if page_id == "INIT":
            init = self.project.pages_json.get("init") or {}
            sheets = list(init.get("sheets", []))
        else:
            for p in self.project.pages_json.get("pages", []):
                if str(p.get("id")) == page_id:
                    sheets = list(p.get("sheets", []))
                    break

        self._sheetbar_files = []
        self.sheetbar.blockSignals(True)
        self._sheetbar_clear_tabs()

        for i, sh in enumerate(sheets):
            file_rel = sh.get("file")
            if not file_rel:
                continue
            fp = (self.project.root / str(file_rel)).resolve()
            self._sheetbar_files.append(fp)
            self.sheetbar.addTab(str(i + 1))
            sheet_name = str(sh.get("name", f"Foglio{i+1}"))
            self.sheetbar.setTabToolTip(i, f"{page_name} — {sheet_name}")

        if self.sheetbar.count() == 0:
            self.sheetbar.setEnabled(False)
        else:
            self.sheetbar.setEnabled(True)
            idx = selected_sheet_index_0 if 0 <= selected_sheet_index_0 < self.sheetbar.count() else 0
            self.sheetbar.setCurrentIndex(idx)

        self.sheetbar.blockSignals(False)
        self._sheetbar_page_id = page_id
        self._sheetbar_page_name = page_name

    # ----------------
    # Page tabs (top)
    # ----------------
    def _is_fixed_tab(self, w: QtWidgets.QWidget) -> bool:
        return w is self.tab_settings or w is self.tab_output

    def _find_page_tab_index(self, page_id: str) -> Optional[int]:
        tab = self._page_tabs.get(page_id)
        if not tab:
            return None
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is tab:
                return i
        return None

    def _get_or_create_page_tab(self, page_id: str, page_name: str) -> PageEditorTab:
        tab = self._page_tabs.get(page_id)
        if tab:
            return tab
        tab = PageEditorTab(self, page_id, page_name)
        self._page_tabs[page_id] = tab
        self.tabs.insertTab(0, tab, page_name)  # tab label: SOLO nome pagina
        self.tabs.setTabToolTip(0, page_id)
        return tab

    def _close_page_tab(self, page_id: str) -> None:
        tab = self._page_tabs.get(page_id)
        if not tab:
            return
        idx = self._find_page_tab_index(page_id)
        if idx is not None:
            self.tabs.removeTab(idx)
        self._page_tabs.pop(page_id, None)

    def open_page_sheet(self, page_id: str, page_name: str, sheet_idx0: int) -> None:
        if not self.project:
            return
        if sheet_idx0 < 0 or sheet_idx0 >= len(self._sheetbar_files):
            return

        fp = self._sheetbar_files[sheet_idx0]

        # FBD: not implemented (per foglio)
        if fp.name.endswith(".fbd.json"):
            QtWidgets.QMessageBox.information(self, "FBD", "Editor FBD non ancora implementato (MVP).")
            return

        tab = self._get_or_create_page_tab(page_id, page_name)
        self.tabs.setCurrentWidget(tab)

        ok = tab.open_sheet(fp, sheet_idx0)
        if ok:
            self.set_sheetbar_page(page_id, page_name, sheet_idx0)

    # ----------------
    # Context menu (NO fogli)
    # ----------------
    def on_tree_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return

        kind = item.data(0, ROLE_NODE_KIND)
        menu = QtWidgets.QMenu(self)

        if kind == "PAGES_ROOT":
            a_new = menu.addAction("Nuova pagina")
            a_new.triggered.connect(self.add_page)

        elif kind == "PAGE":
            page_id = str(item.data(0, ROLE_PAGE_ID) or "")
            page_name = str(item.data(0, ROLE_PAGE_NAME) or "")
            a_del_page = menu.addAction("Elimina pagina")
            if page_id == "INIT":
                a_del_page.setEnabled(False)
            a_del_page.triggered.connect(lambda: self.delete_page(page_id, page_name))

        else:
            return

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ----------------
    # Click su albero
    # ----------------
    def on_tree_clicked(self, item: QtWidgets.QTreeWidgetItem, col: int) -> None:
        if not self.project:
            return

        kind = item.data(0, ROLE_NODE_KIND)

        if kind == "PAGE":
            page_id = str(item.data(0, ROLE_PAGE_ID) or "")
            page_name = str(item.data(0, ROLE_PAGE_NAME) or "")
            if page_id and page_name:
                self.set_sheetbar_page(page_id, page_name, 0)
                # apro il tab pagina (solo nome pagina) e mostro foglio 1
                self.open_page_sheet(page_id, page_name, 0)
            return

        if kind == "SHEET":
            rel = item.data(0, ROLE_FILE)
            page_id = str(item.data(0, ROLE_PAGE_ID) or "")
            page_name = str(item.data(0, ROLE_PAGE_NAME) or "")
            sheet_idx0 = int(item.data(0, ROLE_SHEET_INDEX0) or 0)

            if page_id and page_name:
                self.set_sheetbar_page(page_id, page_name, sheet_idx0)
                self.open_page_sheet(page_id, page_name, sheet_idx0)
            return

    def on_sheetbar_changed(self, idx: int) -> None:
        if not self.project:
            return
        if idx < 0 or idx >= len(self._sheetbar_files):
            return
        if not self._sheetbar_page_id or not self._sheetbar_page_name:
            return
        self.open_page_sheet(self._sheetbar_page_id, self._sheetbar_page_name, idx)

    def on_close_tab(self, idx: int) -> None:
        w = self.tabs.widget(idx)
        if self._is_fixed_tab(w):
            return
        if isinstance(w, PageEditorTab):
            if w.is_dirty():
                r = QtWidgets.QMessageBox.question(
                    self,
                    "Chiudi pagina",
                    f"Pagina: {w.page_name}\nFoglio modificato. Vuoi salvare?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                )
                if r == QtWidgets.QMessageBox.Cancel:
                    return
                if r == QtWidgets.QMessageBox.Yes:
                    w.save_current()
            self._close_page_tab(w.page_id)
        self.on_top_tab_changed(self.tabs.currentIndex())

    def on_top_tab_changed(self, idx: int) -> None:
        w = self.tabs.widget(idx)
        if isinstance(w, PageEditorTab):
            self.set_sheetbar_page(w.page_id, w.page_name, w.current_sheet_index0)
            return
        self.sheetbar.setEnabled(False)

    # prosegue su canvas successivo (parte 3/3)
# parte 3/3 — v6
# (incolla questa parte subito sotto la parte 2/3 nello stesso file)

    # ----------------
    # Persistence: dirs
    # ----------------
    def get_last_project_dir(self) -> Path:
        v = self.qs.value("last_project_dir", "")
        if isinstance(v, str) and v.strip():
            p = Path(v)
            if p.exists() and p.is_dir():
                return p
        return default_projects_dir()

    def set_last_project_dir(self, p: Path) -> None:
        try:
            self.qs.setValue("last_project_dir", str(p))
        except Exception:
            pass

    def get_last_base_dir(self) -> Path:
        v = self.qs.value("last_base_dir", "")
        if isinstance(v, str) and v.strip():
            p = Path(v)
            if p.exists() and p.is_dir():
                return p
        return default_projects_dir()

    def set_last_base_dir(self, p: Path) -> None:
        try:
            self.qs.setValue("last_base_dir", str(p))
        except Exception:
            pass

    # ----------------
    # Project lifecycle
    # ----------------
    def _open_project_path(self, folder: Path) -> None:
        self.project = load_project(folder)
        self.setWindowTitle(f"{APP_NAME} — {self.project.name}")
        self.populate_tree_from_project()
        self.clear_sheetbar()
        self._page_tabs.clear()
        self.log(f"OK: aperto progetto {self.project.root}")
        self.set_last_project_dir(self.project.root.parent)

    def close_project(self) -> None:
        if not self.project:
            return

        # chiudo tutti i tab pagina con prompt se serve
        for page_id in list(self._page_tabs.keys()):
            tab = self._page_tabs.get(page_id)
            if tab and tab.is_dirty():
                r = QtWidgets.QMessageBox.question(
                    self,
                    "Chiudi progetto",
                    f"Pagina '{tab.page_name}' ha modifiche non salvate.\nSalvare prima di chiudere il progetto?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                )
                if r == QtWidgets.QMessageBox.Cancel:
                    return
                if r == QtWidgets.QMessageBox.Yes:
                    try:
                        tab.save_current()
                    except Exception:
                        pass

        # rimuovo i tab pagina
        for page_id in list(self._page_tabs.keys()):
            self._close_page_tab(page_id)

        self.project = None
        self.setWindowTitle(APP_NAME)
        self.populate_tree_empty()
        self.clear_sheetbar()
        self.log("OK: progetto chiuso")

    # ----------------
    # Actions: File menu
    # ----------------
    def new_project(self) -> None:
        dlg = NewProjectDialog(self.get_last_base_dir(), self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        name, base = dlg.get_values()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Nuovo progetto", "Nome progetto vuoto.")
            return

        # se c'è un progetto aperto, provo a chiuderlo (prompt)
        if self.project:
            self.close_project()
            if self.project:
                return

        out_dir = base / name
        try:
            ensure_dir(base)
            create_project_skeleton(out_dir, name)
            self.set_last_base_dir(base)
            self._open_project_path(out_dir)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    def open_project(self) -> None:
        base = self.get_last_project_dir()
        dlg = ProjectPickerDialog(base, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        folder = dlg.selected_folder()
        if not folder:
            return

        if self.project:
            self.close_project()
            if self.project:
                return

        self._open_project_path(folder)

    def save_current(self) -> None:
        w = self.tabs.currentWidget()
        if isinstance(w, PageEditorTab):
            try:
                w.save_current()
                self.log(f"Salvato: {w.page_name} (foglio {w.current_sheet_index0+1})")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    def save_all(self) -> None:
        saved = 0
        for tab in list(self._page_tabs.values()):
            if tab.is_dirty():
                try:
                    tab.save_current()
                    saved += 1
                except Exception:
                    pass
        self.log(f"Salva tutto: {saved} tab salvati")

    def save_project_as(self) -> None:
        if not self.project:
            QtWidgets.QMessageBox.information(self, "Salva con nome", "Apri prima un progetto.")
            return

        base = QtWidgets.QFileDialog.getExistingDirectory(self, "Scegli cartella base", str(self.project.root.parent))
        if not base:
            return
        base_path = Path(base).expanduser().resolve()

        new_name, ok = QtWidgets.QInputDialog.getText(self, "Salva progetto con nome", "Nome nuovo progetto:")
        if not ok:
            return
        new_name = (new_name or "").strip()
        if not new_name:
            return

        out_dir = base_path / new_name
        if out_dir.exists() and not folder_effectively_empty(out_dir):
            QtWidgets.QMessageBox.warning(self, "Salva con nome", f"Cartella già esistente e non vuota:\n{out_dir}")
            return

        # Prima salvo eventuali modifiche correnti
        self.save_all()

        try:
            if out_dir.exists():
                shutil.rmtree(out_dir, ignore_errors=True)
            shutil.copytree(self.project.root, out_dir)

            pj_path = out_dir / "project.json"
            pj = load_json(pj_path)
            pj["name"] = new_name
            pj["saved_as_utc"] = utc_now_iso()
            write_json(pj_path, pj)

            self.set_last_project_dir(out_dir.parent)
            self._open_project_path(out_dir)
            self.log(f"OK: salvato progetto con nome in {out_dir}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    def delete_project(self) -> None:
        if not self.project:
            QtWidgets.QMessageBox.information(self, "Elimina progetto", "Nessun progetto aperto.")
            return

        proj_root = self.project.root
        proj_name = self.project.name

        r = QtWidgets.QMessageBox.question(
            self,
            "Elimina progetto",
            f"Eliminare definitivamente il progetto '{proj_name}'?\n\nCartella:\n{proj_root}\n\n(Operazione irreversibile)",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if r != QtWidgets.QMessageBox.Yes:
            return

        r2 = QtWidgets.QMessageBox.question(
            self,
            "Conferma eliminazione",
            "Confermi ancora?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if r2 != QtWidgets.QMessageBox.Yes:
            return

        try:
            self.close_project()
            if proj_root.exists():
                shutil.rmtree(proj_root, ignore_errors=True)
            self.log(f"OK: eliminato progetto {proj_name}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    # ----------------
    # Actions: progetto
    # ----------------
    def add_page(self) -> None:
        if not self.project:
            QtWidgets.QMessageBox.information(self, "Aggiungi pagina", "Apri prima un progetto.")
            return

        dlg = AddPageDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        page_name, lang = dlg.get_values()
        if not page_name:
            QtWidgets.QMessageBox.warning(self, "Aggiungi pagina", "Nome pagina vuoto.")
            return

        try:
            pid = add_page_to_project(self.project, page_name, lang)
            self.log(f"OK: aggiunta pagina {pid} ({page_name}) [{lang}]")
            self.populate_tree_from_project()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    def delete_page(self, page_id: str, page_name: str) -> None:
        if not self.project:
            return
        if page_id == "INIT":
            return

        pages_list = list(self.project.pages_json.get("pages", []))
        if len(pages_list) <= 1:
            QtWidgets.QMessageBox.information(self, "Elimina pagina", "Deve restare almeno 1 pagina (Main).")
            return

        r = QtWidgets.QMessageBox.question(
            self,
            "Elimina pagina",
            f"Eliminare pagina {page_id} ({page_name})?\n(Elimino anche i file su disco)",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if r != QtWidgets.QMessageBox.Yes:
            return

        try:
            # se la pagina è aperta, chiudo il tab (con prompt se dirty)
            tab = self._page_tabs.get(page_id)
            if tab and tab.is_dirty():
                r2 = QtWidgets.QMessageBox.question(
                    self,
                    "Pagina modificata",
                    f"La pagina '{page_name}' ha modifiche non salvate.\nSalvare prima di eliminare?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                )
                if r2 == QtWidgets.QMessageBox.Cancel:
                    return
                if r2 == QtWidgets.QMessageBox.Yes:
                    tab.save_current()

            self._close_page_tab(page_id)

            # aggiorno pages.json
            self.project.pages_json["pages"] = [p for p in pages_list if str(p.get("id")) != page_id]
            write_json(self.project.root / "pages.json", self.project.pages_json)

            # elimino wrapper e cartella pagina
            wrapper = (self.project.root / "pages" / f"{page_id}.st").resolve()
            if wrapper.exists():
                wrapper.unlink(missing_ok=True)

            page_folder = (self.project.root / "pages" / page_id).resolve()
            if page_folder.exists():
                shutil.rmtree(page_folder, ignore_errors=True)

            # ricarico e refresh UI
            self.project.pages_json = load_json(self.project.root / "pages.json")
            self.populate_tree_from_project()

            if self._sheetbar_page_id == page_id:
                self.clear_sheetbar()

            self.log(f"OK: eliminata pagina {page_id} ({page_name})")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    # ----------------
    # Runtime
    # ----------------
    def on_profile_changed(self, p: RuntimeProfile) -> None:
        self.client.set_profile(p)
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
