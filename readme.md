# Quiz Video Studio 🎬❓

Aplicación web para **automatizar vídeos de quiz estilo "Play Quiz"** para YouTube: preguntas con 4 opciones, cuenta atrás con tic-tac, revelación de la respuesta correcta con sonido, **voz neuronal realista**, intro/cierre, música de fondo, miniatura y **subida directa a YouTube**.

## Funciones

- **Preguntas con IA** (Claude): escribes un tema → 10, 20 o 50 preguntas con distractores plausibles y dato curioso.
- **Editor**: edita, reordena, añade imágenes por pregunta, importa CSV/JSON y exporta JSON.
- **Voces realistas**:
  - Microsoft Edge Neural (**gratis**, sin clave): voces de México, España, Argentina, Colombia, EE. UU., inglés, portugués…
  - ElevenLabs (premium, opcional).
  - Velocidad y tono ajustables, botón "Probar voz".
- **Vídeo**: 1920×1080 (horizontal) o 1080×1920 (**Shorts**), 5 temas visuales, animaciones, temporizador circular + barra, efectos de sonido (whoosh, tic-tac, ding), música con *ducking* automático bajo la voz.
- **Vista previa** instantánea de cada escena antes de renderizar.
- **Miniatura** 1280×720 automática.
- **Metadatos de YouTube** (título, descripción, etiquetas) con IA o plantilla.
- **Subida a YouTube** con OAuth (privado / oculto / público).
- **⚡ Piloto automático**: pega una lista de temas → por cada uno genera preguntas, metadatos, vídeo y (opcional) lo sube.

## Instalación rápida

Requisitos: **Python 3.10+**. No hace falta instalar ffmpeg (se incluye vía `imageio-ffmpeg`).

```bash
git clone <este repo> && cd youtube
cp .env.example .env        # opcional: añade tus claves
./run.sh                    # Windows: run.bat
```

Abre **http://localhost:8000**.

Manual:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Con Docker:

```bash
docker build -t quiz-studio .
docker run -p 8000:8000 --env-file .env -v $PWD/data:/data quiz-studio
```

## Configuración (`.env`)

| Variable | Para qué | Obligatoria |
|---|---|---|
| `ANTHROPIC_API_KEY` | Generar preguntas y metadatos con IA, piloto automático | No (puedes escribir/importar preguntas) |
| `ANTHROPIC_MODEL` | Modelo de Claude (por defecto `claude-opus-5`) | No |
| `ELEVENLABS_API_KEY` | Voces ElevenLabs | No |
| `PUBLIC_BASE_URL` | URL de la app (para el OAuth de YouTube) | No (`http://localhost:8000`) |

### Conectar YouTube

1. En [Google Cloud Console](https://console.cloud.google.com/) crea un proyecto y activa **YouTube Data API v3**.
2. Configura la *pantalla de consentimiento OAuth* (tipo externo) y añade tu cuenta como usuario de prueba.
3. Crea credenciales **ID de cliente OAuth → Aplicación web** con el URI de redirección
   `http://localhost:8000/api/youtube/callback` (o `PUBLIC_BASE_URL` + `/api/youtube/callback`).
4. Descarga el JSON y guárdalo como `data/client_secret.json`.
5. En la app, pestaña **4. Generar y publicar → Conectar**.

> Las APIs de Google limitan la subida (≈6 vídeos/día con la cuota por defecto). Los proyectos no verificados suben los vídeos como privados hasta que Google revise la app. Las miniaturas personalizadas requieren un canal verificado.

## Formato de importación

CSV (con o sin cabecera; separador `,`, `;` o tabulador):

```
pregunta,opcion_a,opcion_b,opcion_c,opcion_d,correcta,explicacion
¿Cuál es el océano más grande?,Atlántico,Índico,Ártico,Pacífico,D,Cubre casi un tercio de la Tierra.
```

`correcta` admite `A-D`, `1-4` o el texto exacto de la opción. Ejemplo en [`examples/preguntas.csv`](examples/preguntas.csv).

JSON:

```json
{"questions": [{"question": "¿…?", "options": ["a", "b", "c", "d"], "correct": 2, "explanation": "…"}]}
```

## Estructura

```
app/
  main.py          API FastAPI + rutas de la web
  models.py        Proyecto, preguntas y ajustes
  ai.py            Claude: preguntas y metadatos (salida estructurada)
  tts.py           Voces: Edge neural, ElevenLabs, silencio
  media.py         Audio: decodificación, efectos sintetizados, mezcla y ducking
  youtube.py       OAuth + subida con YouTube Data API
  jobs.py          Cola de trabajos en segundo plano
  render/
    frames.py      Dibujo de escenas con Pillow (layouts 16:9 y 9:16, animaciones)
    themes.py      Temas visuales
    video.py       Línea de tiempo → fotogramas → ffmpeg (H.264 + AAC)
static/            Interfaz web (HTML/CSS/JS sin dependencias)
data/              Proyectos, vídeos y caché de voces (se crea al arrancar)
```

## Consejos

- Usa la voz "Sin voz (solo pruebas)" para iterar rápido en el diseño; cambia a una voz real para el vídeo final.
- Puedes poner tu propia tipografía en `fonts/heavy.ttf` y `fonts/bold.ttf` (por defecto se descarga Montserrat).
- Usa música **sin copyright** (p. ej. la Biblioteca de audio de YouTube) para evitar reclamaciones.
- Un vídeo de 10 preguntas en 1080p tarda aproximadamente 1-3 minutos en renderizarse, según el equipo.
