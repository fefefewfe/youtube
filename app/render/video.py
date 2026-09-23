"""Pipeline completo: voz -> línea de tiempo -> fotogramas -> ffmpeg (MP4 H.264 + AAC)."""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .. import media, tts
from ..models import Project
from .frames import LETTERS, FrameRenderer, thumbnail

Progress = Callable[[float, str], None]

TEXTS = {
    "es": {
        "question": "Pregunta {n}.",
        "answer": "La respuesta correcta es la {letter}: {text}.",
        "intro": "¿Cuánto sabes de {topic}? Tienes {s} segundos para responder cada pregunta. ¡Vamos allá!",
        "intro_sub": "{n} preguntas · {s} segundos",
        "outro": "¿Cuántas acertaste? Déjalo en los comentarios y suscríbete para más quizzes.",
        "outro_title": "¿Cuántas acertaste?",
        "outro_sub": "Comenta tu puntuación",
    },
    "en": {
        "question": "Question {n}.",
        "answer": "The correct answer is {letter}: {text}.",
        "intro": "How much do you know about {topic}? You have {s} seconds to answer each question. Let's go!",
        "intro_sub": "{n} questions · {s} seconds",
        "outro": "How many did you get right? Tell us in the comments and subscribe for more quizzes.",
        "outro_title": "How many did you get?",
        "outro_sub": "Comment your score",
    },
    "pt": {
        "question": "Pergunta {n}.",
        "answer": "A resposta correta é a {letter}: {text}.",
        "intro": "Quanto você sabe sobre {topic}? Você tem {s} segundos para cada pergunta. Vamos lá!",
        "intro_sub": "{n} perguntas · {s} segundos",
        "outro": "Quantas você acertou? Conte nos comentários e se inscreva para mais quizzes.",
        "outro_title": "Quantas você acertou?",
        "outro_sub": "Comente sua pontuação",
    },
}


def texts(lang: str) -> dict:
    return TEXTS.get(lang, TEXTS["es"])


@dataclass
class Segment:
    kind: str  # intro | question | outro
    start: float
    duration: float
    qi: int = -1
    marks: dict = field(default_factory=dict)  # tiempos internos (relativos al segmento)


def _voice(p: Project, text: str) -> np.ndarray:
    s = p.settings
    return tts.synthesize(text, s.tts_provider, s.voice, s.voice_rate, s.voice_pitch)


def build_timeline(p: Project, progress: Progress) -> tuple[list[Segment], media.AudioTimeline, float]:
    s = p.settings
    T = texts(p.language)
    tl = media.AudioTimeline()
    segs: list[Segment] = []
    cur = 0.0
    n = len(p.questions)
    total_clips = n * 2 + 2
    done = 0

    def step(msg: str):
        nonlocal done
        done += 1
        progress(0.3 * done / total_clips, msg)

    if s.intro_enabled:
        text = s.intro_text.strip() or T["intro"].format(topic=p.topic or p.title, s=s.think_seconds)
        v = _voice(p, text)
        step("Voz de la introducción")
        dur = max(3.0, media.duration(v) + 1.3)
        tl.add_sfx(cur, media.sfx_intro())
        tl.add_voice(cur + 0.6, v)
        segs.append(Segment("intro", cur, dur))
        cur += dur

    for i, q in enumerate(p.questions):
        spoken = f'{T["question"].format(n=i + 1)} {q.question}'
        if s.read_options:
            spoken += " " + ". ".join(f"{LETTERS[k]}: {o}" for k, o in enumerate(q.options[:4]) if o.strip()) + "."
        vq = _voice(p, spoken)
        step(f"Voz pregunta {i + 1}")
        correct = q.options[q.correct] if 0 <= q.correct < len(q.options) else ""
        ans = T["answer"].format(letter=LETTERS[q.correct], text=correct)
        if s.show_explanation and q.explanation.strip():
            ans += " " + q.explanation.strip()
        va = _voice(p, ans)
        step(f"Voz respuesta {i + 1}")

        ask = max(1.6, 0.9 + media.duration(vq) + 0.3)  # animación de entrada + lectura
        think = float(s.think_seconds)
        reveal = max(2.0, media.duration(va) + 0.35 + s.reveal_seconds)
        tl.add_sfx(cur, media.sfx_whoosh())
        tl.add_voice(cur + 0.9, vq)
        for k in range(int(think)):
            tl.add_sfx(cur + ask + k, media.sfx_tick(high=(think - k) <= 3))
        tl.add_sfx(cur + ask + think, media.sfx_ding())
        tl.add_voice(cur + ask + think + 0.35, va)
        dur = ask + think + reveal
        segs.append(Segment("question", cur, dur, qi=i, marks={"ask": ask, "think": think}))
        cur += dur

    if s.outro_enabled:
        text = s.outro_text.strip() or T["outro"]
        v = _voice(p, text)
        step("Voz del cierre")
        dur = max(3.5, media.duration(v) + 1.8)
        tl.add_sfx(cur, media.sfx_intro())
        tl.add_voice(cur + 0.6, v)
        segs.append(Segment("outro", cur, dur))
        cur += dur
    return segs, tl, cur


