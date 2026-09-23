"""Utilidades de audio con ffmpeg + numpy (decodificar, sintetizar efectos, mezclar)."""
from __future__ import annotations

import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from .config import SAMPLE_RATE


@lru_cache
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def decode_audio(path: Path | str) -> np.ndarray:
    """Decodifica cualquier audio a float32 mono a SAMPLE_RATE."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def duration(samples: np.ndarray) -> float:
    return len(samples) / SAMPLE_RATE


def trim_silence(x: np.ndarray, threshold: float = 0.01, pad: float = 0.05) -> np.ndarray:
    idx = np.where(np.abs(x) > threshold)[0]
    if len(idx) == 0:
        return x
    p = int(pad * SAMPLE_RATE)
    return x[max(0, idx[0] - p): min(len(x), idx[-1] + p)]


def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- efectos

def _t(sec: float) -> np.ndarray:
    return np.arange(int(sec * SAMPLE_RATE)) / SAMPLE_RATE


def sfx_tick(high: bool = False) -> np.ndarray:
    t = _t(0.09)
    f = 1500 if high else 1000
    return (np.sin(2 * np.pi * f * t) * np.exp(-t * 60) * 0.7).astype(np.float32)


def sfx_ding() -> np.ndarray:
    t = _t(1.1)
    s = np.zeros_like(t)
    for f, delay, amp in ((880, 0.0, 0.5), (1318.5, 0.09, 0.45), (1760, 0.18, 0.3)):
        tt = np.clip(t - delay, 0, None)
        s += np.where(t >= delay, np.sin(2 * np.pi * f * tt) * np.exp(-tt * 4.5) * amp, 0)
    return (s * 0.8).astype(np.float32)


def sfx_whoosh() -> np.ndarray:
    t = _t(0.45)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(len(t))
    # filtro paso bajo móvil con frecuencia creciente
    alpha = np.linspace(0.02, 0.35, len(t))
    y = np.zeros_like(noise)
    acc = 0.0
    for i, n in enumerate(noise):
        acc += alpha[i] * (n - acc)
        y[i] = acc
    env = np.sin(np.pi * t / t[-1]) ** 2
    return (y * env * 0.5).astype(np.float32)


def sfx_intro() -> np.ndarray:
    t = _t(1.4)
    s = np.zeros_like(t)
    for i, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        d = i * 0.12
        tt = np.clip(t - d, 0, None)
        s += np.where(t >= d, np.sin(2 * np.pi * f * tt) * np.exp(-tt * 3) * 0.3, 0)
    return s.astype(np.float32)


class AudioTimeline:
    """Acumula clips de audio en posiciones de tiempo y los mezcla."""

    def __init__(self) -> None:
        self.voice: list[tuple[float, np.ndarray]] = []
        self.sfx: list[tuple[float, np.ndarray]] = []

    def add_voice(self, at: float, clip: np.ndarray) -> None:
        self.voice.append((at, clip))

    def add_sfx(self, at: float, clip: np.ndarray) -> None:
        self.sfx.append((at, clip))

    @staticmethod
    def _place(buf: np.ndarray, at: float, clip: np.ndarray, gain: float = 1.0) -> None:
        start = int(at * SAMPLE_RATE)
        end = min(len(buf), start + len(clip))
        if end > start:
            buf[start:end] += clip[: end - start] * gain

    def render(self, total: float, music: np.ndarray | None, music_volume: float, sfx_volume: float) -> np.ndarray:
        n = int(total * SAMPLE_RATE) + 1
        voice = np.zeros(n, dtype=np.float32)
        for at, c in self.voice:
            self._place(voice, at, c)
        out = voice.copy()
        for at, c in self.sfx:
            self._place(out, at, c, sfx_volume)
        if music is not None and len(music) > 0:
            reps = int(np.ceil(n / len(music)))
            m = np.tile(music, reps)[:n]
            # "ducking": bajar la música cuando habla la voz
            env = np.abs(voice)
            win = int(0.25 * SAMPLE_RATE)
            env = np.convolve(env, np.ones(win) / win, mode="same")
            duck = 1.0 - 0.6 * np.clip(env / 0.05, 0, 1)
            fade = np.ones(n, dtype=np.float32)
            f = min(n // 4, int(2.5 * SAMPLE_RATE))
            if f > 0:
                fade[:f] = np.linspace(0, 1, f)
                fade[-f:] = np.linspace(1, 0, f)
            out += m * music_volume * duck * fade
        peak = float(np.max(np.abs(out))) if n else 0
        if peak > 0.98:
            out *= 0.98 / peak
        return out
