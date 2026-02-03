# parte 6/9 — ide/dialogs.py
#from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from PySide6 import QtCore, QtWidgets

from ide.runtime_client import RuntimeProfile
from ide.connection_store import ConnectionStore, ConnProfile
from ide.utils import default_projects_dir, load_json


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

        self.ed_name = QtWidgets.QLineEdit("Demo3")
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
    """Gestione profili runtime PER-PROGETTO.

    Profili in <root_progetto>/connections.json.
    Senza progetto: widget disabilitato e campi vuoti (runtime OFF).

    Pulsanti:
      - Nuovo: pulisce i campi per creare un profilo nuovo.
      - Salva: crea/aggiorna profilo usando Nome/Host/Porta nei campi e lo rende attivo.
      - Rinomina: 1° click seleziona il nome; 2° click conferma rinomina se il nome è cambiato.
      - Cancella: elimina profilo selezionato (deve restare almeno 1).

    Combo:
      - Selezione profilo => diventa SUBITO attivo (label + emit) e viene salvato come selected.
    """

    profile_changed = QtCore.Signal(RuntimeProfile)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

        self._project_root: Optional[Path] = None
        self._store: Optional[ConnectionStore] = None
        self._profiles: list[ConnProfile] = []
        self._selected: str = ""
        self._in_ui = False

        # stato per rinomina in 2 fasi
        self._rename_pending_old: Optional[str] = None

        # --- UI ---
        self.lbl_project = QtWidgets.QLabel("(nessun progetto aperto) — runtime OFF")
        self.lbl_project.setStyleSheet("color:#666; font-size:11px;")

        self.lbl_active = QtWidgets.QLabel("Attivo: (nessuno)")
        self.lbl_active.setStyleSheet("color:#444; font-size:11px; font-weight:600;")

        self.lbl_msg = QtWidgets.QLabel("")
        self.lbl_msg.setStyleSheet("color:#0a0; font-size:11px; font-weight:600;")

        self.cbo = QtWidgets.QComboBox()
        self.ed_name = QtWidgets.QLineEdit()
        self.ed_host = QtWidgets.QLineEdit()

        self.sp_port = QtWidgets.QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(1963)

        self.btn_new = QtWidgets.QPushButton("Nuovo")
        self.btn_save = QtWidgets.QPushButton("Salva")
        self.btn_rename = QtWidgets.QPushButton("Rinomina")
        self.btn_delete = QtWidgets.QPushButton("Cancella")

        row1 = QtWidgets.QHBoxLayout()
        row1.addWidget(QtWidgets.QLabel("Profilo"))
        row1.addWidget(self.cbo, 1)
        row1.addWidget(self.btn_new)
        row1.addWidget(self.btn_save)
        row1.addWidget(self.btn_rename)
        row1.addWidget(self.btn_delete)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(6, 6, 6, 6)
        form.addRow("Nome profilo", self.ed_name)
        form.addRow("Host/IP", self.ed_host)
        form.addRow("Porta", self.sp_port)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.addWidget(self.lbl_project)

        row0 = QtWidgets.QHBoxLayout()
        row0.addWidget(self.lbl_active, 1)
        row0.addWidget(self.lbl_msg, 0, QtCore.Qt.AlignRight)
        root.addLayout(row0)

        root.addLayout(row1)
        root.addLayout(form)
        root.addStretch(1)

        # --- Signals ---
        self.btn_new.clicked.connect(self.new_profile)
        self.btn_save.clicked.connect(self.save_current)
        self.btn_rename.clicked.connect(self.rename_current)
        self.btn_delete.clicked.connect(self.delete_selected)

        # Combo: selezione => attiva profilo (persist selected + emit)
        self.cbo.currentIndexChanged.connect(self.on_combo_changed)

        # runtime OFF finché non setti un progetto
        self.clear_project()

    # --------------------
    # API chiamate da MainWindow
    # --------------------
    def set_project(self, project_root: Path) -> None:
        """Abilita il widget e carica i profili dal progetto."""
        self._project_root = project_root.resolve()
        self._store = ConnectionStore(self._project_root)
        self._selected, self._profiles = self._store.load_profiles()
        self._rename_pending_old = None

        self.lbl_project.setText(f"Progetto: {self._project_root}")
        self._rebuild_combo(select_name=self._selected)
        self._load_fields_from_combo()
        self._set_enabled(True)

        # Mostra ed applica il selected (senza riscrivere i profili, ma salviamo il selected se manca)
        self._activate_profile(self._selected, persist_selected=True)

    def clear_project(self) -> None:
        """Disabilita e svuota (runtime OFF)."""
        self._project_root = None
        self._store = None
        self._profiles = []
        self._selected = ""
        self._rename_pending_old = None

        self.lbl_project.setText("(nessun progetto aperto) — runtime OFF")
        self._set_active_label(None)
        self._set_msg("")

        self._in_ui = True
        try:
            self.cbo.clear()
            self.ed_name.setText("")
            self.ed_host.setText("")
            self.sp_port.setValue(1963)
        finally:
            self._in_ui = False

        self._set_enabled(False)

    # --------------------
    # Internal helpers
    # --------------------
    def _set_enabled(self, enabled: bool) -> None:
        self.cbo.setEnabled(enabled)
        self.ed_name.setEnabled(enabled)
        self.ed_host.setEnabled(enabled)
        self.sp_port.setEnabled(enabled)
        self.btn_new.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)
        self.btn_rename.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    def _rebuild_combo(self, select_name: str = "") -> None:
        self._in_ui = True
        try:
            self.cbo.clear()
            for p in self._profiles:
                self.cbo.addItem(p.name)
            if self.cbo.count() == 0:
                return

            idx = 0
            if select_name:
                for i, p in enumerate(self._profiles):
                    if p.name == select_name:
                        idx = i
                        break
            self.cbo.setCurrentIndex(idx)
        finally:
            self._in_ui = False

    def _current_combo_name(self) -> str:
        return (self.cbo.currentText() or "").strip()

    def _find(self, name: str) -> Optional[ConnProfile]:
        for p in self._profiles:
            if p.name == name:
                return p
        return None

    def _persist_selected_and_profiles(self, selected_name: str) -> None:
        if not self._store:
            return
        self._selected = selected_name
        self._store.save_profiles(self._selected, self._profiles)

    def _persist_selected_only(self, selected_name: str) -> None:
        if not self._store:
            return
        self._selected = selected_name
        # scrive solo il campo selected, ma usando save_profiles (i profili restano uguali)
        self._store.save_profiles(self._selected, self._profiles)

    def _load_fields_from_combo(self) -> None:
        if self._in_ui:
            return
        name = self._current_combo_name()
        p = self._find(name)
        if not p:
            return

        self._rename_pending_old = None

        self._in_ui = True
        try:
            self.ed_name.setText(p.name)
            self.ed_host.setText(p.host)
            self.sp_port.setValue(int(p.port))
        finally:
            self._in_ui = False

    def _emit_profile_by_name(self, name: str) -> None:
        p = self._find(name)
        if not p:
            return
        self.profile_changed.emit(RuntimeProfile(p.name, p.host, int(p.port)))

    def _set_active_label(self, profile_name: Optional[str]) -> None:
        if not profile_name:
            self.lbl_active.setText("Attivo: (nessuno)")
            return
        p = self._find(profile_name)
        if not p:
            self.lbl_active.setText(f"Attivo: {profile_name}")
            return
        self.lbl_active.setText(f"Attivo: {p.name} — {p.host}:{int(p.port)}")

    def _set_msg(self, msg: str, ttl_ms: int = 0) -> None:
        self.lbl_msg.setText(msg)
        if ttl_ms > 0:
            QtCore.QTimer.singleShot(ttl_ms, lambda: self.lbl_msg.setText(""))

    def _warn(self, title: str, msg: str) -> None:
        QtWidgets.QMessageBox.warning(self, title, msg)

    def _activate_profile(self, name: str, persist_selected: bool) -> None:
        p = self._find(name)
        if not p:
            return
        self._set_active_label(p.name)
        self._emit_profile_by_name(p.name)
        if persist_selected:
            try:
                self._persist_selected_only(p.name)
            except Exception:
                # non bloccare UI per questo
                pass

    # --------------------
    # Combo
    # --------------------
    def on_combo_changed(self, _idx: int) -> None:
        if self._in_ui or not self._store:
            return
        self._load_fields_from_combo()
        name = self._current_combo_name()
        if not name:
            return
        self._activate_profile(name, persist_selected=True)

    # --------------------
    # Buttons
    # --------------------
    def new_profile(self) -> None:
        """Nuovo: pulisce i campi per creare un profilo."""
        if not self._store:
            return
        self._rename_pending_old = None
        self._set_msg("")

        self._in_ui = True
        try:
            self.ed_name.setText("")
            self.ed_host.setText("")
            self.sp_port.setValue(1963)
        finally:
            self._in_ui = False

        self.ed_name.setFocus(QtCore.Qt.TabFocusReason)
        self.ed_name.selectAll()

    def save_current(self) -> None:
        """Salva: crea o aggiorna usando i campi, e rende attivo questo profilo."""
        if not self._store:
            return

        name = self.ed_name.text().strip()
        host = self.ed_host.text().strip()
        port = int(self.sp_port.value())

        if not name:
            self._warn("Salva profilo", "Nome profilo vuoto.")
            return

        ex = self._find(name)
        if ex:
            ex.host = host
            ex.port = port
        else:
            self._profiles.append(ConnProfile(name=name, host=host, port=port))

        try:
            self._persist_selected_and_profiles(name)
        except Exception as e:
            self._warn("Salva profilo", str(e))
            return

        self._rename_pending_old = None
        self._rebuild_combo(select_name=name)
        self._load_fields_from_combo()
        self._activate_profile(name, persist_selected=False)
        self._set_msg("Salvato", ttl_ms=1500)

    def rename_current(self) -> None:
        """Rinomina a 2 fasi:

        - Se non è pending: seleziona il nome e attiva pending.
        - Se pending e il nome è cambiato: esegue la rinomina.
        """
        if not self._store:
            return

        old = self._current_combo_name()
        if not old:
            return

        # Fase 1: seleziona il nome
        if self._rename_pending_old != old:
            self._rename_pending_old = old
            self.ed_name.setFocus(QtCore.Qt.TabFocusReason)
            self.ed_name.selectAll()
            return

        # Fase 2: conferma
        new = self.ed_name.text().strip()
        if not new:
            self._warn("Rinomina", "Nome nuovo vuoto.")
            return
        if new == old:
            self._warn("Rinomina", "Scrivi un nome diverso e premi Rinomina.")
            return
        if self._find(new):
            self._warn("Rinomina", f"Esiste già un profilo '{new}'.")
            return

        p = self._find(old)
        if not p:
            return

        # mantieni eventuali modifiche host/porta dai campi
        p.host = self.ed_host.text().strip()
        p.port = int(self.sp_port.value())
        p.name = new

        try:
            self._persist_selected_and_profiles(new)
        except Exception as e:
            self._warn("Rinomina", str(e))
            return

        self._rename_pending_old = None
        self._rebuild_combo(select_name=new)
        self._load_fields_from_combo()
        self._activate_profile(new, persist_selected=False)
        self._set_msg("Salvato", ttl_ms=1500)

    def delete_selected(self) -> None:
        """Cancella: elimina il profilo selezionato (deve restare almeno 1)."""
        if not self._store:
            return

        name = self._current_combo_name()
        if not name:
            return

        if len(self._profiles) <= 1:
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

        self._profiles = [p for p in self._profiles if p.name != name]
        new_sel = self._profiles[0].name

        try:
            self._persist_selected_and_profiles(new_sel)
        except Exception as e:
            self._warn("Cancella", str(e))
            return

        self._rename_pending_old = None
        self._rebuild_combo(select_name=new_sel)
        self._load_fields_from_combo()
        self._activate_profile(new_sel, persist_selected=False)
        self._set_msg("Salvato", ttl_ms=1500)


def effective_default_projects_dir() -> Path:
    try:
        p = default_projects_dir()
        if p.exists() and p.is_dir():
            return p
    except Exception:
        pass
    return Path.home()
