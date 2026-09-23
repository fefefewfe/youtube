"""API web (FastAPI) + servidor de la interfaz."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, jobs, storage, tts, youtube
from .config import ELEVENLABS_API_KEY, STATIC_DIR
from .models import Project, Question, VideoSettings
from .render.themes import THEMES
from .render.video import preview_frame, render_video

app = FastAPI(title="Quiz Video Studio")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _load(pid: str) -> Project:
    try:
        return storage.load(pid)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Proyecto no encontrado")


def _ai_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ------------------------------------------------------------------ UI

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/meta")
def meta():
    return {
        "themes": [{"id": k, "name": v["name"]} for k, v in THEMES.items()],
        "voices": {"edge": tts.EDGE_VOICES, "elevenlabs": [], "silent": [{"id": "none", "name": "Sin voz"}]},
        "elevenlabs": bool(ELEVENLABS_API_KEY),
        "ai": _ai_available(),
        "youtube": youtube.status(),
        "defaults": VideoSettings().model_dump(),
    }


@app.get("/api/voices")
def voices(provider: str = "edge"):
    if provider == "elevenlabs":
        return tts.list_elevenlabs_voices()
    if provider == "edge":
        return tts.list_edge_voices()
    return [{"id": "none", "name": "Sin voz"}]


class TTSTest(BaseModel):
    provider: str
    voice: str
    rate: int = 0
    pitch: int = 0
    text: str = "Hola, esta es una prueba de voz para tu quiz. ¿Cuál es la respuesta correcta?"


@app.post("/api/tts/test")
def tts_test(body: TTSTest):
    try:
        path = tts.synthesize_file(body.text[:400], body.provider, body.voice, body.rate, body.pitch)
    except tts.TTSError as e:
        raise HTTPException(400, str(e))
    return FileResponse(path, media_type="audio/wav" if path.suffix == ".wav" else "audio/mpeg")


# ------------------------------------------------------------------ proyectos

@app.get("/api/projects")
def projects():
    return [
        {"id": p.id, "title": p.title, "topic": p.topic, "questions": len(p.questions),
         "has_video": bool(p.video_file), "format": p.settings.format, "updated_at": p.updated_at,
         "video_id": p.youtube.video_id}
        for p in storage.list_all()
    ]


class NewProject(BaseModel):
    title: str = "Nuevo quiz"
    topic: str = ""
    language: str = "es"
    settings: Optional[dict] = None


@app.post("/api/projects")
def create_project(body: NewProject):
    p = Project(title=body.title, topic=body.topic, language=body.language)
    if body.settings:
        p.settings = VideoSettings.model_validate({**p.settings.model_dump(), **body.settings})
    return storage.save(p)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _load(pid)


@app.put("/api/projects/{pid}")
def update_project(pid: str, body: dict):
    old = _load(pid)
    data = {**old.model_dump(), **body, "id": old.id, "created_at": old.created_at}
    # campos gestionados por el servidor
    data["video_file"], data["thumbnail_file"] = old.video_file, old.thumbnail_file
    try:
        p = Project.model_validate(data)
    except Exception as e:
        raise HTTPException(422, f"Datos inválidos: {e}")
    return storage.save(p)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    _load(pid)
    storage.delete(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/duplicate")
def duplicate_project(pid: str):
    src = _load(pid)
    p = src.model_copy(deep=True)
    p.id = uuid.uuid4().hex[:10]
    p.title = f"{src.title} (copia)"
    p.video_file = p.thumbnail_file = None
    p.youtube.video_id = None
    d_src, d_dst = storage.project_dir(src.id), storage.project_dir(p.id)
    d_dst.mkdir(parents=True, exist_ok=True)
    for f in d_src.iterdir():
        if f.name.startswith(("img_", "music_")):
            (d_dst / f.name).write_bytes(f.read_bytes())
    return storage.save(p)


# ------------------------------------------------------------------ archivos

ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ALLOWED_AUDIO = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}


@app.post("/api/projects/{pid}/upload")
async def upload_file(pid: str, kind: str, file: UploadFile = File(...), qid: Optional[str] = None):
    p = _load(pid)
    ext = Path(file.filename or "").suffix.lower()
    if kind == "image" and ext not in ALLOWED_IMG:
        raise HTTPException(400, "Formato de imagen no soportado")
    if kind == "music" and ext not in ALLOWED_AUDIO:
        raise HTTPException(400, "Formato de audio no soportado")
    name = f"{'img' if kind == 'image' else 'music'}_{uuid.uuid4().hex[:8]}{ext}"
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "Archivo demasiado grande (máx. 50 MB)")
    (storage.project_dir(pid) / name).write_bytes(data)
    if kind == "image":
        q = next((q for q in p.questions if q.id == qid), None)
        if not q:
            raise HTTPException(404, "Pregunta no encontrada")
        q.image = name
    else:
        p.settings.music = name
    storage.save(p)
    return {"file": name, "project": p}


@app.get("/files/{pid}/{name}")
def serve_file(pid: str, name: str, download: bool = False):
    if not re.fullmatch(r"[\w.\-]+", name):
        raise HTTPException(400)
    f = storage.project_dir(pid) / name
    if not f.exists():
        raise HTTPException(404)
    if download:
        return FileResponse(f, filename=f"{_load(pid).title}{f.suffix}")
    return FileResponse(f)


@app.get("/api/projects/{pid}/preview.jpg")
def preview(pid: str, q: int = 0, phase: str = "think"):
    p = _load(pid)
    img = preview_frame(p, storage.project_dir(pid), q, phase)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ import / export

def _parse_correct(v: str, options: list[str]) -> int:
    v = (v or "").strip()
    if v.upper() in ("A", "B", "C", "D"):
        return "ABCD".index(v.upper())
    if v.isdigit():
        n = int(v)
        return n - 1 if 1 <= n <= 4 else 0
    return options.index(v) if v in options else 0


@app.post("/api/projects/{pid}/import")
async def import_questions(pid: str, file: UploadFile = File(...), replace: bool = False):
    p = _load(pid)
    raw = (await file.read()).decode("utf-8-sig", errors="ignore")
    new: list[Question] = []
    try:
        if (file.filename or "").lower().endswith(".json") or raw.lstrip().startswith(("[", "{")):
            data = json.loads(raw)
            items = data.get("questions", []) if isinstance(data, dict) else data
            for it in items:
                opts = (list(it.get("options", [])) + ["", "", "", ""])[:4]
                c = it.get("correct", 0)
                new.append(Question(question=it["question"], options=opts,
                                    correct=c if isinstance(c, int) else _parse_correct(str(c), opts),
                                    explanation=it.get("explanation", "")))
        else:
            dialect = csv.Sniffer().sniff(raw[:2000], delimiters=",;\t")
            rows = list(csv.reader(io.StringIO(raw), dialect))
            if rows and rows[0] and rows[0][0].strip().lower() in ("question", "pregunta"):
                rows = rows[1:]
            for r in rows:
                if len(r) < 3 or not r[0].strip():
                    continue
                opts = ([x.strip() for x in r[1:5]] + ["", "", "", ""])[:4]
                corr = _parse_correct(r[5] if len(r) > 5 else "A", opts)
                new.append(Question(question=r[0].strip(), options=opts, correct=corr,
                                    explanation=r[6].strip() if len(r) > 6 else ""))
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer el archivo: {e}")
    p.questions = new if replace else p.questions + new
    storage.save(p)
    return p


@app.get("/api/projects/{pid}/export")
def export_questions(pid: str):
    p = _load(pid)
    data = {"title": p.title, "topic": p.topic, "questions": [
        {"question": q.question, "options": q.options, "correct": q.correct, "explanation": q.explanation}
        for q in p.questions]}
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="quiz_{pid}.json"'})


# ------------------------------------------------------------------ IA

class GenerateReq(BaseModel):
    topic: str
    count: int = 10
    difficulty: str = "progresiva"
    language: Optional[str] = None
    extra: str = ""
    replace: bool = True


def _generate_into(p: Project, body: GenerateReq, progress) -> Project:
    progress(0.1, "Claude está escribiendo las preguntas…")
    res = ai.generate_quiz(body.topic, max(1, min(body.count, 50)), body.difficulty, body.language or p.language,
                           body.extra)
    p = storage.load(p.id)
    qs = [Question(**q) for q in res["questions"]]
    p.questions = qs if body.replace else p.questions + qs
    p.topic = body.topic
    if body.language:
        p.language = body.language
    if not p.title or p.title == "Nuevo quiz":
        p.title = res["title"]
    storage.save(p)
    progress(1.0, f"{len(qs)} preguntas generadas")
    return p


@app.post("/api/projects/{pid}/generate")
def generate(pid: str, body: GenerateReq):
    p = _load(pid)
    if not _ai_available():
        raise HTTPException(400, "Configura ANTHROPIC_API_KEY para generar preguntas con IA")
    return jobs.submit("generate", pid, lambda pr: _generate_into(p, body, pr).id, heavy=False)


def _metadata(p: Project, use_ai: bool, progress) -> dict:
    progress(0.2, "Generando título, descripción y etiquetas…")
    vertical = p.settings.format == "9:16"
    qs = [q.model_dump() for q in p.questions]
    if use_ai:
        m = ai.generate_metadata(p.title, p.topic, qs, p.language, vertical)
    else:
        m = ai.fallback_metadata(p.title, p.topic, len(qs), p.language, vertical)
    p = storage.load(p.id)
    p.youtube.title, p.youtube.description, p.youtube.tags = m["title"], m["description"], m["tags"]
    storage.save(p)
    progress(1.0, "Metadatos listos")
    return m


@app.post("/api/projects/{pid}/metadata")
def metadata(pid: str):
    p = _load(pid)
    return jobs.submit("metadata", pid, lambda pr: _metadata(p, _ai_available(), pr), heavy=False)


# ------------------------------------------------------------------ render y subida

def _render(pid: str, progress) -> str:
    p = storage.load(pid)
    render_video(p, storage.project_dir(pid), progress)
    p = storage.load(pid)
    p.video_file, p.thumbnail_file = "video.mp4", "thumbnail.jpg"
    storage.save(p)
    return p.video_file


@app.post("/api/projects/{pid}/render")
def render(pid: str):
    _load(pid)
    return jobs.submit("render", pid, lambda pr: _render(pid, pr))


def _upload(pid: str, progress) -> str:
    p = storage.load(pid)
    if not p.video_file:
        raise RuntimeError("Primero genera el vídeo")
    d = storage.project_dir(pid)
    meta = p.youtube
    if not meta.title:
        m = ai.fallback_metadata(p.title, p.topic, len(p.questions), p.language, p.settings.format == "9:16")
        meta.title, meta.description, meta.tags = m["title"], m["description"], m["tags"]
    vid = youtube.upload(d / p.video_file, meta.title, meta.description, meta.tags, meta.privacy,
                         d / (p.thumbnail_file or "thumbnail.jpg"), p.language, progress)
    p = storage.load(pid)
    p.youtube.video_id = vid
    storage.save(p)
    return vid


@app.post("/api/projects/{pid}/youtube")
def upload_youtube(pid: str):
    _load(pid)
    if not youtube.status()["connected"]:
        raise HTTPException(400, "Conecta tu cuenta de YouTube primero")
    return jobs.submit("upload", pid, lambda pr: _upload(pid, pr))


# ------------------------------------------------------------------ piloto automático

class AutopilotReq(BaseModel):
    topics: list[str]
    count: int = 10
    difficulty: str = "progresiva"
    language: str = "es"
    extra: str = ""
    settings: dict = {}
    upload: bool = False
    privacy: str = "private"


@app.post("/api/autopilot")
def autopilot(body: AutopilotReq):
    if not _ai_available():
        raise HTTPException(400, "El piloto automático necesita ANTHROPIC_API_KEY")
    if body.upload and not youtube.status()["connected"]:
        raise HTTPException(400, "Conecta YouTube o desactiva la subida automática")
    created = []
    for topic in [t.strip() for t in body.topics if t.strip()][:20]:
        p = Project(title="Nuevo quiz", topic=topic, language=body.language)
        p.settings = VideoSettings.model_validate({**p.settings.model_dump(), **body.settings})
        p.youtube.privacy = body.privacy  # type: ignore[assignment]
        storage.save(p)

        def run(pr, p=p, topic=topic):
            sub = lambda a, b: (lambda f, m: pr(a + (b - a) * f, m))  # noqa: E731
            _generate_into(p, GenerateReq(topic=topic, count=body.count, difficulty=body.difficulty,
                                          language=body.language, extra=body.extra), sub(0.0, 0.15))
            _metadata(storage.load(p.id), True, sub(0.15, 0.2))
            _render(p.id, sub(0.2, 0.9 if body.upload else 1.0))
            if body.upload:
                _upload(p.id, sub(0.9, 1.0))
            return p.id

        created.append({"project_id": p.id, "topic": topic, "job": jobs.submit("autopilot", p.id, run)})
    return created


# ------------------------------------------------------------------ trabajos

@app.get("/api/jobs")
def list_jobs(project_id: Optional[str] = None):
    return jobs.list_jobs(project_id)


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404)
    return j


# ------------------------------------------------------------------ YouTube OAuth

@app.get("/api/youtube/status")
def yt_status():
    st = youtube.status()
    if st["connected"]:
        st["channel"] = youtube.channel_name()
    return st


@app.get("/api/youtube/auth")
def yt_auth():
    try:
        return RedirectResponse(youtube.auth_url())
    except youtube.YouTubeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/youtube/callback")
def yt_callback(request: Request, state: str = ""):
    try:
        youtube.finish_auth(state, str(request.url))
    except Exception as e:
        raise HTTPException(400, f"No se pudo conectar YouTube: {e}")
    return RedirectResponse("/?youtube=connected")


@app.post("/api/youtube/disconnect")
def yt_disconnect():
    youtube.disconnect()
    return {"ok": True}
