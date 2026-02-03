# parte 1/1
# File: ide/connection_store.py
# Scopo: gestire profili di connessione (host/porta) per-progetto via <project>/connections.json
# Nota: modulo "puro" (no UI, no QSettings). Verrà usato dall'IDE.

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PORT = 1963
CONNECTIONS_FILENAME = "connections.json"
SCHEMA_VERSION_CONNECTIONS = 1


@dataclass
class ConnProfile:
    name: str
    host: str
    port: int


class ConnectionStore:
    """Lettura/scrittura atomica di <project>/connections.json.

    Struttura file:
      {
        "schema_version": 1,
        "selected": "Localhost",
        "profiles": [
          {"name":"Localhost","host":"127.0.0.1","port":1963},
          {"name":"WorkConnect","host":"0.0.0.0","port":1963}
        ]
      }

    Regole:
      - profili unici per name
      - almeno 1 profilo
      - selected deve esistere (altrimenti primo profilo)
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir.resolve()
        self.path = (self.project_dir / CONNECTIONS_FILENAME).resolve()

    # ---------- public API ----------
    def load_or_create(self) -> Dict[str, Any]:
        if not self.project_dir.exists():
            # in IDE il progetto dovrebbe esistere già, ma teniamo robusto
            self.project_dir.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            data = self.default_data()
            self.save(data)
            return data

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return self._normalize(data)
        except Exception:
            # Backup del file corrotto e ricreazione
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
        tmp.replace(self.path)

    def load_profiles(self) -> Tuple[str, List[ConnProfile]]:
        data = self.load_or_create()
        selected = str(data.get("selected", "") or "").strip()
        profiles = self._profiles_from_data(data)
        if not selected or selected not in {p.name for p in profiles}:
            selected = profiles[0].name
        return selected, profiles

    def save_profiles(self, selected: str, profiles: List[ConnProfile]) -> None:
        selected = (selected or "").strip()
        data = self._data_from_profiles(selected, profiles)
        self.save(data)

    # ---------- defaults/normalize ----------
    def default_data(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION_CONNECTIONS,
            "selected": "Localhost",
            "profiles": [
                {"name": "Localhost", "host": "127.0.0.1", "port": DEFAULT_PORT},
                # placeholder voluto: da reimpostare
                {"name": "WorkConnect", "host": "0.0.0.0", "port": DEFAULT_PORT},
            ],
        }

    def _normalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schema_version": int(data.get("schema_version", SCHEMA_VERSION_CONNECTIONS) or SCHEMA_VERSION_CONNECTIONS),
            "selected": str(data.get("selected", "") or "").strip(),
            "profiles": [],
        }

        profs = data.get("profiles")
        if not isinstance(profs, list):
            profs = []

        seen: set[str] = set()
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
            norm_profiles = list(self.default_data()["profiles"])  # type: ignore[index]

        out["profiles"] = norm_profiles

        selected = out["selected"]
        if not selected or selected not in {p["name"] for p in norm_profiles}:
            out["selected"] = norm_profiles[0]["name"]

        return out

    # ---------- conversions ----------
    def _profiles_from_data(self, data: Dict[str, Any]) -> List[ConnProfile]:
        out: List[ConnProfile] = []
        for p in data.get("profiles", []) or []:
            try:
                out.append(
                    ConnProfile(
                        name=str(p.get("name", "") or "").strip(),
                        host=str(p.get("host", "") or "").strip(),
                        port=int(p.get("port", DEFAULT_PORT)),
                    )
                )
            except Exception:
                continue
        # garantisci almeno 1 profilo
        if not out:
            d = self.default_data()
            out = self._profiles_from_data(d)
        return out

    def _data_from_profiles(self, selected: str, profiles: List[ConnProfile]) -> Dict[str, Any]:
        # unicità per name
        uniq: List[ConnProfile] = []
        seen: set[str] = set()
        for p in profiles:
            name = (p.name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            host = (p.host or "").strip()
            port = int(p.port)
            if port < 1 or port > 65535:
                port = DEFAULT_PORT
            uniq.append(ConnProfile(name=name, host=host, port=port))

        if not uniq:
            d = self.default_data()
            uniq = self._profiles_from_data(d)

        if not selected or selected not in {p.name for p in uniq}:
            selected = uniq[0].name

        return {
            "schema_version": SCHEMA_VERSION_CONNECTIONS,
            "selected": selected,
            "profiles": [{"name": p.name, "host": p.host, "port": int(p.port)} for p in uniq],
        }


# Convenience helpers (per chiamate rapide dall'IDE)

def ensure_connections_file(project_dir: Path) -> Path:
    """Crea connections.json se manca e ritorna il path."""
    store = ConnectionStore(project_dir)
    store.load_or_create()
    return store.path


def load_connection_profiles(project_dir: Path) -> Tuple[str, List[ConnProfile], Path]:
    store = ConnectionStore(project_dir)
    selected, profiles = store.load_profiles()
    return selected, profiles, store.path


def save_connection_profiles(project_dir: Path, selected: str, profiles: List[ConnProfile]) -> Path:
    store = ConnectionStore(project_dir)
    store.save_profiles(selected, profiles)
    return store.path