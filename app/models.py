"""Modelos de datos: proyecto, preguntas y ajustes de render."""
from __future__ import annotations

import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _id() -> str:
    return uuid.uuid4().hex[:10]


class Question(BaseModel):
    id: str = Field(default_factory=_id)
    question: str
    options: list[str] = Field(default_factory=lambda: ["", "", "", ""])
    correct: int = 0  # índice de la opción correcta
    explanation: str = ""
    image: Optional[str] = None  # nombre de archivo dentro de la carpeta del proyecto


class VideoSettings(BaseModel):
    format: Literal["16:9", "9:16"] = "16:9"
    theme: str = "neon"
    fps: int = 30

    tts_provider: Literal["edge", "elevenlabs", "silent"] = "edge"
    voice: str = "es-MX-JorgeNeural"
    voice_rate: int = 0  # % velocidad (-50..+50), solo edge
    voice_pitch: int = 0  # Hz (-20..+20), solo edge

    think_seconds: int = 5
    read_options: bool = True
    show_explanation: bool = True
    reveal_seconds: float = 1.2  # pausa extra tras decir la respuesta

    intro_enabled: bool = True
    intro_text: str = ""
    outro_enabled: bool = True
    outro_text: str = ""

    music: Optional[str] = None  # archivo de música de fondo en la carpeta del proyecto
    music_volume: float = 0.12
    sfx_volume: float = 0.6


class YouTubeMeta(BaseModel):
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    privacy: Literal["private", "unlisted", "public"] = "private"
    video_id: Optional[str] = None


class Project(BaseModel):
    id: str = Field(default_factory=_id)
    title: str = "Nuevo quiz"
    topic: str = ""
    language: str = "es"
    questions: list[Question] = Field(default_factory=list)
    settings: VideoSettings = Field(default_factory=VideoSettings)
    youtube: YouTubeMeta = Field(default_factory=YouTubeMeta)
    video_file: Optional[str] = None
    thumbnail_file: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
