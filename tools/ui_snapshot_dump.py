from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from PySide6 import QtGui, QtWidgets

from ide.main_window import MainWindow


def _normalize_text(value: str) -> str:
  text = value.replace("&", " ")
  text = text.strip()
  return re.sub(r"\s+", " ", text)


def _action_shortcut(action: QtGui.QAction) -> str:
  return action.shortcut().toString(QtGui.QKeySequence.PortableText)


def _serialize_action(action: QtGui.QAction) -> dict[str, Any]:
  payload: dict[str, Any] = {
    "name": _normalize_text(action.text()),
    "shortcut": _normalize_text(_action_shortcut(action)),
  }
  submenu = action.menu()
  if submenu is not None:
    payload["submenu"] = _serialize_menu(submenu)
  return payload


def _serialize_menu(menu: QtWidgets.QMenu) -> list[dict[str, Any]]:
  items: list[dict[str, Any]] = []
  for action in menu.actions():
    if action.isSeparator():
      continue
    items.append(_serialize_action(action))
  return items


def dump_ui_snapshot() -> dict[str, Any]:
  app = QtWidgets.QApplication.instance()
  owns_app = app is None
  if app is None:
    app = QtWidgets.QApplication(sys.argv[:1])

  window = MainWindow()
  window.show()
  app.processEvents()

  menus: dict[str, list[dict[str, Any]]] = {}
  for menu_action in window.menuBar().actions():
    menu = menu_action.menu()
    if menu is None:
      continue
    menu_title = _normalize_text(menu_action.text())
    menus[menu_title] = _serialize_menu(menu)

  toolbar_actions: list[dict[str, str]] = []
  for toolbar in window.findChildren(QtWidgets.QToolBar):
    for action in toolbar.actions():
      if action.isSeparator():
        continue
      toolbar_actions.append(
        {
          "name": _normalize_text(action.text()),
          "shortcut": _normalize_text(_action_shortcut(action)),
        }
      )

  snapshot = {
    "menu_bar": menus,
    "toolbar": toolbar_actions,
  }

  window.close()
  if owns_app:
    app.quit()

  return snapshot


def main() -> int:
  parser = argparse.ArgumentParser(description="Dump UI menu/toolbar snapshot as JSON.")
  parser.add_argument("--out", help="Path to output JSON file.")
  args = parser.parse_args()

  payload = dump_ui_snapshot()
  rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

  if args.out:
    with open(args.out, "w", encoding="utf-8") as handle:
      handle.write(rendered)
      handle.write("\n")
  else:
    print(rendered)

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
