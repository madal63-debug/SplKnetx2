# parte 8/9 — ide/page_tab.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtWidgets

from ide.editor_st import StEditor


class PageEditorTab(QtWidgets.QWidget):
    """Un tab = una pagina. I fogli si cambiano SOLO dalla sheetbar in basso."""

    def __init__(self, page_id: str, page_name: str, sheets: List[Dict[str, Any]], project_root: Path) -> None:
        super().__init__()
        self.page_id = page_id
        self.page_name = page_name
        self.sheets = sheets
        self.project_root = project_root

        self.current_sheet_index0 = 0
        self._editors: Dict[int, StEditor] = {}

        self.stack = QtWidgets.QStackedWidget()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack, 1)

        self._ensure_editor(0)
        self.stack.setCurrentIndex(0)

    def _sheet_file_path(self, idx0: int) -> Optional[Path]:
        if idx0 < 0 or idx0 >= len(self.sheets):
            return None
        rel = self.sheets[idx0].get("file")
        if not rel:
            return None
        return (self.project_root / str(rel)).resolve()

    def _ensure_editor(self, idx0: int) -> None:
        if idx0 in self._editors:
            return

        fp = self._sheet_file_path(idx0)
        if not fp:
            placeholder = QtWidgets.QLabel("(Foglio senza file)")
            placeholder.setAlignment(QtCore.Qt.AlignCenter)
            self.stack.addWidget(placeholder)
            return

        if fp.suffix.lower() == ".st":
            ed = StEditor(fp)
            self._editors[idx0] = ed
            self.stack.addWidget(ed)
        else:
            # FBD placeholder
            lab = QtWidgets.QLabel("Editor FBD non ancora implementato (MVP).\nFile creato correttamente.")
            lab.setAlignment(QtCore.Qt.AlignCenter)
            self.stack.addWidget(lab)

    def set_current_sheet(self, idx0: int) -> None:
        if idx0 < 0 or idx0 >= len(self.sheets):
            return
        self.current_sheet_index0 = idx0
        self._ensure_editor(idx0)

        # il widget nello stack non è necessariamente idx0 (dipende da placeholder), quindi cerco
        if idx0 in self._editors:
            w = self._editors[idx0]
            self.stack.setCurrentWidget(w)
        else:
            # fallback: prova indice (se combacia)
            if 0 <= idx0 < self.stack.count():
                self.stack.setCurrentIndex(idx0)

    def is_dirty(self) -> bool:
        for ed in self._editors.values():
            if ed.is_dirty():
                return True
        return False

    def save_current(self) -> None:
        ed = self._editors.get(self.current_sheet_index0)
        if ed:
            ed.save_to_disk()

    def save_all(self) -> int:
        n = 0
        for ed in self._editors.values():
            if ed.is_dirty():
                ed.save_to_disk()
                n += 1
        return n

    def current_file(self) -> Optional[Path]:
        ed = self._editors.get(self.current_sheet_index0)
        return ed.file_path if ed else None

    def current_editor(self) -> Optional[StEditor]:
        return self._editors.get(self.current_sheet_index0)
