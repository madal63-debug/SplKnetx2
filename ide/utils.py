# parte 3/9 — ide/utils.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ide.config import SCHEMA_VERSION_PROJECT


def default_projects_dir() -> Path:
    candidates = [
        Path(r"C:\SplKnetx\projects"),
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


def st_sheet_template(pou_name: str, human_title: str) -> str:
    # intestazione più evidente
    return (
        f"(* -------------------- {human_title} — {pou_name} -------------------- *)\n\n"
        f"(* -------------------- FUNCTION_BLOCK {pou_name} -------------------- *)\n\n"
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


def default_project_json(name: str) -> Dict[str, Any]:
    return {
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
