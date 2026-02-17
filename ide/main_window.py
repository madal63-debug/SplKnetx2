# parte 9/9 — ide/main_window.py
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets
from ide.qt_jobs import run_job
from ide.compile_send import compile_project, send_project, compile_job, send_job
from ide.config import APP_NAME, ROLE_FILE, ROLE_TITLE, ROLE_NODE_KIND, ROLE_PAGE_ID, ROLE_PAGE_NAME, ROLE_SHEET_INDEX0
from ide.dialogs import AddPageDialog, NewProjectDialog, ProjectPickerDialog, SettingsWidget
from ide.page_tab import PageEditorTab
from ide.project_model import Project, add_page_to_project, create_project_skeleton, load_project
from ide.runtime_client import RuntimeClient, RuntimeProfile
from ide.utils import default_projects_dir, ensure_dir, folder_effectively_empty, load_json, utc_now_iso, write_json
from ide.connection_store import ensure_connections_file


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.settings = SettingsWidget()
        self.settings.clear_project()

        self.qs = QtCore.QSettings()
        self.project: Optional[Project] = None
        self.client = RuntimeClient()
        self._ping_inflight = False
        self._last_ping_ms = 0
        self._connected = False

        # Page tabs map: page_id -> PageEditorTab
        self._page_tabs: Dict[str, PageEditorTab] = {}

        # Bottom sheetbar state
        self._sheetbar_files: list[Path] = []
        self._sheetbar_page_id: Optional[str] = None
        self._sheetbar_page_name: Optional[str] = None

        # anti-loop selection sync
        self._sync_tree_guard = False

        self._build_toolbar()
        self._build_central()
        self._build_bottom_sheetbar()
        self._build_statusbar()
        self._build_style()
        self._build_menus()
        self._build_inflight = False


        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.refresh_status)
     # NON partiamo con ping automatici: si parte solo dopo "Connetti"
        self.timer.stop()

        self.refresh_status()
        self.populate_tree_empty()
        self.clear_sheetbar()

    # ----------------
    # UI build
    # ----------------
    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(16, 16))
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        # Toolbar minimale: SOLO runtime/diagnostica
        self.act_settings = QtGui.QAction("Settings", self)
        self.act_connect = QtGui.QAction("Connetti", self)
        self.act_compile = QtGui.QAction("Compila", self)
        self.act_download = QtGui.QAction("Send", self)  # se vuoi "Download", cambia qui

        tb.addAction(self.act_settings)
        tb.addAction(self.act_connect)
        tb.addSeparator()
        tb.addAction(self.act_compile)
        tb.addAction(self.act_download)

        # --- signals ---
        # Settings: se hai tabs + tab_settings, porta lì; altrimenti prova show_settings() se esiste
        if hasattr(self, "tabs") and hasattr(self, "tab_settings"):
            self.act_settings.triggered.connect(lambda: self.tabs.setCurrentWidget(self.tab_settings))
        else:
            fn_settings = getattr(self, "show_settings", None)
            if callable(fn_settings):
                self.act_settings.triggered.connect(fn_settings)

        # Connect/Disconnect toggle (STEP 5)
        self.act_connect.triggered.connect(self.toggle_connect)

        # Compile
        fn_compile = (
            getattr(self, "do_compile", None)
            or getattr(self, "compile_project", None)
            or getattr(self, "stub_compile", None)
        )
        if callable(fn_compile):
            self.act_compile.triggered.connect(fn_compile)

        # Send/Download
        fn_send = (
            getattr(self, "do_send", None)
            or getattr(self, "send_project", None)
            or getattr(self, "stub_download", None)
        )
        if callable(fn_send):
            self.act_download.triggered.connect(fn_send)

        # Testo iniziale coerente col flag self._connected
        if hasattr(self, "_set_connect_action_text"):
            self._set_connect_action_text()

    def _build_central(self) -> None:
        self.split = QtWidgets.QSplitter()
        self.split.setChildrenCollapsible(False)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setStyleSheet("QTreeWidget{font-size:11px;}")
        self.tree.itemClicked.connect(self.on_tree_clicked)

        # Right click context menu
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tree_context_menu)

        self.split.addWidget(self.tree)

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
        self.tabs.tabCloseRequested.connect(self.on_close_top_tab)
        self.tabs.currentChanged.connect(self.on_top_tab_changed)

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

        #self.output = QtWidgets.QPlainTextEdit()
        #self.output.setReadOnly(True)
        #self.output.setStyleSheet("font-size:11px;")
        #lay_out = QtWidgets.QVBoxLayout(self.tab_output)
        #lay_out.setContentsMargins(6, 6, 6, 6)
        #lay_out.addWidget(self.output)
        # ---- Output (log) + Diagnostics ----
        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("font-size:11px;")

        self.diag = QtWidgets.QTreeWidget()
        self.diag.setHeaderLabels(["Sev", "File", "Line", "Msg"])
        self.diag.setRootIsDecorated(False)
        self.diag.setAlternatingRowColors(True)
        self.diag.setStyleSheet("font-size:11px;")
        self.diag.itemDoubleClicked.connect(self.on_diag_double_clicked)

        out_split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        out_split.setChildrenCollapsible(False)
        out_split.addWidget(self.output)
        out_split.addWidget(self.diag)
        out_split.setSizes([220, 120])

        lay_out = QtWidgets.QVBoxLayout(self.tab_output)
        lay_out.setContentsMargins(6, 6, 6, 6)
        lay_out.addWidget(out_split)

        self.right_layout.addWidget(self.tabs, 1)

        self.split.addWidget(self.right)
        self.setCentralWidget(self.split)

        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([260, 900])

    def _build_bottom_sheetbar(self) -> None:
        self.sheetbar_wrap = QtWidgets.QWidget()
        self.sheetbar_wrap.setFixedHeight(28)
        hb = QtWidgets.QHBoxLayout(self.sheetbar_wrap)
        hb.setContentsMargins(6, 2, 6, 2)
        hb.setSpacing(2)

        self.btn_error_log = QtWidgets.QPushButton("Log Errori")
        self.btn_error_log.setFixedHeight(22)
        self.btn_error_log.setCheckable(True)
        self.btn_error_log.toggled.connect(self.toggle_error_log_window)
        hb.addWidget(self.btn_error_log, 0, QtCore.Qt.AlignLeft)

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

        hb.addWidget(self.sheetbar, 0, QtCore.Qt.AlignLeft)
        hb.addStretch(1)
        self.right_layout.addWidget(self.sheetbar_wrap, 0)

    def _build_statusbar(self) -> None:
        self.lbl_status = QtWidgets.QLabel("OFFLINE")
        sb = self.statusBar()
        sb.addWidget(self.lbl_status)

    def _ensure_error_log_window(self) -> None:
        if hasattr(self, "error_log_window"):
            return

        self.error_log_window = QtWidgets.QWidget(self, QtCore.Qt.Window)
        self.error_log_window.setWindowTitle("Log Errori")
        self.error_log_window.resize(760, 320)

        lay = QtWidgets.QVBoxLayout(self.error_log_window)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.error_log_view = QtWidgets.QPlainTextEdit()
        self.error_log_view.setReadOnly(True)
        self.error_log_view.setStyleSheet("font-size:11px;")
        lay.addWidget(self.error_log_view, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_error_log_copy = QtWidgets.QPushButton("Copia")
        self.btn_error_log_copy.clicked.connect(self.copy_error_log_text)
        btn_row.addWidget(self.btn_error_log_copy)
        lay.addLayout(btn_row)

        self.error_log_window.installEventFilter(self)
        self.error_log_view.setPlainText(self.output.toPlainText())

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if hasattr(self, "error_log_window") and obj is self.error_log_window and event.type() == QtCore.QEvent.Close:
            self.btn_error_log.blockSignals(True)
            self.btn_error_log.setChecked(False)
            self.btn_error_log.blockSignals(False)
        return super().eventFilter(obj, event)

    def toggle_error_log_window(self, checked: bool) -> None:
        self._ensure_error_log_window()
        if checked:
            self.error_log_view.setPlainText(self.output.toPlainText())
            self.error_log_window.show()
            self.error_log_window.raise_()
            self.error_log_window.activateWindow()
            return
        self.error_log_window.hide()

    def copy_error_log_text(self) -> None:
        if hasattr(self, "error_log_view"):
            QtWidgets.QApplication.clipboard().setText(self.error_log_view.toPlainText())

    def _build_style(self) -> None:
        self.setStyleSheet(
            "QMainWindow{font-size:11px;}"
            "QToolBar{spacing:4px;}"
            "QToolButton{padding:2px 6px;}"
            "QTabBar::tab{padding:4px 8px; margin:1px;}"
            "QSplitter::handle{background:#ddd;}"
        )

    def _build_menus(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("File")
        a_new = m_file.addAction("Nuovo progetto")
        a_open = m_file.addAction("Apri progetto")
        a_close = m_file.addAction("Chiudi progetto")
        m_file.addSeparator()
        a_save = m_file.addAction("Salva")
        a_save_all = m_file.addAction("Salva tutto")
        a_save_as = m_file.addAction("Salva con nome...")
        m_file.addSeparator()
        a_exit = m_file.addAction("Esci")

        a_save.setShortcut(QtGui.QKeySequence.Save)

        a_new.triggered.connect(self.new_project)
        a_open.triggered.connect(self.open_project)
        a_close.triggered.connect(self.close_project)
        a_save.triggered.connect(self.save_current)
        a_save_all.triggered.connect(self.save_all)
        a_save_as.triggered.connect(self.save_project_as)
        a_exit.triggered.connect(self.close)

        m_proj = mb.addMenu("Progetto")
        a_add_page = m_proj.addAction("Aggiungi pagina")
        m_proj.addSeparator()
        a_delete_proj = m_proj.addAction("Elimina progetto")

        a_add_page.triggered.connect(self.add_page)
        a_delete_proj.triggered.connect(self.delete_project)

    # ----------------
    # Logging
    # ----------------
    def log(self, s: str) -> None:
        self.output.appendPlainText(s)
        if hasattr(self, "error_log_view"):
            self.error_log_view.appendPlainText(s)

    # ----------------
    # Tree population
    # ----------------
    def populate_tree_empty(self) -> None:
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            root = QtWidgets.QTreeWidgetItem(["Nessun progetto aperto"])
            self.tree.addTopLevelItem(root)
            root.setExpanded(True)
        finally:
            self.tree.setUpdatesEnabled(True)
            
    def _find_sheet_tree_item(self, page_id: str, sheet_idx0: int) -> Optional[QtWidgets.QTreeWidgetItem]:
        def walk(node: QtWidgets.QTreeWidgetItem) -> Optional[QtWidgets.QTreeWidgetItem]:
            kind = node.data(0, ROLE_NODE_KIND)
            if kind == "SHEET":
                pid = str(node.data(0, ROLE_PAGE_ID) or "")
                sidx = int(node.data(0, ROLE_SHEET_INDEX0) or 0)
                if pid == str(page_id) and sidx == int(sheet_idx0):
                    return node
            for i in range(node.childCount()):
                r = walk(node.child(i))
                if r is not None:
                    return r
            return None

        for i in range(self.tree.topLevelItemCount()):
            r = walk(self.tree.topLevelItem(i))
            if r is not None:
                return r
        return None


    def _select_tree_sheet(self, page_id: str, sheet_idx0: int) -> None:
        it = self._find_sheet_tree_item(page_id, sheet_idx0)
        if it is None:
            return

        # espandi i parent per renderlo visibile
        p = it.parent()
        while p is not None:
            p.setExpanded(True)
            p = p.parent()

        # seleziona senza “clic” utente
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it, QtWidgets.QAbstractItemView.PositionAtCenter)


    def populate_tree_from_project(self) -> None:
        self.tree.setUpdatesEnabled(False)
        try:
            if not self.project:
                # NON chiamare populate_tree_empty() qui per evitare doppi wrapper,
                # ricostruisci direttamente il placeholder
                self.tree.clear()
                root = QtWidgets.QTreeWidgetItem(["Nessun progetto aperto"])
                self.tree.addTopLevelItem(root)
                root.setExpanded(True)
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
                sheets = init.get("sheets", [])
                single = len(sheets) == 1
                for idx, sh in enumerate(sheets):
                    self._add_sheet_item(it, init_id, init_name, sh, single, idx)

            for p in self.project.pages_json.get("pages", []):
                page_id = str(p.get("id", "P???"))
                page_name = str(p.get("name", page_id))
                pt = QtWidgets.QTreeWidgetItem([f"{page_id} ({page_name})"])
                pt.setData(0, ROLE_NODE_KIND, "PAGE")
                pt.setData(0, ROLE_PAGE_ID, page_id)
                pt.setData(0, ROLE_PAGE_NAME, page_name)
                root_pages.addChild(pt)
                sheets = p.get("sheets", [])
                single = len(sheets) == 1
                for idx, sh in enumerate(sheets):
                    self._add_sheet_item(pt, page_id, page_name, sh, single, idx)

            root_proj.setExpanded(True)
            root_pages.setExpanded(True)

        finally:
            self.tree.setUpdatesEnabled(True)
    def _human_tab_title(self, page_name: str, sheet_name: str, single_sheet: bool) -> str:
        # Se la pagina ha 1 solo foglio "Foglio1", mostro solo il nome pagina
        if single_sheet and sheet_name.strip().lower().startswith("foglio"):
            return page_name
        return f"{page_name}/{sheet_name}"



    def _add_sheet_item(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        page_id: str,
        page_name: str,
        sh: dict,
        single_sheet: bool,
        sheet_index_0: int = 0,
    ) -> None:
        sheet_id = str(sh.get("id", ""))
        sheet_name = str(sh.get("name", sheet_id or "Foglio"))
        label = f"{sheet_id} - {sheet_name}" if sheet_id else sheet_name
        child = QtWidgets.QTreeWidgetItem([label])

        file_rel = sh.get("file")
        if file_rel:
            child.setData(0, ROLE_FILE, str(file_rel))
            child.setData(0, ROLE_TITLE, self._human_tab_title(page_name, sheet_name, single_sheet))
            child.setData(0, ROLE_PAGE_ID, page_id)
            child.setData(0, ROLE_PAGE_NAME, page_name)
            child.setData(0, ROLE_SHEET_INDEX0, int(sheet_index_0))
            child.setData(0, ROLE_NODE_KIND, "SHEET")

        parent.addChild(child)


    # ----------------
    # Sheetbar
    # ----------------
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

        if self._sheetbar_page_id == page_id and self.sheetbar.count() > 0:
            if 0 <= selected_sheet_index_0 < self.sheetbar.count():
                self.sheetbar.blockSignals(True)
                self.sheetbar.setCurrentIndex(selected_sheet_index_0)
                self.sheetbar.blockSignals(False)
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
            self.sheetbar.setCurrentIndex(selected_sheet_index_0 if 0 <= selected_sheet_index_0 < self.sheetbar.count() else 0)

        self.sheetbar.blockSignals(False)
        self._sheetbar_page_id = page_id
        self._sheetbar_page_name = page_name

    # ----------------
    # Page tabs
    # ----------------
    def _page_sheets(self, page_id: str) -> list[Dict[str, Any]]:
        assert self.project is not None
        if page_id == "INIT":
            init = self.project.pages_json.get("init") or {}
            return list(init.get("sheets", []))
        for p in self.project.pages_json.get("pages", []):
            if str(p.get("id")) == page_id:
                return list(p.get("sheets", []))
        return []

    def _page_name(self, page_id: str) -> str:
        assert self.project is not None
        if page_id == "INIT":
            init = self.project.pages_json.get("init") or {}
            return str(init.get("name", "Init"))
        for p in self.project.pages_json.get("pages", []):
            if str(p.get("id")) == page_id:
                return str(p.get("name", page_id))
        return page_id

    def _open_page_tab(self, page_id: str) -> PageEditorTab:
        assert self.project is not None

        if page_id in self._page_tabs:
            tab = self._page_tabs[page_id]
            self.tabs.setCurrentWidget(tab)
            return tab

        page_name = self._page_name(page_id)
        sheets = self._page_sheets(page_id)

        tab = PageEditorTab(page_id, page_name, sheets, self.project.root)
        self._page_tabs[page_id] = tab
        self.tabs.insertTab(0, tab, page_name)
        self.tabs.setCurrentWidget(tab)
        return tab

    def _close_page_tab(self, page_id: str) -> None:
        tab = self._page_tabs.get(page_id)
        if not tab:
            return
        idx = self.tabs.indexOf(tab)
        if idx >= 0:
            self.tabs.removeTab(idx)
        self._page_tabs.pop(page_id, None)

    def _page_tab_from_widget(self, w: QtWidgets.QWidget) -> Optional[PageEditorTab]:
        if isinstance(w, PageEditorTab):
            return w
        return None

    # ----------------
    # Context menu
    # ----------------
    def on_tree_context_menu(self, pos: QtCore.QPoint) -> None:
        if not self.project:
            return
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
            menu.addSeparator()
            a_del_page = menu.addAction("Elimina pagina")
            if page_id == "INIT":
                a_del_page.setEnabled(False)
            a_del_page.triggered.connect(lambda: self.delete_page(page_id, page_name))

        elif kind == "SHEET":
            page_id = str(item.data(0, ROLE_PAGE_ID) or "")
            page_name = str(item.data(0, ROLE_PAGE_NAME) or "")
            sheet_idx0 = int(item.data(0, ROLE_SHEET_INDEX0) or 0)
            menu.addSeparator()
            a_del_page = menu.addAction("Elimina pagina")
            if page_id == "INIT":
                a_del_page.setEnabled(False)
            a_del_page.triggered.connect(lambda: self.delete_page(page_id, page_name))

            # (niente elimina foglio)
            _ = sheet_idx0

        else:
            return

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ----------------
    # Tree click
    # ----------------
    def on_tree_clicked(self, item: QtWidgets.QTreeWidgetItem, col: int) -> None:
        if not self.project:
            return

        kind = item.data(0, ROLE_NODE_KIND)

        if kind == "PAGE":
            page_id = item.data(0, ROLE_PAGE_ID)
            page_name = item.data(0, ROLE_PAGE_NAME)
            if page_id and page_name:
                self._open_page_tab(str(page_id))
                self.set_sheetbar_page(str(page_id), str(page_name), 0)
                self._select_tree_sheet(str(page_id), 0)
            return

        if kind == "SHEET":
            page_id = str(item.data(0, ROLE_PAGE_ID) or "")
            page_name = str(item.data(0, ROLE_PAGE_NAME) or "")
            sheet_idx0 = int(item.data(0, ROLE_SHEET_INDEX0) or 0)

            tab = self._open_page_tab(page_id)
            tab.set_current_sheet(sheet_idx0)

            self.set_sheetbar_page(page_id, page_name, sheet_idx0)
            self._select_tree_sheet(page_id, sheet_idx0)
            return

    def _select_tree_sheet(self, page_id: str, sheet_idx0: int) -> None:
        if self._sync_tree_guard:
            return
        try:
            self._sync_tree_guard = True
            root = self.tree.invisibleRootItem()
            for i in range(root.childCount()):
                proj = root.child(i)
                if not proj:
                    continue
                for j in range(proj.childCount()):
                    node = proj.child(j)
                    if not node or node.text(0) != "Pagine":
                        continue
                    for k in range(node.childCount()):
                        page_item = node.child(k)
                        if not page_item:
                            continue
                        if str(page_item.data(0, ROLE_PAGE_ID) or "") != page_id:
                            continue
                        page_item.setExpanded(True)
                        if 0 <= sheet_idx0 < page_item.childCount():
                            self.tree.setCurrentItem(page_item.child(sheet_idx0))
                        else:
                            self.tree.setCurrentItem(page_item)
                        return
        finally:
            self._sync_tree_guard = False

    # ----------------
    # Top tab close/change
    # ----------------
    def on_close_top_tab(self, idx: int) -> None:
        w = self.tabs.widget(idx)
        tab = self._page_tab_from_widget(w)
        if not tab:
            # non chiudo settings/output
            if w in (self.tab_settings, self.tab_output):
                return
            self.tabs.removeTab(idx)
            return

        if tab.is_dirty():
            r = QtWidgets.QMessageBox.question(
                self,
                "Chiudi pagina",
                f"Pagina '{tab.page_name}' ha modifiche non salvate.\nVuoi salvare?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
            )
            if r == QtWidgets.QMessageBox.Cancel:
                return
            if r == QtWidgets.QMessageBox.Yes:
                tab.save_current()

        self._close_page_tab(tab.page_id)
        self.on_top_tab_changed(self.tabs.currentIndex())

    def on_top_tab_changed(self, idx: int) -> None:
        if not hasattr(self, "tabs"):
            return

        w = self.tabs.widget(idx)

        # Se è una pagina editor con file_path → aggiorna sheetbar
        if w is not None and hasattr(w, "file_path"):
            try:
                page_id, page_name, sheet_idx0 = self.infer_page_from_file(w.file_path)
                if page_id and page_name and hasattr(self, "set_sheetbar_page"):
                   self.set_sheetbar_page(page_id, page_name, sheet_idx0)
            except Exception:
                pass
        return

        # Se sei su Settings/Output: NON disabilitare la sheetbar.
        # Deve restare cliccabile per cambiare foglio mentre leggi l'output.
        if w in (self.tab_settings, self.tab_output):
            return

        # Altri widget non-editor: non tocchiamo la sheetbar (la lasciamo come sta)
        return




    # ----------------
    # Sheetbar change
    # ----------------
    def on_sheetbar_changed(self, idx: int) -> None:
        if not self.project:
            return
        if idx < 0:
            return

        page_id = getattr(self, "_sheetbar_page_id", None)
        if not page_id:
            return

        # Apri (o riusa) il tab pagina
        tab = self._open_page_tab(str(page_id))
        self.tabs.setCurrentWidget(tab)

        # Chiedi al PageEditorTab di mostrare il foglio idx
        # (usiamo fallback per non “indovinare” un solo nome)
        for meth in ("set_sheet_index", "select_sheet", "open_sheet", "show_sheet", "set_current_sheet"):
            if hasattr(tab, meth):
                getattr(tab, meth)(idx)
                self._select_tree_sheet(str(page_id), int(idx))
                return


        # Se arrivi qui: PageEditorTab non espone ancora un metodo per cambiare foglio
        self.log("SHEETBAR: PageEditorTab non ha un metodo per cambiare foglio (serve set_sheet_index).")

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
        ensure_connections_file(self.project.root)
        self.settings.set_project(self.project.root)
        self.setWindowTitle(f"{APP_NAME} — {self.project.name}")
        self.populate_tree_from_project()
        self.clear_sheetbar()
        self._page_tabs.clear()
        self.log(f"OK: aperto progetto {self.project.root}")
        self.set_last_project_dir(self.project.root.parent)
        self.disconnect_runtime("project opened")


    def close_project(self) -> None:
        if not self.project:
            return

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
        tab = self._page_tab_from_widget(w)
        if tab:
            try:
                tab.save_current()
                self.log(f"Salvato: {tab.page_name} (foglio {tab.current_sheet_index0+1})")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Errore", str(e))

    def save_all(self) -> None:
        saved = 0
        for tab in list(self._page_tabs.values()):
            if tab.is_dirty():
                try:
                    tab.save_all()
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

            self.project.pages_json["pages"] = [p for p in pages_list if str(p.get("id")) != page_id]
            write_json(self.project.root / "pages.json", self.project.pages_json)

            wrapper = (self.project.root / "pages" / f"{page_id}.st").resolve()
            if wrapper.exists():
                wrapper.unlink(missing_ok=True)

            page_folder = (self.project.root / "pages" / page_id).resolve()
            if page_folder.exists():
                shutil.rmtree(page_folder, ignore_errors=True)

            self.project.pages_json = load_json(self.project.root / "pages.json")
            self.populate_tree_from_project()

            if self._sheetbar_page_id == page_id:
                self.clear_sheetbar()

            self.log(f"OK: eliminata pagina {page_id} ({page_name})")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore", str(e))
    # ------------------------------

    def _set_connect_action_text(self) -> None:
    # chiamare ogni volta che cambia stato
        self.act_connect.setText("Disconnetti" if self._connected else "Connetti")


    def _force_offline_ui(self) -> None:
        self.lbl_status.setText("OFFLINE")
        self.lbl_status.setStyleSheet("color:#777; font-weight:600;")

    def connect_runtime_once(self) -> None:
        if not self.project:
            return
        if getattr(self, "_ping_inflight", False):
            return

        self._ping_inflight = True
        self.act_connect.setEnabled(False)

        def _err(msg: str) -> None:
            self._ping_inflight = False
            self.act_connect.setEnabled(True)
            self._connected = False
            self._set_connect_action_text()
            self.timer.stop()
            self._force_offline_ui()
            self.log(f"CONNECT: ERROR — {msg}")

        self.client.ping_async(self._on_connect_ping_result, _err)


    def _on_connect_ping_result(self, result) -> None:
        self._ping_inflight = False
        self.act_connect.setEnabled(True)

        try:
            online, st = result
        except Exception:
            online, st = False, "OFFLINE"

        if online:
            self._connected = True
            self._set_connect_action_text()
            self.timer.start()
            self.lbl_status.setText(f"ONLINE — {st}")
            self.lbl_status.setStyleSheet("color:#0a0; font-weight:600;")
            self.log("CONNECT: OK")
        else:
            self._connected = False
            self._set_connect_action_text()
            self.timer.stop()
            self._force_offline_ui()
            self.log("CONNECT: OFFLINE")


    def disconnect_runtime(self, reason: str = "") -> None:
        """Disconnessione logica: stop ping e OFFLINE."""
        self._connected = False
        self._set_connect_action_text()
        self.timer.stop()
        self._force_offline_ui()
        if reason:
            self.log(f"DISCONNECT: {reason}")
        else:
            self.log("DISCONNECT")


    def toggle_connect(self) -> None:
        """Toolbar: Connetti <-> Disconnetti."""
        if not self.project:
            return
        if self._connected:
            self.disconnect_runtime("user")
        else:
            self.connect_runtime_once()
    # ----------------
    # Runtime
    # ----------------
    def on_profile_changed(self, p: RuntimeProfile) -> None:
        self.client.set_profile(p)
        if self.project and self._connected:
            self.refresh_status()



    def refresh_status(self) -> None:
        if not self.project or not self._connected:
            self._force_offline_ui()
            self._set_connect_action_text()
            return

        if getattr(self, "_ping_inflight", False):
            return

        self._ping_inflight = True

        def _err(_msg: str) -> None:
            self._ping_inflight = False
            self.disconnect_runtime("lost")

        self.client.ping_async(self._on_timer_ping_result, _err)


    def _on_timer_ping_result(self, result) -> None:
        self._ping_inflight = False

        try:
            online, st = result
        except Exception:
            online, st = False, "OFFLINE"

        if online:
            self.lbl_status.setText(f"ONLINE — {st}")
            self.lbl_status.setStyleSheet("color:#0a0; font-weight:600;")
        else:
            self.disconnect_runtime("lost")


    def stub_compile(self) -> None:
        compile_project(self)


    def stub_download(self) -> None:
        send_project(self)
    # ----------------
    # Diagnostics UI helpers
    # ----------------
    def diag_clear(self) -> None:
        if hasattr(self, "diag"):
            self.diag.clear()

    def diag_set(self, diags: list[dict]) -> None:
        if not hasattr(self, "diag"):
            return

        self.diag.setUpdatesEnabled(False)
        try:
            self.diag.clear()
            for d in diags or []:
                sev = str(d.get("sev", "") or "")
                f = str(d.get("file", "") or "")
                ln = int(d.get("line", 0) or 0)
                msg = str(d.get("msg", "") or "")
                it = QtWidgets.QTreeWidgetItem([sev, f, str(ln) if ln else "", msg])
                it.setData(0, QtCore.Qt.UserRole, f)          # file rel
                it.setData(0, QtCore.Qt.UserRole + 1, ln)     # line
                self.diag.addTopLevelItem(it)
            self.diag.resizeColumnToContents(0)
            self.diag.resizeColumnToContents(2)
        finally:
            self.diag.setUpdatesEnabled(True)

    def _infer_page_from_file_path(self, fp: Path) -> tuple[str, str, int]:
        """Ritorna (page_id, page_name, sheet_idx0)."""
        if not self.project:
            return "", "", 0

        root = self.project.root.resolve()
        try:
            rel = fp.resolve().relative_to(root).as_posix()
        except Exception:
            rel = fp.as_posix()

        # wrapper pages/P001.st
        if rel.startswith("pages/") and rel.count("/") == 1 and rel.endswith(".st"):
            pid = Path(rel).stem
            if pid == "INIT":
                init = self.project.pages_json.get("init") or {}
                return "INIT", str(init.get("name", "Init")), 0
            for p in self.project.pages_json.get("pages", []) or []:
                if str(p.get("id", "")) == pid:
                    return pid, str(p.get("name", pid)), 0

        # INIT sheets
        init = self.project.pages_json.get("init") or {}
        init_id = str(init.get("id", "INIT"))
        init_name = str(init.get("name", "Init"))
        for idx, sh in enumerate(init.get("sheets", []) or []):
            if str(sh.get("file", "")).replace("\\", "/") == rel.replace("\\", "/"):
                return init_id, init_name, idx

        # normal pages sheets
        for p in self.project.pages_json.get("pages", []) or []:
            pid = str(p.get("id", ""))
            pname = str(p.get("name", pid))
            for idx, sh in enumerate(p.get("sheets", []) or []):
                if str(sh.get("file", "")).replace("\\", "/") == rel.replace("\\", "/"):
                    return pid, pname, idx

        return "", "", 0

    def on_diag_double_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        if not self.project:
            return
        rel = str(item.data(0, QtCore.Qt.UserRole) or "")
        if not rel:
            return
        line = int(item.data(0, QtCore.Qt.UserRole + 1) or 0)

        fp = (self.project.root / rel).resolve()
        page_id, page_name, sheet_idx0 = self._infer_page_from_file_path(fp)
        if not page_id:
            self.log(f"NAV: file non mappato nel progetto: {rel}")
            return

        tab = self._open_page_tab(page_id)
        if hasattr(tab, "set_current_sheet"):
            tab.set_current_sheet(sheet_idx0)

        self.tabs.setCurrentWidget(tab)
        self.set_sheetbar_page(page_id, page_name, sheet_idx0)
        self._select_tree_sheet(page_id, sheet_idx0)

        # salto riga (step successivo): lo lasciamo “soft”
        if line and hasattr(tab, "goto_line"):
            try:
                tab.goto_line(int(line))
            except Exception:
                pass

    # ----------------
    # Async Compile/Send
    # ----------------
    def _set_build_actions_enabled(self, enabled: bool) -> None:
        if hasattr(self, "act_compile"):
            self.act_compile.setEnabled(enabled)
        if hasattr(self, "act_download"):
            self.act_download.setEnabled(enabled)

    def do_compile(self) -> None:
        self._start_build_job(kind="COMPILA")

    def do_send(self) -> None:
        self._start_build_job(kind="SEND")

    def _start_build_job(self, kind: str) -> None:
        if not self.project:
            self.log(f"{kind}: ERRORE — nessun progetto aperto")
            return

        if getattr(self, "_build_inflight", False):
            self.log(f"{kind}: già in corso")
            return

        prof = getattr(self.client, "profile", None)
        host = getattr(prof, "host", "127.0.0.1")
        port = int(getattr(prof, "port", 1963))

        self._build_inflight = True
        self._set_build_actions_enabled(False)
        self.diag_clear()
        self.log(f"{kind}: avvio… ({host}:{port})")

        root = self.project.root

        fn = compile_job if kind == "COMPILA" else send_job

        def _done(res: dict) -> None:
            self._build_inflight = False
            self._set_build_actions_enabled(True)

            ok = bool(res.get("ok", False))
            diags = res.get("diagnostics") or []
            info = res.get("project_info") or {}

            if ok:
                self.log(
                    f"{kind}: OK — files={info.get('files')} st={info.get('st_files')} "
                    f"bytes={info.get('bytes')} received={info.get('received_utc')}"
                )
            else:
                self.log(f"{kind}: FAIL — {res.get('error','?')}")

            # mostra diagnostics (WARN/ERROR con file+line)
            if diags:
                self.diag_set(diags)

        def _err(msg: str) -> None:
            self._build_inflight = False
            self._set_build_actions_enabled(True)
            self.log(f"{kind}: ERRORE — {msg}")

        self._last_build_job = run_job(fn, self.project.root, host, port, on_ok=_done, on_err=_err)


    def _set_build_actions_enabled(self, enabled: bool) -> None:
        self.act_compile.setEnabled(enabled)
        self.act_download.setEnabled(enabled)

    def do_compile(self) -> None:
        self._start_build_job("COMPILA")

    def do_send(self) -> None:
        self._start_build_job("SEND")

    def _start_build_job(self, kind: str) -> None:
        if not self.project:
            self.log(f"{kind}: ERRORE — nessun progetto aperto")
            return
        if self._build_inflight:
            self.log(f"{kind}: già in corso")
            return

        prof = getattr(self.client, "profile", None)
        host = getattr(prof, "host", "127.0.0.1")
        port = int(getattr(prof, "port", 1963))

        self._build_inflight = True
        self._set_build_actions_enabled(False)
        self.log(f"{kind}: avvio… ({host}:{port})")

        fn = compile_job if kind == "COMPILA" else send_job

        def _finish() -> None:
            self._build_inflight = False
            self._set_build_actions_enabled(True)

        def _done(res: dict) -> None:
            try:
                ok = bool(res.get("ok", False))
                info = res.get("project_info") or {}
                if ok:
                    self.log(
                        f"{kind}: OK — files={info.get('files')} st={info.get('st_files')} "
                        f"bytes={info.get('bytes')} received={info.get('received_utc')}"
                    )
                else:
                    self.log(f"{kind}: FAIL — {res.get('error','?')}")
            finally:
                _finish()

        def _err(msg: str) -> None:
            try:
                self.log(f"{kind}: ERRORE — {msg}")
            finally:
                _finish()

        self._last_build_job = run_job(fn, self.project.root, host, port, on_ok=_done, on_err=_err)

    # Compat: se la toolbar è ancora agganciata a questi nomi
    def stub_compile(self) -> None:
        self.do_compile()

    def stub_download(self) -> None:
        self.do_send()
