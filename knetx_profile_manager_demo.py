# parte 1/1
# KnetX Profile Manager (DEMO ISOLATO)
# Scopo: provare UI + salvataggio profili IP/porta su file di progetto (connections.json)
# - Nessun QSettings
# - I profili sono SOLO quelli del progetto (cartella selezionata)
# - Pulsanti: Apri, Salva, Rinomina, Cancella
#
# Uso (Windows):
#   py knetx_profile_manager_demo.py
# Poi scegli una cartella progetto: verrà creato/letto <cartella>/connections.json

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets


DEFAULT_PORT = 1963
CONNECTIONS_FILENAME = "connections.json"


# ----------------------------
# Model / Store
# ----------------------------
@dataclass
class ConnProfile:
    name: str
    host: str
    port: int


class ConnectionStore:
    """Gestisce lettura/scrittura del file connections.json dentro una cartella progetto."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.path = (project_dir / CONNECTIONS_FILENAME).resolve()

    def load_or_create(self) -> Dict[str, Any]:
        if not self.project_dir.exists():
            self.project_dir.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            data = self.default_data()
            self.save(data)
            return data

        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return self._normalize(data)
        except Exception:
            # Se file corrotto, non lo distruggiamo: facciamo backup e ricreiamo.
            try:
                bak = self.path.with_suffix(self.path.suffix + ".bak")
                self.path.replace(bak)
            except Exception:
                pass
            data = self.default_data()
            self.save(data)
            return data

    def save(self, data: Dict[str, Any]) -> None:
        data = self._normalize(data)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # replace atomico (su Windows Path.replace sovrascrive)
        tmp.replace(self.path)

    def default_data(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "selected": "Localhost",
            "profiles": [
                {"name": "Localhost", "host": "127.0.0.1", "port": DEFAULT_PORT},
                # placeholder voluto: da reimpostare
                {"name": "WorkConnect", "host": "0.0.0.0", "port": DEFAULT_PORT},
            ],
        }

    def _normalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schema_version": int(data.get("schema_version", 1) or 1),
            "selected": str(data.get("selected", "") or "").strip(),
            "profiles": [],
        }

        profs = data.get("profiles")
        if not isinstance(profs, list):
            profs = []

        seen = set()
        norm_profiles: List[Dict[str, Any]] = []
        for p in profs:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "") or "").strip()
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            host = str(p.get("host", "") or "").strip()
            port = p.get("port", DEFAULT_PORT)
            try:
                port_i = int(port)
            except Exception:
                port_i = DEFAULT_PORT
            if port_i < 1 or port_i > 65535:
                port_i = DEFAULT_PORT
            norm_profiles.append({"name": name, "host": host, "port": port_i})

        if not norm_profiles:
            norm_profiles = list(self.default_data()["profiles"])

        out["profiles"] = norm_profiles

        selected = out["selected"]
        if not selected or selected not in {p["name"] for p in norm_profiles}:
            out["selected"] = norm_profiles[0]["name"]

        return out


def _profiles_from_data(data: Dict[str, Any]) -> List[ConnProfile]:
    out: List[ConnProfile] = []
    for p in data.get("profiles", []) or []:
        out.append(ConnProfile(str(p.get("name")), str(p.get("host", "")), int(p.get("port", DEFAULT_PORT))))
    return out


def _data_from_profiles(selected: str, profiles: List[ConnProfile]) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "selected": selected,
        "profiles": [{"name": p.name, "host": p.host, "port": int(p.port)} for p in profiles],
    }


# ----------------------------
# UI
# ----------------------------
class ProfileManagerDemo(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KnetX Profile Manager — DEMO")
        self.resize(760, 380)

        self.project_dir: Path = Path.cwd().resolve()
        self.store: Optional[ConnectionStore] = None
        self.data: Dict[str, Any] = {}
        self.profiles: List[ConnProfile] = []

        # Top: project dir chooser
        self.ed_project = QtWidgets.QLineEdit(str(self.project_dir))
        self.btn_browse = QtWidgets.QPushButton("...")
        self.btn_browse.setFixedWidth(34)

        row_proj = QtWidgets.QHBoxLayout()
        row_proj.addWidget(QtWidgets.QLabel("Cartella progetto"))
        row_proj.addWidget(self.ed_project, 1)
        row_proj.addWidget(self.btn_browse)

        # Profile selection
        self.cbo = QtWidgets.QComboBox()
        self.btn_open = QtWidgets.QPushButton("Apri")
        self.btn_save = QtWidgets.QPushButton("Salva")
        self.btn_rename = QtWidgets.QPushButton("Rinomina")
        self.btn_delete = QtWidgets.QPushButton("Cancella")

        row_sel = QtWidgets.QHBoxLayout()
        row_sel.addWidget(QtWidgets.QLabel("Profilo"))
        row_sel.addWidget(self.cbo, 1)
        row_sel.addWidget(self.btn_open)
        row_sel.addWidget(self.btn_save)
        row_sel.addWidget(self.btn_rename)
        row_sel.addWidget(self.btn_delete)

        # Fields
        self.ed_name = QtWidgets.QLineEdit()
        self.ed_host = QtWidgets.QLineEdit()
        self.sp_port = QtWidgets.QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(DEFAULT_PORT)

        form = QtWidgets.QFormLayout()
        form.addRow("Nome profilo", self.ed_name)
        form.addRow("Host/IP", self.ed_host)
        form.addRow("Porta", self.sp_port)

        # Status / preview
        self.lbl_file = QtWidgets.QLabel("")
        self.lbl_file.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setStyleSheet("color:#444;")

        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(140)
        self.preview.setStyleSheet("font-size:11px;")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addLayout(row_proj)
        root.addLayout(row_sel)
        root.addLayout(form)
        root.addWidget(self.lbl_file)
        root.addWidget(self.lbl_status)
        root.addWidget(self.preview)

        # Signals
        self.btn_browse.clicked.connect(self.on_browse)
        self.btn_open.clicked.connect(self.on_open_profile)
        self.btn_save.clicked.connect(self.on_save_profile)
        self.btn_delete.clicked.connect(self.on_delete_profile)
        self.btn_rename.clicked.connect(self.on_rename_profile)

        # QoL: quando cambi profilo in combo, aggiorniamo subito i campi (Apri resta comunque disponibile)
        self.cbo.currentIndexChanged.connect(lambda _i: self.on_open_profile())

        # Load initial
        self.load_project_dir(self.project_dir)

    # ----------------------------
    # Project selection
    # ----------------------------
    def on_browse(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Scegli cartella progetto", str(self.project_dir))
        if not d:
            return
        self.ed_project.setText(d)
        self.load_project_dir(Path(d).expanduser().resolve())

    def load_project_dir(self, p: Path) -> None:
        self.project_dir = p
        self.store = ConnectionStore(self.project_dir)
        self.data = self.store.load_or_create()
        self.profiles = _profiles_from_data(self.data)

        self.lbl_file.setText(f"File profili: {self.store.path}")
        self.refresh_combo()
        self.refresh_preview()
        self._set_status(f"Caricato progetto: {self.project_dir}")

    # ----------------------------
    # Helpers
    # ----------------------------
    def refresh_combo(self) -> None:
        self.cbo.blockSignals(True)
        self.cbo.clear()
        for p in self.profiles:
            self.cbo.addItem(p.name)

        selected = str(self.data.get("selected", "") or "")
        idx = 0
        for i, p in enumerate(self.profiles):
            if p.name == selected:
                idx = i
                break
        self.cbo.setCurrentIndex(idx)
        self.cbo.blockSignals(False)

        # carica subito il profilo selezionato
        self.on_open_profile()

    def refresh_preview(self) -> None:
        # aggiorna data da profiles
        selected = self.current_selected_name() or (self.profiles[0].name if self.profiles else "")
        self.data = _data_from_profiles(selected, self.profiles)
        self.preview.setPlainText(json.dumps(self.data, ensure_ascii=False, indent=2))

    def current_selected_name(self) -> str:
        return self.cbo.currentText().strip()

    def find_profile(self, name: str) -> Optional[ConnProfile]:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def _persist(self, selected_name: str) -> None:
        assert self.store is not None
        self.data = _data_from_profiles(selected_name, self.profiles)
        self.store.save(self.data)
        self.refresh_preview()

    def _set_status(self, msg: str) -> None:
        self.lbl_status.setText(msg)

    def _warn(self, title: str, msg: str) -> None:
        QtWidgets.QMessageBox.warning(self, title, msg)

    # ----------------------------
    # Buttons
    # ----------------------------
    def on_open_profile(self) -> None:
        name = self.current_selected_name()
        p = self.find_profile(name)
        if not p:
            return
        # Carica campi
        self.ed_name.setText(p.name)
        self.ed_host.setText(p.host)
        self.sp_port.setValue(int(p.port))

        # Marca come selected e persiste (così il progetto ricorda l'ultimo profilo)
        self.data["selected"] = p.name
        try:
            self._persist(p.name)
        except Exception as e:
            self._warn("Persist", str(e))
            return

        self._set_status(f"Aperto: {p.name}")

    def on_save_profile(self) -> None:
        name = self.ed_name.text().strip()
        host = self.ed_host.text().strip()
        port = int(self.sp_port.value())

        if not name:
            self._warn("Salva profilo", "Nome profilo vuoto.")
            return

        existing = self.find_profile(name)
        if existing:
            existing.host = host
            existing.port = port
            self._set_status(f"Aggiornato: {name}")
        else:
            self.profiles.append(ConnProfile(name=name, host=host, port=port))
            self._set_status(f"Creato: {name}")

        # Persist + seleziona questo
        try:
            self._persist(name)
        except Exception as e:
            self._warn("Salva", str(e))
            return

        # aggiorna combo e selezione
        self.refresh_combo()
        idx = self.cbo.findText(name)
        if idx >= 0:
            self.cbo.setCurrentIndex(idx)
        self.on_open_profile()

    def on_delete_profile(self) -> None:
        name = self.current_selected_name()
        if not name:
            return
        if len(self.profiles) <= 1:
            self._warn("Cancella", "Deve restare almeno 1 profilo.")
            return

        r = QtWidgets.QMessageBox.question(
            self,
            "Cancella profilo",
            f"Cancellare il profilo '{name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if r != QtWidgets.QMessageBox.Yes:
            return

        self.profiles = [p for p in self.profiles if p.name != name]
        # seleziona primo
        new_sel = self.profiles[0].name

        try:
            self._persist(new_sel)
        except Exception as e:
            self._warn("Cancella", str(e))
            return

        self.refresh_combo()
        self._set_status(f"Cancellato: {name}")

    def on_rename_profile(self) -> None:
        old_name = self.current_selected_name()
        if not old_name:
            return

        new_name = self.ed_name.text().strip()
        if not new_name:
            self._warn("Rinomina", "Nome nuovo vuoto.")
            return

        if new_name == old_name:
            self._warn("Rinomina", "Nome nuovo uguale al vecchio.")
            return

        if self.find_profile(new_name):
            self._warn("Rinomina", f"Esiste già un profilo con nome '{new_name}'.")
            return

        p = self.find_profile(old_name)
        if not p:
            return

        p.name = new_name
        # Nota: manteniamo host/port dai campi (se li hai cambiati)
        p.host = self.ed_host.text().strip()
        p.port = int(self.sp_port.value())

        try:
            self._persist(new_name)
        except Exception as e:
            self._warn("Rinomina", str(e))
            return

        self.refresh_combo()
        idx = self.cbo.findText(new_name)
        if idx >= 0:
            self.cbo.setCurrentIndex(idx)
        self.on_open_profile()
        self._set_status(f"Rinominato: {old_name} → {new_name}")


def main() -> int:
    # High DPI ok
    try:
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    except Exception:
        pass

    app = QtWidgets.QApplication([])
    app.setOrganizationName("SplKnetx")
    app.setApplicationName("KnetX Profile Manager Demo")

    w = ProfileManagerDemo()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())