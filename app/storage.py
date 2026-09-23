"""Persistencia sencilla: un directorio por proyecto con project.json y sus ficheros."""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from .config import PROJECTS_DIR
from .models import Project

_lock = threading.Lock()


def project_dir(pid: str) -> Path:
    if not pid.isalnum():
        raise ValueError("id de proyecto inválido")
    return PROJECTS_DIR / pid


def save(project: Project) -> Project:
    project.updated_at = time.time()
    d = project_dir(project.id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "project.json.tmp"
    with _lock:
        tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(d / "project.json")
    return project


def load(pid: str) -> Project:
    f = project_dir(pid) / "project.json"
    if not f.exists():
        raise FileNotFoundError(pid)
    return Project.model_validate(json.loads(f.read_text(encoding="utf-8")))


def list_all() -> list[Project]:
    out = []
    for f in PROJECTS_DIR.glob("*/project.json"):
        try:
            out.append(Project.model_validate(json.loads(f.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return sorted(out, key=lambda p: p.updated_at, reverse=True)


def delete(pid: str) -> None:
    shutil.rmtree(project_dir(pid), ignore_errors=True)
