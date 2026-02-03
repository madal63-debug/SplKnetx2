from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ide.runtime_client import RuntimeClient, RuntimeProfile


# -----------------------
# Helpers
# -----------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _collect_paths_from_pages_json(pages: Dict[str, Any]) -> Tuple[set[str], list[str]]:
    """Return (relative_paths_set, warnings)."""
    rels: set[str] = set()
    warnings: list[str] = []

    def add_file(rel: Any) -> None:
        if isinstance(rel, str) and rel.strip():
            rels.add(rel.replace("\\", "/"))

    init = pages.get("init")
    if isinstance(init, dict):
        for sh in init.get("sheets", []) or []:
            if isinstance(sh, dict):
                add_file(sh.get("file"))

    for p in pages.get("pages", []) or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id", ""))
        if pid:
            add_file(f"pages/{pid}.st")  # wrapper
        for sh in p.get("sheets", []) or []:
            if isinstance(sh, dict):
                add_file(sh.get("file"))

    add_file("pages/INIT.st")  # wrapper init

    if not rels:
        warnings.append("Nessun file trovato in pages.json")

    return rels, warnings


def build_project_bundle(project_root: Path) -> Dict[str, Any]:
    """Build payload for RuntimeClient.load_project()."""
    project_root = project_root.resolve()

    project_json = _load_json(project_root / "project.json")
    pages_json = _load_json(project_root / "pages.json")
    vars_json = _load_json(project_root / "vars.json")

    rel_paths, warnings = _collect_paths_from_pages_json(pages_json)

    sources: Dict[str, str] = {}
    missing: list[str] = []
    total_bytes = 0

    for rel in sorted(rel_paths):
        fp = (project_root / rel).resolve()
        try:
            txt = fp.read_text(encoding="utf-8")
            sources[rel] = txt
            total_bytes += len(txt.encode("utf-8"))
        except FileNotFoundError:
            missing.append(rel)
        except Exception as e:
            raise RuntimeError(f"Errore lettura {rel}: {e}")

    if missing:
        miss = "\n".join(missing[:20])
        more = "" if len(missing) <= 20 else f"\n...(+{len(missing)-20})"
        raise RuntimeError(f"File mancanti nel progetto (pages.json):\n{miss}{more}")

    return {
        "project": project_json,
        "pages": pages_json,
        "vars": vars_json,
        "sources": sources,
        "meta": {
            "sent_utc": _utc_now_iso(),
            "warnings": warnings,
            "total_bytes": total_bytes,
        },
    }


# -----------------------
# Diagnostics normalize
# -----------------------
def _as_rel_posix(project_root: Path, p: str) -> str:
    try:
        pp = Path(p)
        if not pp.is_absolute():
            return pp.as_posix().replace("\\", "/")
        pr = project_root.resolve()
        rel = pp.resolve().relative_to(pr)
        return rel.as_posix().replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _norm_sev(s: Any) -> str:
    t = str(s or "").strip().upper()
    if t in ("WARNING", "WARN", "W"):
        return "WARN"
    if t in ("ERROR", "ERR", "E"):
        return "ERROR"
    if t in ("INFO", "I"):
        return "INFO"
    return t or "INFO"


def _parse_diag_line(line: str) -> Dict[str, Any] | None:
    s = (line or "").strip()
    if not s:
        return None

    m = re.match(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.*)$", s)
    if m:
        return {"sev": "ERROR", "file": m.group("file"), "line": int(m.group("line")), "col": int(m.group("col")), "msg": m.group("msg")}

    m = re.match(r"^(?P<file>[^:]+):(?P<line>\d+):\s*(?P<msg>.*)$", s)
    if m:
        return {"sev": "ERROR", "file": m.group("file"), "line": int(m.group("line")), "col": 0, "msg": m.group("msg")}

    m = re.match(r"^(?P<file>.+)\((?P<line>\d+)\):\s*(?P<msg>.*)$", s)
    if m:
        return {"sev": "ERROR", "file": m.group("file"), "line": int(m.group("line")), "col": 0, "msg": m.group("msg")}

    return None


