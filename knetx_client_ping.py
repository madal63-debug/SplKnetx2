"""KnetX SoftPLC - Minimal client to test LocalSim runtime.

- Connects to 127.0.0.1:1963
- Sends framed JSON commands (uint32 LE length + JSON)
- Prints responses.

Run (PowerShell, with venv active):
  python knetx_client_ping.py

Optional args:
  python knetx_client_ping.py --cmd PING
  python knetx_client_ping.py --cmd GET_STATUS
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
from typing import Any, Dict


def send_cmd(host: str, port: int, cmd: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    msg = {"cmd": cmd, "req_id": 1, "payload": payload}
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    framed = struct.pack("<I", len(raw)) + raw

    with socket.create_connection((host, port), timeout=2.0) as s:
        s.sendall(framed)

        # Read response frame
        hdr = s.recv(4)
        if len(hdr) != 4:
            raise RuntimeError("Short header")
        (ln,) = struct.unpack("<I", hdr)
        data = b""
        while len(data) < ln:
            chunk = s.recv(ln - len(data))
            if not chunk:
                raise RuntimeError("Socket closed")
            data += chunk

    return json.loads(data.decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1963)
    ap.add_argument("--cmd", default="PING")
    args = ap.parse_args()

    resp = send_cmd(args.host, args.port, args.cmd, {})
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