def frame_at(r: FrameRenderer, p: Project, seg: Segment, lt: float) -> Image.Image:
    T = texts(p.language)
    s = p.settings
    fade_out = min(1.0, (seg.duration - lt) / 0.3)
    if seg.kind == "intro":
        sub = T["intro_sub"].format(n=len(p.questions), s=s.think_seconds)
        return r.title_frame(p.title or p.topic, sub, lt, fade=fade_out)
    if seg.kind == "outro":
        return r.title_frame(T["outro_title"], T["outro_sub"], lt, fade=min(1.0, lt / 0.3), cta=True)
    ask, think = seg.marks["ask"], seg.marks["think"]
    if lt < ask:
        return r.question_frame(seg.qi, "ask", lt, 1.0, str(int(think)))
    if lt < ask + think:
        el = lt - ask
        frac = max(0.0, 1 - el / think)
        return r.question_frame(seg.qi, "think", el, frac, str(max(1, math.ceil(think - el))))
    return r.question_frame(seg.qi, "reveal", lt - ask - think, fade=fade_out)


def preview_frame(p: Project, project_dir: Path, qi: int, phase: str) -> Image.Image:
    r = FrameRenderer(p, project_dir)
    T = texts(p.language)
    if phase == "intro" or not p.questions:
        return r.title_frame(p.title or p.topic, T["intro_sub"].format(n=len(p.questions), s=p.settings.think_seconds), 5)
    if phase == "outro":
        return r.title_frame(T["outro_title"], T["outro_sub"], 5, cta=True)
    qi = max(0, min(qi, len(p.questions) - 1))
    if phase == "reveal":
        return r.question_frame(qi, "reveal", 2)
    th = p.settings.think_seconds
    return r.question_frame(qi, "think", 0, 0.6, str(max(1, round(th * 0.6))))


def render_video(p: Project, project_dir: Path, progress: Progress) -> Path:
    if not p.questions:
        raise ValueError("El proyecto no tiene preguntas")
    for i, q in enumerate(p.questions):
        if not q.question.strip() or sum(1 for o in q.options if o.strip()) < 2:
            raise ValueError(f"La pregunta {i + 1} está incompleta (texto y al menos 2 opciones)")
        if not 0 <= q.correct < len(q.options) or not q.options[q.correct].strip():
            raise ValueError(f"La pregunta {i + 1} no tiene una respuesta correcta válida")

    progress(0.01, "Generando voces…")
    segs, tl, total = build_timeline(p, progress)
    s = p.settings

    progress(0.31, "Mezclando audio…")
    music = None
    if s.music and (project_dir / s.music).exists():
        music = media.decode_audio(project_dir / s.music)
    audio = tl.render(total, music, s.music_volume, s.sfx_volume)
    wav = project_dir / "audio.wav"
    media.write_wav(wav, audio)

    r = FrameRenderer(p, project_dir)
    W, H = r.W, r.H
    fps = s.fps
    out = project_dir / "video.mp4"
    tmp = project_dir / "video.tmp.mp4"
    cmd = [
        media.ffmpeg_exe(), "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
        "-i", str(wav),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(tmp),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    nframes = int(total * fps)
    si = 0
    last_key, last_bytes = None, b""
    try:
        for fi in range(nframes):
            t = fi / fps
            while si < len(segs) - 1 and t >= segs[si].start + segs[si].duration:
                si += 1
            seg = segs[si]
            lt = t - seg.start
            # Reutiliza fotogramas idénticos (fase de "reveal" ya estable, etc.)
            key = None
            if seg.kind == "question":
                ask, think = seg.marks["ask"], seg.marks["think"]
                rt = lt - ask - think
                if rt > 0.4 and seg.duration - lt > 0.3:
                    key = (si, "reveal-static")
                elif ask > lt > 1.6:
                    key = (si, "ask-static")
            if key is not None and key == last_key:
                data = last_bytes
            else:
                data = frame_at(r, p, seg, lt).tobytes()
                last_key, last_bytes = key, data
            proc.stdin.write(data)
            if fi % fps == 0:
                progress(0.32 + 0.63 * fi / nframes, f"Renderizando fotogramas {fi}/{nframes}")
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="ignore")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg falló: {err[-800:]}")
    except BrokenPipeError:
        err = proc.stderr.read().decode(errors="ignore")
        raise RuntimeError(f"ffmpeg se cerró inesperadamente: {err[-800:]}")
    tmp.replace(out)
    wav.unlink(missing_ok=True)
    progress(0.97, "Creando miniatura…")
    thumbnail(p, project_dir, project_dir / "thumbnail.jpg")
    progress(1.0, "¡Vídeo listo!")
    return out
