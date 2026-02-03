# parte 1/3 — runtime/localsim/knetx_runtime_sim.py
"""KnetX SoftPLC - LocalSim Runtime (MVP)

- TCP server on 127.0.0.1:1963 (default)
- Framing: uint32 little-endian length + JSON UTF-8
- Commands (MVP):
  PING, GET_STATUS, START, STOP, SHUTDOWN, GET_DIAG,
  READ_VARS, SET_VARS, FORCE_SET, FORCE_CLEAR, GET_FORCES,
  LOAD_PROJECT (NEW)

Run (PowerShell, with venv active):
  python knetx_runtime_sim.py

Note:
- This is the SIM runtime (no serial/bus).
- Single-instance is ensured by binding the TCP port.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


LOG = logging.getLogger("knetx.localsim")


def now_ms() -> int:
    return int(time.time() * 1000)


def now_utc_iso() -> str:
    # niente timezone awareness complicata: stringa leggibile
    # (se vuoi precisione: metti datetime.now(timezone.utc).isoformat(...))
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pack_msg(obj: Dict[str, Any]) -> bytes:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


async def read_exactly(reader: asyncio.StreamReader, n: int) -> bytes:
    data = await reader.readexactly(n)
    return data


@dataclass
class ForceTable:
    # owner_id -> { var_name -> value }
    by_owner: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # owner_id -> connection_id (for auto-clear on disconnect)
    owner_conn: Dict[str, str] = field(default_factory=dict)

    def set_values(self, owner_id: str, conn_id: str, values: Dict[str, Any]) -> None:
        self.owner_conn[owner_id] = conn_id
        bucket = self.by_owner.setdefault(owner_id, {})
        bucket.update(values)

    def clear(self, owner_id: str, names: Optional[list[str]] = None, clear_all: bool = False) -> None:
        if owner_id not in self.by_owner:
            return
        if clear_all or not names:
            self.by_owner.pop(owner_id, None)
            self.owner_conn.pop(owner_id, None)
            return
        bucket = self.by_owner.get(owner_id, {})
        for n in names:
            bucket.pop(n, None)
        if not bucket:
            self.by_owner.pop(owner_id, None)
            self.owner_conn.pop(owner_id, None)

    def clear_by_connection(self, conn_id: str) -> int:
        to_clear = [oid for oid, cid in self.owner_conn.items() if cid == conn_id]
        for oid in to_clear:
            self.by_owner.pop(oid, None)
            self.owner_conn.pop(oid, None)
        return len(to_clear)

    def snapshot(self) -> list[Dict[str, Any]]:
        out: list[Dict[str, Any]] = []
        for owner_id, vars_map in self.by_owner.items():
            for name, value in vars_map.items():
                out.append({"owner_id": owner_id, "name": name, "value": value})
        return out


@dataclass
class LocalSimRuntime:
    state: str = "STOP"  # STOP | RUN | ERROR
    start_monotonic: float = field(default_factory=time.monotonic)
    last_error: str = ""
    effective_scan_ms: float = 10.0
    round_time_ms: float = 0.0

    # Simple symbol table for SIM (name -> value)
    vars: Dict[str, Any] = field(default_factory=dict)

    forces: ForceTable = field(default_factory=ForceTable)

    # NEW: last project bundle received from IDE
    project_loaded: bool = False
    project_bundle: Optional[Dict[str, Any]] = None
    project_info: Dict[str, Any] = field(default_factory=dict)

    def uptime_ms(self) -> int:
        return int((time.monotonic() - self.start_monotonic) * 1000)

    def _set_state(self, new_state: str) -> None:
        self.state = new_state

    def handle_ping(self) -> Dict[str, Any]:
        return {
            "resp": "PONG",
            "runtime_state": self.state,
            "uptime_ms": self.uptime_ms(),
            "project_loaded": self.project_loaded,
            "caps": [
                "PING",
                "GET_STATUS",
                "START",
                "STOP",
                "GET_DIAG",
                "READ_VARS",
                "SET_VARS",
                "FORCE_SET",
                "FORCE_CLEAR",
                "GET_FORCES",
                "LOAD_PROJECT",
                "SHUTDOWN",
            ],
        }

    def handle_get_status(self) -> Dict[str, Any]:
        return {
            "runtime_state": self.state,
            "last_error": self.last_error,
            "effective_scan_ms": self.effective_scan_ms,
            "round_time_ms": self.round_time_ms,
            "uptime_ms": self.uptime_ms(),
            "project_loaded": self.project_loaded,
            "project_info": self.project_info,
        }

    def handle_start(self) -> Dict[str, Any]:
        if self.state == "ERROR":
            raise RuntimeError("Runtime in ERROR: STOP then clear error (MVP: restart LocalSim)")
        # MVP: richiediamo progetto caricato prima di RUN (evita RUN a vuoto)
        if not self.project_loaded:
            raise RuntimeError("No project loaded. Use LOAD_PROJECT first.")
        self._set_state("RUN")
        return {"runtime_state": self.state}

    def handle_stop(self) -> Dict[str, Any]:
        self._set_state("STOP")
        return {"runtime_state": self.state}

    def handle_get_diag(self) -> Dict[str, Any]:
        # SIM: no boards yet
        return {
            "runtime_state": self.state,
            "round_time_ms": self.round_time_ms,
            "effective_scan_ms": self.effective_scan_ms,
            "boards": [],
        }

    def handle_read_vars(self, names: list[str]) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        # Apply output of forces on read (so IDE sees forced values too)
        forced_map: Dict[str, Any] = {}
        for entry in self.forces.snapshot():
            forced_map[entry["name"]] = entry["value"]
        for n in names:
            if n in forced_map:
                values[n] = forced_map[n]
            else:
                values[n] = self.vars.get(n, None)
        return {"values": values}

    def handle_set_vars(self, values: Dict[str, Any]) -> Dict[str, Any]:
        # In SIM this is allowed; in real runtime this may be restricted.
        self.vars.update(values)
        return {"count": len(values)}

    # ----------------------------
    # NEW: LOAD_PROJECT
    # ----------------------------
    def handle_load_project(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Receives a project bundle from IDE.

        Expected payload:
          {
            "project": {...},
            "pages": {...},
            "vars": {...},
            "sources": {"pages/P001/S001.st": "...", ...},
            "meta": {...}
          }
        """
        project = payload.get("project")
        pages = payload.get("pages")
        varsj = payload.get("vars")
        sources = payload.get("sources")
        meta = payload.get("meta") or {}

        if not isinstance(project, dict):
            raise ValueError("payload.project must be object")
        if not isinstance(pages, dict):
            raise ValueError("payload.pages must be object")
        if not isinstance(varsj, dict):
            raise ValueError("payload.vars must be object")
        if not isinstance(sources, dict):
            raise ValueError("payload.sources must be object")

        # validate sources
        total_bytes = 0
        st_count = 0
        for k, v in sources.items():
            if not isinstance(k, str) or not k:
                raise ValueError("payload.sources keys must be non-empty strings")
            if not isinstance(v, str):
                raise ValueError("payload.sources values must be strings")
            # rough size accounting (utf-8)
            b = len(v.encode("utf-8"))
            total_bytes += b
            if k.lower().endswith(".st"):
                st_count += 1

        # store
        self.project_bundle = {
            "project": project,
            "pages": pages,
            "vars": varsj,
            "sources": sources,
            "meta": meta,
            "received_utc": now_utc_iso(),
        }
        self.project_loaded = True

        # summary info for UI
        p_name = str(project.get("name", ""))
        n_pages = 0
        n_sheets = 0
        try:
            if isinstance(pages.get("init"), dict):
                n_pages += 1
                n_sheets += len(pages.get("init", {}).get("sheets", []) or [])
            n_pages += len(pages.get("pages", []) or [])
            for p in (pages.get("pages", []) or []):
                if isinstance(p, dict):
                    n_sheets += len(p.get("sheets", []) or [])
        except Exception:
            pass

        self.project_info = {
            "name": p_name,
            "pages": n_pages,
            "sheets": n_sheets,
            "files": len(sources),
            "st_files": st_count,
            "bytes": total_bytes,
            "received_utc": self.project_bundle["received_utc"],
        }

        # MVP policy: load project forces STOP
        self._set_state("STOP")

        return {
            "loaded": True,
            "project_info": self.project_info,
        }


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, rt: LocalSimRuntime, shutdown_evt: asyncio.Event) -> None:
    peer = writer.get_extra_info("peername")
    conn_id = f"{peer}-{now_ms()}"
    LOG.info("Client connected: %s", peer)

    async def send(obj: Dict[str, Any]) -> None:
        writer.write(pack_msg(obj))
        await writer.drain()

    try:
        while not shutdown_evt.is_set():
            # Read framed JSON
            try:
                header = await read_exactly(reader, 4)
            except asyncio.IncompleteReadError:
                break
            (ln,) = struct.unpack("<I", header)
            if ln <= 0 or ln > 10_000_000:
                await send({"ok": False, "req_id": -1, "payload": {}, "error": f"Invalid length: {ln}"})
                break
            raw = await read_exactly(reader, ln)
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception as e:
                await send({"ok": False, "req_id": -1, "payload": {}, "error": f"JSON parse error: {e}"})
                continue

            cmd = msg.get("cmd")
            req_id = msg.get("req_id")
            payload = msg.get("payload") or {}

            if not isinstance(cmd, str) or not isinstance(req_id, int) or not isinstance(payload, dict):
                await send({"ok": False, "req_id": req_id if isinstance(req_id, int) else -1, "payload": {}, "error": "Invalid message schema"})
                continue

            try:
                # Dispatch
                if cmd == "PING":
                    out = rt.handle_ping()
                elif cmd == "GET_STATUS":
                    out = rt.handle_get_status()
                elif cmd == "START":
                    out = rt.handle_start()
                elif cmd == "STOP":
                    out = rt.handle_stop()
                elif cmd == "GET_DIAG":
                    out = rt.handle_get_diag()
                elif cmd == "READ_VARS":
                    names = payload.get("names", [])
                    if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
                        raise ValueError("payload.names must be array of strings")
                    out = rt.handle_read_vars(names)
                elif cmd == "SET_VARS":
                    values = payload.get("values", {})
                    if not isinstance(values, dict):
                        raise ValueError("payload.values must be object")
                    out = rt.handle_set_vars(values)
                elif cmd == "FORCE_SET":
                    owner_id = payload.get("owner_id")
                    values = payload.get("values", {})
                    if not isinstance(owner_id, str) or not owner_id:
                        raise ValueError("payload.owner_id required")
                    if not isinstance(values, dict):
                        raise ValueError("payload.values must be object")
                    rt.forces.set_values(owner_id=owner_id, conn_id=conn_id, values=values)
                    out = {"owner_id": owner_id, "count": len(values)}
                elif cmd == "FORCE_CLEAR":
                    owner_id = payload.get("owner_id")
                    if not isinstance(owner_id, str) or not owner_id:
                        raise ValueError("payload.owner_id required")
                    clear_all = bool(payload.get("all", False))
                    names = payload.get("names")
                    if names is not None:
                        if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
                            raise ValueError("payload.names must be array of strings")
                    rt.forces.clear(owner_id=owner_id, names=names, clear_all=clear_all)
                    out = {"owner_id": owner_id}
                elif cmd == "GET_FORCES":
                    out = {"forces": rt.forces.snapshot()}
                elif cmd == "LOAD_PROJECT":
                    out = rt.handle_load_project(payload)
                elif cmd == "SHUTDOWN":
                    # LocalSim only: graceful shutdown
                    out = {"shutting_down": True}
                    await send({"ok": True, "req_id": req_id, "payload": out, "error": ""})
                    shutdown_evt.set()
                    break
                else:
                    raise ValueError(f"Unknown cmd: {cmd}")

                await send({"ok": True, "req_id": req_id, "payload": out, "error": ""})

            except Exception as e:
                await send({"ok": False, "req_id": req_id, "payload": {}, "error": str(e)})

    finally:
        # Fail-safe: if connection drops, clear all forces owned by this connection
        cleared = rt.forces.clear_by_connection(conn_id)
        if cleared:
            LOG.warning("Cleared %d force owner(s) due to disconnect: %s", cleared, peer)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        LOG.info("Client disconnected: %s", peer)


async def main_async(host: str, port: int) -> int:
    rt = LocalSimRuntime()
    shutdown_evt = asyncio.Event()

    server = await asyncio.start_server(lambda r, w: handle_client(r, w, rt, shutdown_evt), host=host, port=port)
    sockets = server.sockets or []
    bind_info = ", ".join(str(s.getsockname()) for s in sockets)
    LOG.info("LocalSim listening on %s", bind_info)

    async with server:
        # Wait until SHUTDOWN
        await shutdown_evt.wait()
        LOG.info("Shutdown requested. Closing server...")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="KnetX LocalSim Runtime (MVP)")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=1963, help="Bind port (default: 1963)")
    p.add_argument("--log", default="INFO", help="Log level (DEBUG/INFO/WARN/ERROR)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        return asyncio.run(main_async(args.host, args.port))
    except OSError as e:
        # Most common: port already in use => instance already running
        LOG.error("Cannot bind %s:%s (%s)", args.host, args.port, e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())