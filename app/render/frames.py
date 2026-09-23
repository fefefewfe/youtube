"""Dibujo de fotogramas con Pillow: fondo, tarjeta de pregunta, opciones, temporizador y animaciones."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..models import Project, Question
from .fonts import font
from .themes import get_theme

LETTERS = "ABCD"
LABELS = {
    "es": {"pill": "PREGUNTA", "thanks": "¡GRACIAS!", "questions": "PREGUNTAS", "subscribe": "SUSCRÍBETE"},
    "en": {"pill": "QUESTION", "thanks": "THANKS!", "questions": "QUESTIONS", "subscribe": "SUBSCRIBE"},
    "pt": {"pill": "PERGUNTA", "thanks": "OBRIGADO!", "questions": "PERGUNTAS", "subscribe": "INSCREVA-SE"},
}
Rect = tuple[int, int, int, int]  # x0, y0, x1, y1


# ------------------------------------------------------------------ helpers

def ease_out_back(x: float) -> float:
    x = max(0.0, min(1.0, x))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def wrap_lines(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words, cur = para.split(), ""
        for w in words:
            test = f"{cur} {w}".strip()
            if draw.textlength(test, font=fnt) <= max_w or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def fit_text(text: str, box_w: int, box_h: int, max_size: int, min_size: int = 18, kind="heavy", spacing=1.18):
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    size = max_size
    while True:
        f = font(size, kind)
        lines = wrap_lines(d, text, f, box_w)
        lh = int(size * spacing)
        widest = max((d.textlength(l, font=f) for l in lines), default=0)
        if (len(lines) * lh <= box_h and widest <= box_w) or size <= min_size:
            return f, lines, lh
        size = max(min_size, int(size * 0.92))


def draw_text_block(img: Image.Image, rect: Rect, text: str, color, max_size: int, min_size=18,
                    kind="heavy", align="center", valign="center", shadow=None):
    x0, y0, x1, y1 = rect
    f, lines, lh = fit_text(text, x1 - x0, y1 - y0, max_size, min_size, kind)
    d = ImageDraw.Draw(img)
    total = len(lines) * lh
    y = y0 + ((y1 - y0 - total) // 2 if valign == "center" else 0)
    for line in lines:
        w = d.textlength(line, font=f)
        x = x0 + ((x1 - x0 - w) / 2 if align == "center" else 0)
        if shadow:
            d.text((x + 3, y + 4), line, font=f, fill=shadow)
        d.text((x, y), line, font=f, fill=color)
        y += lh


def rounded_tile(w: int, h: int, radius: int, fill, border=None, border_w=0, shadow=True) -> tuple[Image.Image, int]:
    """Devuelve (tile RGBA, margen) con una tarjeta redondeada y sombra suave."""
    m = int(max(w, h) * 0.06) + 10 if shadow else 0
    tile = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((m, m + m // 3, m + w, m + h + m // 3), radius, fill=(0, 0, 0, 90))
        tile = Image.alpha_composite(tile, sh.filter(ImageFilter.GaussianBlur(m / 2.5)))
    body = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    ImageDraw.Draw(body).rounded_rectangle((m, m, m + w, m + h), radius, fill=fill,
                                           outline=border, width=border_w)
    return Image.alpha_composite(tile, body), m


def paste_tile(base: Image.Image, tile: Image.Image, x: int, y: int, alpha: float = 1.0, scale: float = 1.0):
    if scale != 1.0:
        nw, nh = max(1, int(tile.width * scale)), max(1, int(tile.height * scale))
        cx, cy = x + tile.width / 2, y + tile.height / 2
        tile = tile.resize((nw, nh), Image.BILINEAR)
        x, y = int(cx - nw / 2), int(cy - nh / 2)
    if alpha < 1.0:
        a = tile.getchannel("A").point(lambda v: int(v * max(0.0, alpha)))
        tile = tile.copy()
        tile.putalpha(a)
    base.paste(tile, (int(x), int(y)), tile)


# ------------------------------------------------------------------ layout

@dataclass
class Layout:
    W: int
    H: int
    s: float
    pill: Rect
    timer_c: tuple[int, int]
    timer_r: int
    card: Rect
    image: Rect | None
    text: Rect
    options: list[Rect]
    bar: Rect


def make_layout(fmt: str, has_image: bool) -> Layout:
    if fmt == "9:16":
        W, H = 1080, 1920
        s = 1.0
        card = (60, 440, 1020, 920)
        options = []
        y = 990
        for _ in range(4):
            options.append((70, y, 1010, y + 160))
            y += 160 + 30
        pill = (W // 2 - 230, 90, W // 2 + 230, 180)
        timer_c, timer_r = (W // 2, 310), 100
        bar = (90, 1790, W - 90, 1812)
    else:
        W, H = 1920, 1080
        s = 1.0
        card = (80, 190, W - 80, 520)
        options = []
        ow = (W - 160 - 40) // 2
        for i in range(4):
            r, c = divmod(i, 2)
            x = 80 + c * (ow + 40)
            y = 565 + r * (185 + 30)
            options.append((x, y, x + ow, y + 185))
        pill = (80, 50, 520, 140)
        timer_c, timer_r = (W - 170, 100), 80
        bar = (80, 1030, W - 80, 1048)
    pad = 40
    if has_image:
        ch = card[3] - card[1] - 2 * pad
        image = (card[0] + pad, card[1] + pad, card[0] + pad + ch, card[3] - pad)
        text = (image[2] + pad, card[1] + pad, card[2] - pad, card[3] - pad)
    else:
        image = None
        text = (card[0] + pad + 10, card[1] + pad, card[2] - pad - 10, card[3] - pad)
    return Layout(W, H, s, pill, timer_c, timer_r, card, image, text, options, bar)


def video_size(fmt: str) -> tuple[int, int]:
    return (1080, 1920) if fmt == "9:16" else (1920, 1080)


# ------------------------------------------------------------------ renderer

class FrameRenderer:
    def __init__(self, project: Project, project_dir: Path):
        self.p = project
        self.dir = project_dir
        self.st = project.settings
        self.th = get_theme(self.st.theme)
        self.W, self.H = video_size(self.st.format)
        self.bg = self._background()
        self._cache: dict = {}
        self.lbl = LABELS.get(project.language, LABELS["es"])

    # -------- fondo
    def _background(self) -> Image.Image:
        W, H = self.W, self.H
        c = self.th["bg"]
        grad = Image.new("RGB", (1, 256))
        for y in range(256):
            t = y / 255
            col = lerp_color(c[0], c[1], t * 2) if t < 0.5 else lerp_color(c[1], c[2], (t - 0.5) * 2)
            grad.putpixel((0, y), col)
        img = grad.resize((W, H), Image.BICUBIC).rotate(0).convert("RGBA")
        # manchas de luz difuminadas
        blobs = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(blobs)
        bw, bh = blobs.size
        spots = [(0.12, 0.2, 0.35), (0.85, 0.75, 0.4), (0.6, 0.1, 0.25)]
        for (fx, fy, fr), col in zip(spots, self.th["blobs"]):
            r = int(fr * max(bw, bh))
            cx, cy = int(fx * bw), int(fy * bh)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        blobs = blobs.filter(ImageFilter.GaussianBlur(max(bw, bh) / 12)).resize((W, H), Image.BICUBIC)
        img = Image.alpha_composite(img, blobs)
        # signos de interrogación decorativos
        deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(deco)
        tc = self.th["text"]
        for fx, fy, size, rot in ((0.05, 0.62, 260, 15), (0.9, 0.32, 200, -12), (0.45, 0.93, 160, 8), (0.72, 0.02, 140, -20)):
            f = font(int(size * min(W, H) / 1080))
            layer = Image.new("RGBA", (int(size * 1.2), int(size * 1.4)), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((10, 0), "?", font=f, fill=(*tc[:3], 22))
            layer = layer.rotate(rot, expand=True, resample=Image.BICUBIC)
            deco.paste(layer, (int(fx * W), int(fy * H)), layer)
        img = Image.alpha_composite(img, deco)
        return img.convert("RGB")

    # -------- piezas cacheadas
    def _pill(self, text: str) -> tuple[Image.Image, int]:
        key = ("pill", text)
        if key not in self._cache:
            x0, y0, x1, y1 = make_layout(self.st.format, False).pill
            w, h = x1 - x0, y1 - y0
            tile, m = rounded_tile(w, h, h // 2, (*self.th["accent"], 255))
            draw_text_block(tile, (m + 20, m, m + w - 20, m + h), text, self.th.get("accent_text", (20, 20, 30)), int(h * 0.48))
            self._cache[key] = (tile, m)
        return self._cache[key]

    def _card(self, q: Question, lay: Layout, reveal: bool) -> tuple[Image.Image, int]:
        key = ("card", q.id, reveal, q.question, q.explanation, q.image)
        if key in self._cache:
            return self._cache[key]
        x0, y0, x1, y1 = lay.card
        w, h = x1 - x0, y1 - y0
        tile, m = rounded_tile(w, h, 36, self.th["card"])
        if lay.image and q.image:
            ip = self.dir / q.image
            if ip.exists():
                ix0, iy0, ix1, iy1 = lay.image
                im = ImageOps.fit(Image.open(ip).convert("RGB"), (ix1 - ix0, iy1 - iy0), Image.LANCZOS)
                mask = Image.new("L", im.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, *im.size), 24, fill=255)
                tile.paste(im, (ix0 - x0 + m, iy0 - y0 + m), mask)
        tx0, ty0, tx1, ty1 = lay.text
        tr = (tx0 - x0 + m, ty0 - y0 + m, tx1 - x0 + m, ty1 - y0 + m)
        big = 78 if self.st.format == "16:9" else 70
        if reveal and self.st.show_explanation and q.explanation.strip():
            split = tr[1] + int((tr[3] - tr[1]) * 0.5)
            draw_text_block(tile, (tr[0], tr[1], tr[2], split - 10), q.question, self.th["card_text"], int(big * 0.7))
            d = ImageDraw.Draw(tile)
            d.line((tr[0] + 40, split, tr[2] - 40, split), fill=(*self.th["correct"], 255), width=4)
            draw_text_block(tile, (tr[0], split + 14, tr[2], tr[3]), q.explanation, self.th["correct"],
                            int(big * 0.55), kind="bold")
        else:
            draw_text_block(tile, tr, q.question, self.th["card_text"], big)
        self._cache[key] = (tile, m)
        return tile, m

    def _option(self, q: Question, i: int, lay: Layout, state: str) -> tuple[Image.Image, int]:
        """state: normal | correct | wrong"""
        key = ("opt", q.id, i, state, q.options[i] if i < len(q.options) else "")
        if key in self._cache:
            return self._cache[key]
        x0, y0, x1, y1 = lay.options[i]
        w, h = x1 - x0, y1 - y0
        th = self.th
        if state == "correct":
            fill, border, tcol = (*th["correct"], 255), (255, 255, 255, 255), (255, 255, 255)
        elif state == "wrong":
            fill, border, tcol = th["wrong"], None, (*th["option_text"][:3], 110)
        else:
            fill, border, tcol = th["option"], th["option_border"], th["option_text"]
        tile, m = rounded_tile(w, h, h // 3, fill, border, 4 if border else 0)
        d = ImageDraw.Draw(tile)
        br = int(h * 0.3)
        bx, by = m + 24 + br, m + h // 2
        bcol = (255, 255, 255) if state == "correct" else th["badge"][i % 4]
        if state == "wrong":
            bcol = (*bcol, 110)
        d.ellipse((bx - br, by - br, bx + br, by + br), fill=bcol)
        lf = font(int(br * 1.1))
        letter_col = th["correct"] if state == "correct" else (255, 255, 255)
        if state == "correct":
            # marca de verificación
            d.line((bx - br * 0.45, by, bx - br * 0.1, by + br * 0.38, bx + br * 0.5, by - br * 0.4),
                   fill=letter_col, width=max(6, br // 5), joint="curve")
        else:
            lw = d.textlength(LETTERS[i], font=lf)
            d.text((bx - lw / 2, by - br * 0.62), LETTERS[i], font=lf, fill=letter_col)
        text = q.options[i] if i < len(q.options) else ""
        draw_text_block(tile, (bx + br + 24, m + 10, m + w - 28, m + h - 10), text, tcol,
                        int(h * 0.3), kind="bold", align="left")
        self._cache[key] = (tile, m)
        return tile, m

    def _timer(self, lay: Layout, frac: float, number: str) -> Image.Image:
        r = lay.timer_r
        ss = 2
        size = (r * 2 + 20) * ss
        tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        c = size // 2
        R = r * ss
        d.ellipse((c - R, c - R, c + R, c + R), fill=(0, 0, 0, 110))
        wdt = int(R * 0.18)
        d.ellipse((c - R, c - R, c + R, c + R), outline=(255, 255, 255, 60), width=wdt)
        col = lerp_color((34, 197, 94), (239, 68, 68), 1 - frac) if frac < 0.999 else (34, 197, 94)
        if frac > 0:
            d.arc((c - R, c - R, c + R, c + R), -90, -90 + 360 * frac, fill=(*col, 255), width=wdt)
        f = font(int(R * 0.95))
        tw = d.textlength(number, font=f)
        bb = d.textbbox((0, 0), number, font=f)
        d.text((c - tw / 2, c - (bb[3] + bb[1]) / 2), number, font=f, fill=(255, 255, 255, 255))
        return tile.resize((size // ss, size // ss), Image.LANCZOS)

    def _bar(self, img: Image.Image, lay: Layout, frac: float):
        x0, y0, x1, y1 = lay.bar
        d = ImageDraw.Draw(img)
        h = y1 - y0
        d.rounded_rectangle(lay.bar, h // 2, fill=(15, 15, 25))
        if frac > 0:
            xe = x0 + int((x1 - x0) * frac)
            col = lerp_color((34, 197, 94), (239, 68, 68), 1 - frac)
            d.rounded_rectangle((x0, y0, max(xe, x0 + h), y1), h // 2, fill=col)

    # -------- escenas
    def question_frame(self, qi: int, phase: str, t: float, frac: float = 1.0, number: str = "",
                       fade: float = 1.0) -> Image.Image:
        """phase: ask (t = segundos desde el inicio) | think | reveal (t = segundos desde el reveal)."""
        q = self.p.questions[qi]
        lay = make_layout(self.st.format, bool(q.image))
        img = self.bg.copy()
        n = len(self.p.questions)
        pill, pm = self._pill(f"{self.lbl['pill']} {qi + 1} / {n}")
        paste_tile(img, pill, lay.pill[0] - pm, lay.pill[1] - pm)

        a_card = ease_out_back(t / 0.45) if phase == "ask" else 1.0
        card, cm = self._card(q, lay, reveal=(phase == "reveal"))
        cy = lay.card[1] - cm + int((1 - a_card) * -120)
        paste_tile(img, card, lay.card[0] - cm, cy, alpha=min(1.0, t / 0.25) if phase == "ask" else 1.0)

        for i in range(min(4, len(q.options))):
            if phase == "reveal":
                state = "correct" if i == q.correct else "wrong"
                tile, om = self._option(q, i, lay, state)
                scale = 1.0
                if state == "correct":
                    k = t / 0.35
                    scale = 1.0 + 0.08 * math.sin(math.pi * min(1.0, k)) if k < 1 else 1.0
                paste_tile(img, tile, lay.options[i][0] - om, lay.options[i][1] - om, scale=scale)
            else:
                tile, om = self._option(q, i, lay, "normal")
                if phase == "ask":
                    k = (t - 0.3 - i * 0.12) / 0.35
                    if k <= 0:
                        continue
                    dx = int((1 - ease_out(k)) * 80) * (-1 if i % 2 == 0 else 1)
                    paste_tile(img, tile, lay.options[i][0] - om + dx, lay.options[i][1] - om,
                               alpha=min(1.0, k), scale=0.9 + 0.1 * ease_out(k))
                else:
                    paste_tile(img, tile, lay.options[i][0] - om, lay.options[i][1] - om)

        if phase in ("ask", "think"):
            timer = self._timer(lay, frac, number or str(self.st.think_seconds))
            img.paste(timer, (lay.timer_c[0] - timer.width // 2, lay.timer_c[1] - timer.height // 2), timer)
            self._bar(img, lay, frac)
        if fade < 1.0:
            img = Image.blend(self.bg, img, max(0.0, fade))
        return img

    def _title_tiles(self, title: str, subtitle: str, cta: bool):
        key = ("title", title, subtitle, cta)
        if key in self._cache:
            return self._cache[key]
        W, H = self.W, self.H
        vertical = self.st.format == "9:16"
        cw, ch = (int(W * 0.86), int(H * 0.36)) if vertical else (int(W * 0.78), int(H * 0.52))
        card, m = rounded_tile(cw, ch, 44, self.th["card"])
        bw = int(cw * 0.36)
        badge, bm = rounded_tile(bw, 90, 45, (*self.th["accent"], 255))
        draw_text_block(badge, (bm + 20, bm, bm + bw - 20, bm + 90), "QUIZ" if not cta else self.lbl["thanks"],
                        self.th.get("accent_text", (20, 20, 30)), 56)
        draw_text_block(card, (m + 60, m + 70, m + cw - 60, m + ch - 150), title, self.th["card_text"],
                        110 if not vertical else 96)
        draw_text_block(card, (m + 60, m + ch - 140, m + cw - 60, m + ch - 40), subtitle,
                        self.th["card_text"], 46, kind="bold")
        btn, btm = rounded_tile(560, 120, 24, (230, 33, 23, 255))
        draw_text_block(btn, (btm, btm, btm + 560, btm + 120), self.lbl["subscribe"], (255, 255, 255), 58)
        self._cache[key] = (card, m, cw, ch, badge, bm, btn)
        return self._cache[key]

    def title_frame(self, title: str, subtitle: str, t: float, fade: float = 1.0, cta: bool = False) -> Image.Image:
        img = self.bg.copy()
        W, H = self.W, self.H
        card, m, cw, ch, badge, bm, btn = self._title_tiles(title, subtitle, cta)
        k = ease_out_back(t / 0.6)
        x, y = (W - cw) // 2 - m, (H - ch) // 2 - m
        paste_tile(img, card, x, y, alpha=min(1.0, t / 0.3), scale=0.6 + 0.4 * k)
        if t > 0.35:
            kb = ease_out_back((t - 0.35) / 0.4)
            paste_tile(img, badge, (W - badge.width) // 2, y + m - 45 - bm, scale=max(0.01, kb))
        if cta and t > 0.6:
            ks = ease_out_back((t - 0.6) / 0.5)
            pulse = 1 + 0.04 * math.sin(t * 5)
            paste_tile(img, btn, (W - btn.width) // 2, y + ch + m + 40, scale=max(0.01, ks * pulse))
        if fade < 1.0:
            img = Image.blend(self.bg, img, max(0.0, fade))
        return img


def thumbnail(project: Project, project_dir: Path, out: Path) -> Path:
    """Miniatura 1280x720 para YouTube."""
    p = project.model_copy(deep=True)
    p.settings.format = "16:9"
    r = FrameRenderer(p, project_dir)
    img = r.bg.copy().convert("RGBA")
    W, H = img.size
    th = r.th
    # gran signo de interrogación
    q = Image.new("RGBA", (700, 900), (0, 0, 0, 0))
    ImageDraw.Draw(q).text((40, 0), "?", font=font(820), fill=(*th["accent"], 255), stroke_width=18,
                           stroke_fill=(20, 20, 30))
    q = q.rotate(-10, expand=True, resample=Image.BICUBIC)
    img.paste(q, (W - q.width + 40, H - q.height + 60), q)
    badge, bm = rounded_tile(520, 120, 60, (230, 33, 23, 255))
    n = len(project.questions)
    draw_text_block(badge, (bm + 36, bm, bm + 484, bm + 120), f"{n} {r.lbl['questions']}" if n else "QUIZ", (255, 255, 255), 58)
    paste_tile(img, badge, 90 - bm, 90 - bm)
    title = (project.title or project.topic or "QUIZ").upper()
    draw_text_block(img, (100, 260, int(W * 0.66), H - 80), title, (255, 255, 255), 170, 60, align="left",
                    shadow=(0, 0, 0))
    img.convert("RGB").resize((1280, 720), Image.LANCZOS).save(out, "JPEG", quality=92)
    return out
