# parte 5/9 — ide/project_model.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from ide.utils import (
    default_project_json,
    ensure_dir,
    folder_effectively_empty,
    load_json,
    make_fbd_placeholder,
    next_page_id,
    st_sheet_template,
    st_wrapper_template,
    utc_now_iso,
    write_json,
)


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
    # INIT = 1 foglio
    # Main (P001) = 2 fogli
    # Pag_IA (P002) = 2 fogli: S001 "Dichiarazioni Utente", S002 "Risultato Elaborazione IA"
    if out_dir.exists() and not folder_effectively_empty(out_dir):
        raise RuntimeError(f"Cartella non vuota: {out_dir}")

    ensure_dir(out_dir)
    ensure_dir(out_dir / "pages")
    ensure_dir(out_dir / "data")

    project = default_project_json(name)

    pages = {
        "schema_version": 1,
        "init": {
            "id": "INIT",
            "name": "Init",
            "sheets": [
                {"id": "S001", "name": "Foglio1", "file": "pages/INIT/S001.st", "pou": "INIT_S001"},
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
            },
            {
                "id": "P002",
                "name": "Pag_IA",
                "enabled": True,
                "language": "ST",
                "sheets": [
                    {
                        "id": "S001",
                        "name": "Dichiarazioni Utente",
                        "file": "pages/P002/S001.st",
                        "pou": "P002_S001",
                    },
                    {
                        "id": "S002",
                        "name": "Risultato Elaborazione IA",
                        "file": "pages/P002/S002.st",
                        "pou": "P002_S002",
                    },
                ],
            },
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
    p002_dir = out_dir / "pages" / "P002"
    ensure_dir(init_dir)
    ensure_dir(p001_dir)
    ensure_dir(p002_dir)

    (init_dir / "S001.st").write_text(st_sheet_template("INIT_S001", "Init"), encoding="utf-8")

    (p001_dir / "S001.st").write_text(st_sheet_template("P001_S001", "Main"), encoding="utf-8")
    (p001_dir / "S002.st").write_text(st_sheet_template("P001_S002", "Main"), encoding="utf-8")

    (p002_dir / "S001.st").write_text(st_sheet_template("P002_S001", "Dichiarazioni Utente"), encoding="utf-8")
    (p002_dir / "S002.st").write_text(st_sheet_template("P002_S002", "Risultato Elaborazione IA"), encoding="utf-8")

    (out_dir / "pages" / "INIT.st").write_text(st_wrapper_template("INIT", ["INIT_S001"]), encoding="utf-8")
    (out_dir / "pages" / "P001.st").write_text(
        st_wrapper_template("P001", ["P001_S001", "P001_S002"]), encoding="utf-8"
    )
    (out_dir / "pages" / "P002.st").write_text(
        st_wrapper_template("P002", ["P002_S001", "P002_S002"]), encoding="utf-8"
    )


def add_page_to_project(project: Project, page_name: str, language: str) -> str:
    # Nuove pagine: 2 fogli di default (S001, S002)
    language = (language or "ST").upper()
    if language not in {"ST", "FBD"}:
        language = "ST"

    pages_json = project.pages_json
    pid = next_page_id(pages_json)

    ensure_dir(project.root / "pages" / pid)

    page_entry: Dict[str, Any] = {"id": pid, "name": page_name, "enabled": True, "language": language, "sheets": []}

    if language == "ST":
        rel1 = f"pages/{pid}/S001.st"
        pou1 = f"{pid}_S001"
        page_entry["sheets"].append({"id": "S001", "name": "Foglio1", "file": rel1, "pou": pou1})
        (project.root / rel1).write_text(st_sheet_template(pou1, page_name), encoding="utf-8")

        rel2 = f"pages/{pid}/S002.st"
        pou2 = f"{pid}_S002"
        page_entry["sheets"].append({"id": "S002", "name": "Foglio2", "file": rel2, "pou": pou2})
        (project.root / rel2).write_text(st_sheet_template(pou2, page_name), encoding="utf-8")

        (project.root / "pages" / f"{pid}.st").write_text(st_wrapper_template(pid, [pou1, pou2]), encoding="utf-8")
    else:
        rel1 = f"pages/{pid}/S001.fbd.json"
        rel2 = f"pages/{pid}/S002.fbd.json"
        page_entry["sheets"].append({"id": "S001", "name": "Foglio1", "file": rel1})
        page_entry["sheets"].append({"id": "S002", "name": "Foglio2", "file": rel2})
        write_json(project.root / rel1, make_fbd_placeholder(pid, "S001"))
        write_json(project.root / rel2, make_fbd_placeholder(pid, "S002"))

    pages_json.setdefault("pages", []).append(page_entry)
    write_json(project.root / "pages.json", pages_json)
    project.pages_json = load_json(project.root / "pages.json")
    return pid
