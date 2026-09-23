"""Generación de preguntas y metadatos de YouTube con Claude (Anthropic API)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .config import ANTHROPIC_MODEL

LANG_NAMES = {"es": "español", "en": "inglés", "pt": "portugués", "fr": "francés", "it": "italiano", "de": "alemán"}


class AIError(RuntimeError):
    pass


class _Q(BaseModel):
    question: str = Field(description="Enunciado corto (máx. ~90 caracteres)")
    options: list[str] = Field(description="Exactamente 4 opciones cortas (máx. ~30 caracteres cada una)")
    correct: int = Field(description="Índice 0-3 de la opción correcta")
    explanation: str = Field(description="Dato curioso de una frase (máx. ~110 caracteres)")


class _Quiz(BaseModel):
    title: str = Field(description="Título atractivo del vídeo")
    questions: list[_Q]


class _Meta(BaseModel):
    title: str = Field(description="Título de YouTube (máx. 90 caracteres)")
    description: str
    tags: list[str]


def _client():
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise AIError("Instala el paquete 'anthropic'") from e
    try:
        return anthropic.Anthropic()
    except Exception as e:
        raise AIError("Configura ANTHROPIC_API_KEY para usar la IA") from e


def _parse(prompt: str, schema: type[BaseModel], system: str) -> BaseModel:
    import anthropic

    client = _client()
    try:
        resp = client.messages.parse(
            model=ANTHROPIC_MODEL,
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
    except anthropic.AuthenticationError as e:
        raise AIError("ANTHROPIC_API_KEY inválida o ausente") from e
    except anthropic.RateLimitError as e:
        raise AIError("Límite de uso de la API alcanzado; inténtalo en un momento") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Error de la API de Claude ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("No se pudo conectar con la API de Claude") from e
    if resp.stop_reason == "refusal":
        raise AIError("Claude rechazó la petición; prueba con otro tema")
    if resp.parsed_output is None:
        raise AIError(f"Respuesta sin formato válido (stop_reason={resp.stop_reason})")
    return resp.parsed_output


SYSTEM_QUIZ = (
    "Eres guionista de un canal de YouTube de quizzes estilo 'Play Quiz'. Escribes preguntas de cultura general "
    "precisas y verificables, con distractores plausibles del mismo tipo que la respuesta correcta. "
    "Los textos se muestran en pantalla y se leen en voz alta, así que deben ser breves y claros. "
    "Varía la posición de la respuesta correcta entre las opciones."
)


def generate_quiz(topic: str, count: int = 10, difficulty: str = "mixta", language: str = "es",
                  extra: str = "") -> dict:
    lang = LANG_NAMES.get(language, language)
    prompt = (
        f"Crea un quiz de {count} preguntas sobre: {topic}.\n"
        f"Dificultad: {difficulty} (si es 'progresiva', de fácil a difícil).\n"
        f"Idioma de todo el contenido: {lang}.\n"
        "Cada pregunta con exactamente 4 opciones y una sola correcta."
    )
    if extra.strip():
        prompt += f"\nIndicaciones adicionales: {extra.strip()}"
    quiz: _Quiz = _parse(prompt, _Quiz, SYSTEM_QUIZ)  # type: ignore[assignment]
    questions = []
    for q in quiz.questions:
        opts = (list(q.options) + ["", "", "", ""])[:4]
        correct = q.correct if 0 <= q.correct < 4 and opts[q.correct].strip() else 0
        questions.append({"question": q.question, "options": opts, "correct": correct, "explanation": q.explanation})
    return {"title": quiz.title, "questions": questions}


def generate_metadata(title: str, topic: str, questions: list[dict], language: str = "es",
                      vertical: bool = False) -> dict:
    lang = LANG_NAMES.get(language, language)
    listing = "\n".join(f"- {q['question']}" for q in questions[:30])
    prompt = (
        f"Escribe los metadatos de YouTube (en {lang}) para un vídeo de quiz.\n"
        f"Título provisional: {title}\nTema: {topic}\nNúmero de preguntas: {len(questions)}\n"
        f"Formato: {'YouTube Shorts (vertical), incluye #shorts' if vertical else 'vídeo horizontal'}\n"
        f"Preguntas:\n{listing}\n\n"
        "El título debe invitar a participar (p. ej. '¿Puedes acertar las 10?'), sin revelar respuestas. "
        "La descripción: 2-3 frases enganchantes, invitación a comentar la puntuación y suscribirse, "
        "y 3-5 hashtags al final. Entre 10 y 20 tags relevantes."
    )
    meta: _Meta = _parse(prompt, _Meta, "Eres experto en SEO de YouTube.")  # type: ignore[assignment]
    return {"title": meta.title[:100], "description": meta.description, "tags": meta.tags[:30]}


def fallback_metadata(title: str, topic: str, n: int, language: str = "es", vertical: bool = False) -> dict:
    """Metadatos por plantilla (sin IA)."""
    t = title or topic or "Quiz"
    desc = (
        f"¿Cuánto sabes de {topic or t}? Pon a prueba tus conocimientos con estas {n} preguntas. "
        "¡Deja tu puntuación en los comentarios y suscríbete para más quizzes!\n\n#quiz #trivia #preguntas"
    )
    if vertical:
        desc += " #shorts"
    tags = ["quiz", "trivia", "preguntas y respuestas", "cultura general", "test", topic or t]
    return {"title": f"{t} | ¿Puedes acertar las {n}? 🧠"[:100], "description": desc, "tags": [x for x in tags if x]}