def extract_diagnostics(project_root: Path, resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    diags: List[Dict[str, Any]] = []
    payload = (resp.get("payload") or {}) if isinstance(resp, dict) else {}

    raw = payload.get("diagnostics") or payload.get("diags")
    if raw is None:
        errs = payload.get("errors")
        warns = payload.get("warnings")
        if isinstance(errs, list) or isinstance(warns, list):
            raw = []
            if isinstance(errs, list):
                for x in errs:
                    raw.append({"severity": "ERROR", **(x if isinstance(x, dict) else {"message": str(x)})})
            if isinstance(warns, list):
                for x in warns:
                    raw.append({"severity": "WARN", **(x if isinstance(x, dict) else {"message": str(x)})})

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                d = _parse_diag_line(item)
                if d:
                    d["file"] = _as_rel_posix(project_root, d.get("file", ""))
                    diags.append(d)
                else:
                    diags.append({"sev": "ERROR", "file": "", "line": 0, "col": 0, "msg": item})
                continue

            if isinstance(item, dict):
                sev = _norm_sev(item.get("sev") or item.get("severity") or item.get("level"))
                fp = item.get("file") or item.get("path") or ""
                msg = item.get("msg") or item.get("message") or ""
                line = int(item.get("line") or 0)
                col = int(item.get("col") or item.get("column") or 0)
                diags.append(
                    {
                        "sev": sev,
                        "file": _as_rel_posix(project_root, str(fp)) if fp else "",
                        "line": line,
                        "col": col,
                        "msg": str(msg),
                    }
                )

    if not diags:
        err = resp.get("error") if isinstance(resp, dict) else None
        if isinstance(err, str) and err.strip():
            d = _parse_diag_line(err)
            if d:
                d["file"] = _as_rel_posix(project_root, d.get("file", ""))
                diags.append(d)
            else:
                diags.append({"sev": "ERROR", "file": "", "line": 0, "col": 0, "msg": err})

    return diags


# -----------------------
# ST sanity-check (MVP)
# -----------------------
def _strip_st_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    in_block = False

    while i < n:
        if in_block:
            if text.startswith("*)", i):
                in_block = False
                i += 2
            else:
                i += 1
            continue

        if text.startswith("(*", i):
            in_block = True
            i += 2
            continue

        if text.startswith("//", i):
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        out.append(text[i])
        i += 1

    return "".join(out)


def _st_if_balance_check(sources: Dict[str, str]) -> List[Dict[str, Any]]:
    diags: List[Dict[str, Any]] = []
    for rel, txt in (sources or {}).items():
        if not str(rel).lower().endswith(".st"):
            continue

        clean = _strip_st_comments(txt)
        stack: list[int] = []

        for ln, line in enumerate(clean.splitlines(), start=1):
            if re.search(r"\bEND_IF\b", line, flags=re.IGNORECASE):
                if stack:
                    stack.pop()
                else:
                    diags.append({"sev": "ERROR", "file": rel, "line": ln, "col": 0, "msg": "END_IF senza IF corrispondente"})
                continue

            if re.search(r"\bIF\b", line, flags=re.IGNORECASE):
                stack.append(ln)

        for start_ln in stack:
            diags.append({"sev": "ERROR", "file": rel, "line": start_ln, "col": 0, "msg": "IF senza END_IF"})

    return diags


# -----------------------
# Jobs (async-safe)
# -----------------------
def _mk_client(host: str, port: int) -> RuntimeClient:
    c = RuntimeClient()
    c.set_profile(RuntimeProfile("job", host, int(port)))
    return c


def compile_job(project_root: Path, host: str, port: int) -> Dict[str, Any]:
    """
    Job-safe: niente Qt.
    1) build bundle
    2) sanity-check ST (MVP)
    3) LOAD_PROJECT su runtime
    """
    try:
        project_root = project_root.resolve()
        bundle = build_project_bundle(project_root)

        local_diags = _st_if_balance_check(bundle.get("sources") or {})
        if local_diags:
            return {
                "ok": False,
                "error": "ST check failed",
                "diagnostics": local_diags,
                "project_info": {},
                "meta": bundle.get("meta") or {},
            }

        client = _mk_client(host, int(port))
        resp = client.load_project(bundle)

        ok = bool(resp.get("ok", False))
        info = (resp.get("payload") or {}).get("project_info") or {}
        diags = extract_diagnostics(project_root, resp)

        return {
            "ok": ok,
            "error": "" if ok else str(resp.get("error", "")) or "compile failed",
            "diagnostics": diags,
            "project_info": info,
            "meta": bundle.get("meta") or {},
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "diagnostics": [{"sev": "ERROR", "file": "", "line": 0, "col": 0, "msg": str(e)}],
            "project_info": {},
            "meta": {},
        }


def send_job(project_root: Path, host: str, port: int) -> Dict[str, Any]:
    """MVP: SEND usa la stessa pipeline (include sanity-check)."""
    return compile_job(project_root, host, port)


# -------------------------------------------------------------------
# Back-compat: importati da main_window (anche se oggi usi l’async)
# -------------------------------------------------------------------
def compile_project(window: Any) -> None:
    if not getattr(window, "project", None):
        window.log("COMPILA: ERRORE — nessun progetto aperto")
        return

    prof = getattr(getattr(window, "client", None), "profile", None)
    host = getattr(prof, "host", "127.0.0.1")
    port = int(getattr(prof, "port", 1963))

    res = compile_job(window.project.root, host, port)
    if res.get("ok", False):
        info = res.get("project_info") or {}
        window.log(
            "COMPILA: OK — "
            f"files={info.get('files')} st={info.get('st_files')} "
            f"bytes={info.get('bytes')} received={info.get('received_utc')}"
        )
    else:
        window.log(f"COMPILA: FAIL — {res.get('error','?')}")

    diags = res.get("diagnostics") or []
    if diags and hasattr(window, "diag_set"):
        window.diag_set(diags)


def send_project(window: Any) -> None:
    if not getattr(window, "project", None):
        window.log("SEND: ERRORE — nessun progetto aperto")
        return

    prof = getattr(getattr(window, "client", None), "profile", None)
    host = getattr(prof, "host", "127.0.0.1")
    port = int(getattr(prof, "port", 1963))

    res = send_job(window.project.root, host, port)
    if res.get("ok", False):
        info = res.get("project_info") or {}
        window.log(
            "SEND: OK — "
            f"files={info.get('files')} st={info.get('st_files')} "
            f"bytes={info.get('bytes')} received={info.get('received_utc')}"
        )
    else:
        window.log(f"SEND: FAIL — {res.get('error','?')}")

    diags = res.get("diagnostics") or []
    if diags and hasattr(window, "diag_set"):
        window.diag_set(diags)
