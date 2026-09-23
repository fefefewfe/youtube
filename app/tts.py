"""Síntesis de voz: Microsoft Edge neural (gratis), ElevenLabs (premium) o silencio (pruebas)."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx
import numpy as np

from . import media
from .config import CACHE_DIR, ELEVENLABS_API_KEY, ELEVENLABS_MODEL, SAMPLE_RATE

# Selección de voces neuronales realistas (la lista completa se obtiene de /api/voices)
EDGE_VOICES = [
    {"id": "es-MX-JorgeNeural", "name": "Jorge (México)", "lang": "es"},
    {"id": "es-MX-DaliaNeural", "name": "Dalia (México)", "lang": "es"},
    {"id": "es-ES-AlvaroNeural", "name": "Álvaro (España)", "lang": "es"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira (España)", "lang": "es"},
    {"id": "es-ES-XimenaNeural", "name": "Ximena (España)", "lang": "es"},
    {"id": "es-AR-TomasNeural", "name": "Tomás (Argentina)", "lang": "es"},
    {"id": "es-AR-ElenaNeural", "name": "Elena (Argentina)", "lang": "es"},
    {"id": "es-CO-GonzaloNeural", "name": "Gonzalo (Colombia)", "lang": "es"},
    {"id": "es-CO-SalomeNeural", "name": "Salomé (Colombia)", "lang": "es"},
    {"id": "es-US-AlonsoNeural", "name": "Alonso (EE. UU.)", "lang": "es"},
    {"id": "es-US-PalomaNeural", "name": "Paloma (EE. UU.)", "lang": "es"},
    {"id": "en-US-AndrewMultilingualNeural", "name": "Andrew (US, multilingüe)", "lang": "en"},
    {"id": "en-US-AvaMultilingualNeural", "name": "Ava (US, multilingüe)", "lang": "en"},
    {"id": "en-US-GuyNeural", "name": "Guy (US)", "lang": "en"},
    {"id": "en-US-JennyNeural", "name": "Jenny (US)", "lang": "en"},
    {"id": "en-GB-RyanNeural", "name": "Ryan (UK)", "lang": "en"},
    {"id": "pt-BR-AntonioNeural", "name": "Antônio (Brasil)", "lang": "pt"},
    {"id": "pt-BR-FranciscaNeural", "name": "Francisca (Brasil)", "lang": "pt"},
    {"id": "fr-FR-HenriNeural", "name": "Henri (Francia)", "lang": "fr"},
    {"id": "it-IT-DiegoNeural", "name": "Diego (Italia)", "lang": "it"},
    {"id": "de-DE-ConradNeural", "name": "Conrad (Alemania)", "lang": "de"},
]


class TTSError(RuntimeError):
    pass


def _cache_path(provider: str, voice: str, rate: int, pitch: int, text: str) -> Path:
    h = hashlib.sha1(f"{provider}|{voice}|{rate}|{pitch}|{text}".encode()).hexdigest()
    return CACHE_DIR / f"tts_{h}.mp3"


async def _edge(text: str, voice: str, rate: int, pitch: int, out: Path) -> None:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz")
    await comm.save(str(out))


def _elevenlabs(text: str, voice: str, out: Path) -> None:
    if not ELEVENLABS_API_KEY:
        raise TTSError("Falta ELEVENLABS_API_KEY en el entorno")
    r = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "accept": "audio/mpeg"},
        json={
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35},
        },
        timeout=120,
    )
    if r.status_code != 200:
        raise TTSError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    out.write_bytes(r.content)


def synthesize(text: str, provider: str, voice: str, rate: int = 0, pitch: int = 0) -> np.ndarray:
    """Devuelve audio float32 mono (con caché en disco)."""
    text = text.strip()
    if not text:
        return np.zeros(0, dtype=np.float32)
    if provider == "silent":
        # Duración aproximada de lectura para previsualizar sin voz.
        words = max(1, len(text.split()))
        return np.zeros(int((0.35 * words + 0.4) * SAMPLE_RATE), dtype=np.float32)

    out = _cache_path(provider, voice, rate, pitch, text)
    if not out.exists() or out.stat().st_size == 0:
        tmp = out.with_suffix(".part")
        try:
            if provider == "edge":
                asyncio.run(_edge(text, voice, rate, pitch, tmp))
            elif provider == "elevenlabs":
                _elevenlabs(text, voice, tmp)
            else:
                raise TTSError(f"Proveedor de voz desconocido: {provider}")
        except TTSError:
            raise
        except Exception as e:  # red, voz inexistente...
            raise TTSError(f"No se pudo generar la voz ({provider}/{voice}): {e}") from e
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise TTSError("El servicio de voz devolvió audio vacío")
        tmp.replace(out)
    return media.trim_silence(media.decode_audio(out))


def synthesize_file(text: str, provider: str, voice: str, rate: int = 0, pitch: int = 0) -> Path:
    """Para 'Probar voz' en la web: devuelve la ruta a un mp3/wav reproducible."""
    if provider == "silent":
        p = CACHE_DIR / "silent.wav"
        media.write_wav(p, np.zeros(SAMPLE_RATE, dtype=np.float32))
        return p
    synthesize(text, provider, voice, rate, pitch)
    return _cache_path(provider, voice, rate, pitch, text.strip())


def list_edge_voices() -> list[dict]:
    try:
        import edge_tts

        voices = asyncio.run(edge_tts.list_voices())
        return [
            {"id": v["ShortName"], "name": f'{v["ShortName"]} ({v["Gender"]})', "lang": v["Locale"].split("-")[0]}
            for v in voices
        ]
    except Exception:
        return EDGE_VOICES


def list_elevenlabs_voices() -> list[dict]:
    if not ELEVENLABS_API_KEY:
        return []
    try:
        r = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": ELEVENLABS_API_KEY}, timeout=30)
        r.raise_for_status()
        return [{"id": v["voice_id"], "name": v["name"], "lang": "multi"} for v in r.json().get("voices", [])]
    except Exception:
        return []
