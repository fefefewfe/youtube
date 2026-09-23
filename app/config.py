"""Configuración global de la aplicación (rutas, claves y valores por defecto)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # carga variables desde .env si existe
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass
DATA_DIR = Path(os.environ.get("QUIZ_DATA_DIR", ROOT / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
CACHE_DIR = DATA_DIR / "cache"
FONTS_DIR = ROOT / "fonts"
STATIC_DIR = ROOT / "static"

for _d in (DATA_DIR, PROJECTS_DIR, CACHE_DIR, FONTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# IA (generación de preguntas y metadatos de YouTube)
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")

# Voz premium opcional
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")

# YouTube (OAuth). Descarga el client_secret.json desde Google Cloud Console.
YOUTUBE_CLIENT_SECRETS = Path(os.environ.get("YOUTUBE_CLIENT_SECRETS", DATA_DIR / "client_secret.json"))
YOUTUBE_TOKEN_FILE = DATA_DIR / "youtube_token.json"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")

SAMPLE_RATE = 44100
