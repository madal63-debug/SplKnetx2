"""KnetX SoftPLC - Project Skeleton Generator (MVP)

Creates a minimal project folder with:
- project.json
- pages.json (includes INIT + MAIN page definitions)
- vars.json (empty initial global vars list)
- monitors.json (empty initial presets)
- pages/INIT/{S001.st, INIT.st}
- pages/P001/{S001.st, P001.st}

Notes:
- Sheets are full IEC ST FUNCTION_BLOCKs (so user can declare locals safely).
- Wrappers INIT.st / P001.st are marked AUTO-GENERATED (do not edit).

Run:
  python tools/knetx_new_project.py --out C:\SplKnetx\projects\Demo1 --name Demo1

"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    # Wrapper is an FB that instantiates sheet FBs and calls them in order.
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


@dataclass
class ProjectConfig:
    name: str
    out_dir: Path


def create_project(cfg: ProjectConfig) -> None:
    root = cfg.out_dir
    ensure_dir(root)

    # Core dirs
    ensure_dir(root / "pages")
    ensure_dir(root / "data")

    # Memory sizes (from spec): 1MB PLC + 64KB retain
    project = {
        "schema_version": SCHEMA_VERSION,
        "name": cfg.name,
        "created_utc": utc_now_iso(),
        "languages": ["ST"],
        "targets": {
            "localsim": {"host": "127.0.0.1", "port": 1963},
            "linux_runtime": {"host": "<set in IDE settings>", "port": 1963},
        },
        "memory": {"plc_bytes": 1048576, "retain_bytes": 65536},
    }

    # INIT page is special (compiled into plc_init later)
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
        "var_global": [
            # Example entries (empty by default)
            # {"name":"G_Flag", "type":"BOOL", "init": false, "retain": false},
        ],
        "types": {
            "builtins": ["BOOL", "BYTE", "INT", "UINT", "UDINT", "REAL"],
        },
    }

    monitors_json = {
        "schema_version": 1,
        "presets": [
            # {"name":"Preset1", "items":["G_Flag","IN1","OUT3"]}
        ],
    }

    write_json(root / "project.json", project)
    write_json(root / "pages.json", pages)
    write_json(root / "vars.json", vars_json)
    write_json(root / "monitors.json", monitors_json)

    # ST files
    init_dir = root / "pages" / "INIT"
    p001_dir = root / "pages" / "P001"
    ensure_dir(init_dir)
    ensure_dir(p001_dir)

    (init_dir / "S001.st").write_text(st_sheet_template("INIT_S001", "Init / Foglio1"), encoding="utf-8")
    (p001_dir / "S001.st").write_text(st_sheet_template("P001_S001", "Main / Foglio1"), encoding="utf-8")

    # Wrappers (auto-generated placeholders for now)
    (root / "pages" / "INIT.st").write_text(st_wrapper_template("INIT", ["INIT_S001"]), encoding="utf-8")
    (root / "pages" / "P001.st").write_text(st_wrapper_template("P001", ["P001_S001"]), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Create a minimal KnetX SoftPLC project skeleton")
    ap.add_argument("--out", required=True, help="Output directory for the new project")
    ap.add_argument("--name", required=True, help="Project name")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out).expanduser().resolve()

    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"ERROR: cartella non vuota: {out_dir}")

    create_project(ProjectConfig(name=args.name, out_dir=out_dir))
    print(f"OK: progetto creato in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
