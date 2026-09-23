"""Cola de trabajos en segundo plano (render, IA, subida, piloto automático)."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

_heavy = ThreadPoolExecutor(max_workers=1)  # renders y subidas: de uno en uno
_light = ThreadPoolExecutor(max_workers=4)  # llamadas a la IA
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _update(jid: str, **kw) -> None:
    with _lock:
        _jobs[jid].update(kw, updated_at=time.time())


def submit(kind: str, project_id: str | None, fn: Callable[[Callable[[float, str], None]], object],
           heavy: bool = True) -> dict:
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "kind": kind, "project_id": project_id, "status": "queued", "progress": 0.0,
           "message": "En cola…", "error": None, "result": None, "created_at": time.time(), "updated_at": time.time()}
    with _lock:
        _jobs[jid] = job

    def progress(frac: float, msg: str) -> None:
        _update(jid, progress=round(max(0.0, min(1.0, frac)), 4), message=msg)

    def run():
        _update(jid, status="running", message="Empezando…")
        try:
            result = fn(progress)
            _update(jid, status="done", progress=1.0, result=result,
                    message=_jobs[jid]["message"] if _jobs[jid]["progress"] >= 1 else "Completado")
        except Exception as e:
            traceback.print_exc()
            _update(jid, status="error", error=str(e), message="Error")

    (_heavy if heavy else _light).submit(run)
    return dict(job)


def get(jid: str) -> dict | None:
    with _lock:
        j = _jobs.get(jid)
        return dict(j) if j else None


def list_jobs(project_id: str | None = None) -> list[dict]:
    with _lock:
        js = [dict(j) for j in _jobs.values() if project_id is None or j["project_id"] == project_id]
    return sorted(js, key=lambda j: j["created_at"], reverse=True)
