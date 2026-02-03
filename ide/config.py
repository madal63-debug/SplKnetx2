# parte 2/9 — ide/config.py
from __future__ import annotations

from PySide6 import QtCore

APP_NAME = "KnetX IDE-lite"
SCHEMA_VERSION_PROJECT = 1

# Tree item roles
ROLE_TITLE = int(QtCore.Qt.UserRole + 1)
ROLE_FILE = int(QtCore.Qt.UserRole)
ROLE_PAGE_ID = int(QtCore.Qt.UserRole + 2)
ROLE_PAGE_NAME = int(QtCore.Qt.UserRole + 3)
ROLE_SHEET_INDEX0 = int(QtCore.Qt.UserRole + 4)
ROLE_NODE_KIND = int(QtCore.Qt.UserRole + 10)  # 'PAGES_ROOT' | 'PAGE' | 'SHEET'

# Editor defaults
CODE_FONT_FAMILY = "Verdana"
CODE_FONT_SIZE_PT = 8
LINE_NUMBER_GAP_CM = 0.5
