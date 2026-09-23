"""Gestión de tipografías: descarga Montserrat (Google Fonts, OFL) y usa fuentes del sistema si no hay red."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import httpx
from PIL import ImageFont

from ..config import FONTS_DIR

GOOGLE_FONTS = {"heavy": ("Montserrat", 800), "bold": ("Montserrat", 700)}
FALLBACKS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _download(family: str, weight: int, dest: Path) -> bool:
    try:
        css = httpx.get(
            "https://fonts.googleapis.com/css2",
            params={"family": f"{family}:wght@{weight}"},
            headers={"User-Agent": "Mozilla/4.0"},  # hace que Google devuelva TTF
            timeout=15,
        ).text
        m = re.search(r"url\((https://[^)]+\.ttf)\)", css)
        if not m:
            return False
        data = httpx.get(m.group(1), timeout=30).content
        if len(data) < 10_000:
            return False
        dest.write_bytes(data)
        return True
    except Exception:
        return False


@lru_cache
def font_path(kind: str = "heavy") -> str:
    # 1) fuente propia del usuario: fonts/heavy.ttf / fonts/bold.ttf
    custom = FONTS_DIR / f"{kind}.ttf"
    if custom.exists():
        return str(custom)
    family, weight = GOOGLE_FONTS.get(kind, GOOGLE_FONTS["heavy"])
    cached = FONTS_DIR / f"{family}-{weight}.ttf"
    if cached.exists() or _download(family, weight, cached):
        return str(cached)
    for f in FALLBACKS:
        if Path(f).exists():
            return f
    return ""


@lru_cache(maxsize=256)
def font(size: int, kind: str = "heavy") -> ImageFont.FreeTypeFont:
    p = font_path(kind)
    if p:
        return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)
