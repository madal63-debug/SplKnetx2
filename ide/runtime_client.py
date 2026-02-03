from __future__ import annotations

import json
import socket
import struct
from dataclasses import dataclass
from typing import Any, Dict, Tuple
from ide.qt_jobs import run_job


@dataclass
class RuntimeProfile:
    name: str
    host: str
    port: int


class RuntimeClient:
    """Client TCP framed JSON: <uint32 le length> + JSON UTF-8."""

    def __init__(self) -> None:
        self.profile = RuntimeProfile("RunTimeLocal", "127.0.0.1", 1963)
        self._req_id = 1

    def set_profile(self, p: RuntimeProfile) -> None:
        self.profile = p

    def _next_req_id(self) -> int:
        self._req_id += 1
        if self._req_id > 2_000_000_000:
            self._req_id = 1
        return self._req_id

    def _send_cmd(self, cmd: str, payload: Dict[str, Any], timeout_s: float = 1.2) -> Dict[str, Any]:
        msg = {"cmd": cmd, "req_id": self._next_req_id(), "payload": payload}
        raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        framed = struct.pack("<I", len(raw)) + raw

        with socket.create_connection((self.profile.host, self.profile.port), timeout=timeout_s) as s:
            s.sendall(framed)

            hdr = s.recv(4)
            if len(hdr) != 4:
                raise RuntimeError("Header incompleto")
            (ln,) = struct.unpack("<I", hdr)
            if ln <= 0 or ln > 10_000_000:
                raise RuntimeError(f"Lunghezza risposta non valida: {ln}")

            data = b""
            while len(data) < ln:
                chunk = s.recv(ln - len(data))
                if not chunk:
                    raise RuntimeError("Connessione chiusa")
                data += chunk

        return json.loads(data.decode("utf-8"))

    def ping(self) -> Tuple[bool, str]:
        try:
            r = self._send_cmd("PING", {})
            if not r.get("ok", False):
                return False, "OFFLINE"
            st = (r.get("payload") or {}).get("runtime_state", "?")
            return True, str(st)
        except Exception:
            return False, "OFFLINE"

    def get_status(self) -> Dict[str, Any]:
        return self._send_cmd("GET_STATUS", {})

    def load_project(self, bundle_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send project bundle to runtime (MVP)."""
        return self._send_cmd("LOAD_PROJECT", bundle_payload, timeout_s=3.0)

    # ----------------
    # Async helpers
    # ----------------
    def ping_async(self, on_done, on_err=None):
        """Ping non bloccante. on_done riceve: (online: bool, state: str)."""
        return run_job(self.ping, on_ok=on_done, on_err=on_err)

    def load_project_async(self, bundle_payload: Dict[str, Any], on_done, on_err=None):
        """LOAD_PROJECT non bloccante. on_done riceve la response dict del runtime."""
        return run_job(self.load_project, bundle_payload, on_ok=on_done, on_err=on_err)
