"""Visual design primitives shared by every scene layout."""

from __future__ import annotations

import math
import os
import random
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Design canvas. All layout coordinates are authored at 1280x720 and scaled to
# the configured output size at draw time.
DESIGN_WIDTH = 1280
DESIGN_HEIGHT = 720

BACKGROUND_START = "#050D1F"
BACKGROUND_END = "#0B2B52"
PRIMARY = "#4CC9F0"
TEXT = "#F8FAFC"
MUTED = "#A9B7CC"
ACID = "#F94144"
ACID_ORANGE = "#F3722C"
NEUTRAL = "#90BE6D"
BASE = "#5B8DEF"
PURPLE = "#7B61FF"
ELECTRON = "#FFD166"
CARD = "#0D2444"
CARD_LIGHT = "#123157"
BORDER = "#21466F"
DARK_BORDER = "#18365A"
BLACK = "#000000"

PH_STOPS: tuple[tuple[float, str], ...] = (
    (0, "#F94144"),
    (3, "#F3722C"),
    (5, "#F9C74F"),
    (7, "#90BE6D"),
    (9, "#43AA8B"),
    (11, "#4CC9F0"),
    (14, "#7B61FF"),
)


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(color_a: str, color_b: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    a = hex_rgb(color_a)
    b = hex_rgb(color_b)
    return "#{:02X}{:02X}{:02X}".format(*(int(a[i] + (b[i] - a[i]) * amount) for i in range(3)))


def ph_color(ph: float) -> str:
    ph = max(0.0, min(14.0, ph))
    for index in range(len(PH_STOPS) - 1):
        start_ph, start_color = PH_STOPS[index]
        end_ph, end_color = PH_STOPS[index + 1]
        if start_ph <= ph <= end_ph:
            span = end_ph - start_ph
            amount = (ph - start_ph) / span if span else 0.0
            return mix(start_color, end_color, amount)
    return PH_STOPS[-1][1]


class FontManager:
    def __init__(self, assets_dir: Path) -> None:
        self.assets_dir = Path(assets_dir)
        self._cache: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}

    def _candidates(self, bold: bool) -> list[Path]:
        names = (
            [
                "DejaVuSans-Bold.ttf",
                "Inter-Bold.ttf",
                "Roboto-Bold.ttf",
                "Montserrat-Bold.ttf",
            ]
            if bold
            else [
                "DejaVuSans.ttf",
                "Inter-Regular.ttf",
                "Roboto-Regular.ttf",
                "Montserrat-Regular.ttf",
            ]
        )
        candidates = [self.assets_dir / "fonts" / name for name in names]
        system_root = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        if sys.platform == "win32":
            candidates.extend(
                [
                    system_root / "Fonts" / ("segoeuib.ttf" if bold else "segoeui.ttf"),
                    system_root / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf"),
                    system_root / "Fonts" / ("calibrib.ttf" if bold else "calibri.ttf"),
                ]
            )
        candidates.extend(
            [
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
                if bold
                else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")
                if bold
                else Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            ]
        )
        return candidates

    def get(self, size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        size = max(8, int(size))
        key = (size, bold)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        for path in self._candidates(bold):
            if path.is_file():
                try:
                    font = ImageFont.truetype(str(path), size=size)
                    self._cache[key] = font
                    return font
                except OSError:
                    continue
        try:
            font = cast(ImageFont.FreeTypeFont, ImageFont.load_default(size=size))
        except TypeError:  # Pillow < 10.1
            font = cast(ImageFont.FreeTypeFont, ImageFont.load_default())
        self._cache[key] = font
        return font


class Canvas:
    def __init__(self, image: Image.Image, fonts: FontManager) -> None:
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.fonts = fonts
        self.width, self.height = image.size
        self.sx = self.width / DESIGN_WIDTH
        self.sy = self.height / DESIGN_HEIGHT
        self.scale = min(self.sx, self.sy)

    def x(self, value: float) -> float:
        return value * self.sx

    def y(self, value: float) -> float:
        return value * self.sy

    def r(self, value: float) -> float:
        return value * self.scale

    def font(self, size: float, bold: bool = True) -> ImageFont.FreeTypeFont:
        return self.fonts.get(int(round(size * self.scale)), bold=bold)

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: float,
        color: str = TEXT,
        *,
        anchor: str = "la",
        bold: bool = True,
    ) -> None:
        self.draw.text(
            (self.x(x), self.y(y)),
            value,
            font=self.font(size, bold),
            fill=color,
            anchor=anchor,
        )

    def measure(self, value: str, size: float, bold: bool = True) -> tuple[float, float]:
        font = self.font(size, bold)
        left, top, right, bottom = self.draw.textbbox((0, 0), value, font=font)
        return (right - left) / self.scale, (bottom - top) / self.scale

    def wrap(
        self,
        value: str,
        size: float,
        max_width: float,
        *,
        bold: bool = True,
    ) -> list[str]:
        font = self.font(size, bold)
        max_px = self.x(max_width)
        words = value.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if self.draw.textlength(candidate, font=font) <= max_px:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def wrapped_text(
        self,
        x: float,
        y: float,
        value: str,
        size: float,
        max_width: float,
        color: str = TEXT,
        *,
        anchor: str = "la",
        bold: bool = True,
        max_lines: int | None = None,
        line_height: float = 1.22,
    ) -> list[str]:
        lines = self.wrap(value, size, max_width, bold=bold)
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and self.measure(last + "…", size, bold)[0] > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
        px = self.x(x)
        py = self.y(y)
        step = size * self.scale * line_height
        for index, line in enumerate(lines):
            self.draw.text(
                (px, py + index * step),
                line,
                font=self.font(size, bold),
                fill=color,
                anchor=anchor,
            )
        return lines

    def panel(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        fill: str = CARD,
        outline: str | None = BORDER,
        radius: float = 24,
        width: float = 2,
    ) -> None:
        self.draw.rounded_rectangle(
            [self.x(x1), self.y(y1), self.x(x2), self.y(y2)],
            radius=self.r(radius),
            fill=fill,
            outline=outline,
            width=max(1, int(self.r(width))),
        )

    def pill_size(
        self,
        value: str,
        size: float = 20,
        *,
        pad_x: float = 18,
        pad_y: float = 9,
    ) -> tuple[float, float]:
        width, height = self.measure(value, size)
        return width + pad_x * 2, max(height + pad_y * 2, size * 1.9)

    def pill(
        self,
        x: float,
        y: float,
        value: str,
        size: float = 20,
        *,
        fill: str = CARD_LIGHT,
        outline: str = PRIMARY,
        text_color: str = TEXT,
        pad_x: float = 18,
        pad_y: float = 9,
    ) -> tuple[float, float]:
        width, height = self.pill_size(value, size, pad_x=pad_x, pad_y=pad_y)
        self.draw.rounded_rectangle(
            [self.x(x), self.y(y), self.x(x + width), self.y(y + height)],
            radius=self.r(height / 2),
            fill=fill,
            outline=outline,
            width=max(1, int(self.r(1.6))),
        )
        self.text(
            x + width / 2,
            y + height / 2,
            value,
            size,
            text_color,
            anchor="mm",
        )
        return width, height

    def circle(
        self,
        cx: float,
        cy: float,
        radius: float,
        *,
        fill: str,
        outline: str | None = None,
        width: float = 2,
    ) -> None:
        self.draw.ellipse(
            [
                self.x(cx - radius),
                self.y(cy - radius),
                self.x(cx + radius),
                self.y(cy + radius),
            ],
            fill=fill,
            outline=outline,
            width=max(1, int(self.r(width))),
        )

    def ring(
        self,
        cx: float,
        cy: float,
        radius: float,
        *,
        color: str,
        width: float = 2,
        start: float = 0,
        end: float = 360,
    ) -> None:
        box = [
            self.x(cx - radius),
            self.y(cy - radius),
            self.x(cx + radius),
            self.y(cy + radius),
        ]
        if start == 0 and end == 360:
            self.draw.ellipse(box, outline=color, width=max(1, int(self.r(width))))
        else:
            self.draw.arc(
                box,
                start=start,
                end=end,
                fill=color,
                width=max(1, int(self.r(width))),
            )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
        *,
        width: float = 3,
    ) -> None:
        self.draw.line(
            [self.x(x1), self.y(y1), self.x(x2), self.y(y2)],
            fill=color,
            width=max(1, int(self.r(width))),
        )

    def dashed_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
        *,
        width: float = 2,
        dash: float = 12,
        gap: float = 10,
    ) -> None:
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 0:
            return
        steps = max(1, int(length / (dash + gap)))
        for index in range(steps + 1):
            start_fraction = min(1.0, (index * (dash + gap)) / length)
            end_fraction = min(1.0, start_fraction + dash / length)
            self.line(
                x1 + (x2 - x1) * start_fraction,
                y1 + (y2 - y1) * start_fraction,
                x1 + (x2 - x1) * end_fraction,
                y1 + (y2 - y1) * end_fraction,
                color,
                width=width,
            )

    def arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
        *,
        width: float = 4,
        head: float = 14,
        progress: float = 1.0,
    ) -> None:
        progress = max(0.0, min(1.0, progress))
        if progress <= 0:
            return
        ex = x1 + (x2 - x1) * progress
        ey = y1 + (y2 - y1) * progress
        angle = math.atan2(ey - y1, ex - x1)
        self.line(x1, y1, ex, ey, color, width=width)
        if progress >= 0.99:
            left = (
                ex - head * math.cos(angle - math.pi / 6),
                ey - head * math.sin(angle - math.pi / 6),
            )
            right = (
                ex - head * math.cos(angle + math.pi / 6),
                ey - head * math.sin(angle + math.pi / 6),
            )
            self.draw.polygon(
                [
                    (self.x(ex), self.y(ey)),
                    (self.x(left[0]), self.y(left[1])),
                    (self.x(right[0]), self.y(right[1])),
                ],
                fill=color,
            )

    def check(self, cx: float, cy: float, radius: float, color: str) -> None:
        self.line(cx - radius * 0.5, cy, cx - radius * 0.1, cy + radius * 0.4, color, width=4)
        self.line(
            cx - radius * 0.1,
            cy + radius * 0.4,
            cx + radius * 0.6,
            cy - radius * 0.4,
            color,
            width=4,
        )


def ease_out(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1.0 - (1.0 - value) ** 3


def build_background(width: int, height: int) -> Image.Image:
    """Create the dark blue gradient, glows and particles once per video."""
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    top = hex_rgb(BACKGROUND_START)
    bottom = hex_rgb(BACKGROUND_END)
    for y in range(height):
        amount = y / max(1, height - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * amount) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        [width * 0.58, -height * 0.55, width * 1.2, height * 0.55],
        fill=(76, 201, 240, 34),
    )
    glow_draw.ellipse(
        [-width * 0.3, height * 0.45, width * 0.45, height * 1.35],
        fill=(123, 97, 255, 26),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(24, int(height * 0.14))))
    image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")

    particles = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    particle_draw = ImageDraw.Draw(particles)
    rng = random.Random(20261030)
    for _ in range(42):
        px = rng.uniform(0.03, 0.97) * width
        py = rng.uniform(0.08, 0.88) * height
        radius = rng.uniform(0.7, 2.1) * (height / DESIGN_HEIGHT)
        alpha = rng.randint(18, 70)
        particle_draw.ellipse(
            [px - radius, py - radius, px + radius, py + radius],
            fill=(140, 205, 255, alpha),
        )
    return Image.alpha_composite(image.convert("RGBA"), particles).convert("RGB")


def draw_header(
    canvas: Canvas,
    concept_title: str,
    scene_index: int,
    total_scenes: int,
) -> None:
    canvas.draw.rectangle(
        [canvas.x(70), canvas.y(32), canvas.x(118), canvas.y(36)],
        fill=PRIMARY,
    )
    canvas.text(70, 46, concept_title, 21, MUTED, anchor="la", bold=True)
    canvas.line(70, 92, 1210, 92, DARK_BORDER, width=1)
    label = f"{scene_index:02d} / {total_scenes:02d}"
    canvas.text(1210, 46, label, 18, MUTED, anchor="ra", bold=True)

    dot_radius = 4.0
    gap = 17.0
    total_width = (total_scenes - 1) * gap
    start_x = 1210 - 80 - total_width
    for index in range(total_scenes):
        color = PRIMARY if index < scene_index else "#1E3A5F"
        canvas.circle(
            start_x + index * gap,
            58,
            dot_radius if index < scene_index else dot_radius - 0.6,
            fill=color,
        )


def draw_heading(canvas: Canvas, heading: str, accent: str = PRIMARY) -> None:
    canvas.draw.rectangle(
        [canvas.x(70), canvas.y(112), canvas.x(76), canvas.y(158)],
        fill=accent,
    )
    canvas.text(92, 116, heading, 34, TEXT, anchor="la", bold=True)


def draw_label_row(
    canvas: Canvas,
    labels: Iterable[str],
    *,
    center_x: float = 640,
    y: float = 535,
    size: float = 20,
    outline: str = PRIMARY,
    max_width: float = 1080,
) -> None:
    values = [label for label in labels if label.strip()]
    if not values:
        return
    while size > 14:
        widths = [canvas.pill_size(value, size)[0] for value in values]
        total = sum(widths) + 14 * (len(values) - 1)
        if total <= max_width:
            break
        size -= 1
    widths = [canvas.pill_size(value, size)[0] for value in values]
    total = sum(widths) + 14 * (len(values) - 1)
    x = center_x - total / 2
    for value, width in zip(values, widths, strict=True):
        canvas.pill(x, y, value, size, outline=outline)
        x += width + 14


def draw_caption(canvas: Canvas, caption: str) -> None:
    canvas.panel(48, 590, 1232, 703, fill="#0A1C35", outline=DARK_BORDER, radius=20)
    canvas.panel(64, 606, 72, 687, fill=PRIMARY, outline=PRIMARY, radius=4)
    chosen_size = 27.0
    for candidate in (27.0, 25.0, 23.0, 21.0, 19.0):
        lines = canvas.wrap(caption, candidate, 1088)
        if len(lines) <= 3:
            chosen_size = candidate
            break
    canvas.wrapped_text(
        92,
        606,
        caption,
        chosen_size,
        1088,
        TEXT,
        bold=False,
        max_lines=3,
        line_height=1.24,
    )


def draw_ph_scale(
    canvas: Canvas,
    x1: float,
    x2: float,
    y: float,
    *,
    progress: float = 1.0,
    number_size: float = 18,
    track_height: float = 16,
    show_numbers: bool = True,
) -> None:
    progress = max(0.0, min(1.0, progress))
    visible_end = x1 + (x2 - x1) * progress
    segments = 160
    for index in range(segments):
        start = x1 + (x2 - x1) * index / segments
        if start > visible_end:
            break
        end = min(visible_end, x1 + (x2 - x1) * (index + 1) / segments + 0.8)
        color = ph_color((start - x1) / max(1, x2 - x1) * 14)
        canvas.line(start, y, end, y, color, width=track_height)
    canvas.circle(x1, y, track_height / 2, fill=ph_color(0))
    canvas.circle(
        visible_end, y, track_height / 2, fill=ph_color((visible_end - x1) / max(1, x2 - x1) * 14)
    )
    if show_numbers:
        for value in range(15):
            amount = value / 14
            if amount > progress + 0.01:
                continue
            x = x1 + (x2 - x1) * amount
            canvas.text(x, y + 26, str(value), number_size, MUTED, anchor="ma", bold=True)


def draw_mini_scale(canvas: Canvas, center_x: float, y: float, width: float = 520) -> None:
    draw_ph_scale(
        canvas,
        center_x - width / 2,
        center_x + width / 2,
        y,
        number_size=13,
        track_height=10,
        show_numbers=False,
    )
    canvas.text(center_x - width / 2, y + 18, "0", 14, MUTED, anchor="ma")
    canvas.text(center_x, y + 18, "7", 14, NEUTRAL, anchor="ma")
    canvas.text(center_x + width / 2, y + 18, "14", 14, MUTED, anchor="ma")


def draw_atom(
    canvas: Canvas,
    cx: float,
    cy: float,
    radius: float,
    *,
    symbol: str,
    color: str,
    electron_color: str = ELECTRON,
    electrons: int = 4,
    highlight_outer: bool = False,
    progress: float = 1.0,
    label: str | None = None,
) -> None:
    progress = ease_out(progress)
    canvas.circle(cx, cy, radius, fill=mix(color, "#000000", 0.55), outline=color, width=3)
    inner = radius * 0.42
    canvas.circle(cx, cy, inner, fill=color)
    canvas.text(cx, cy + 1, symbol, max(18, radius * 0.52), "#07152A", anchor="mm", bold=True)

    orbit = radius * 0.78
    canvas.ring(cx, cy, orbit, color=mix(color, "#FFFFFF", 0.18), width=2)
    if highlight_outer:
        canvas.ring(cx, cy, orbit + 6, color=PRIMARY, width=2)

    count = max(1, electrons)
    for index in range(count):
        angle = (2 * math.pi * index / count) + progress * math.pi * 0.35
        ex = cx + orbit * math.cos(angle)
        ey = cy + orbit * math.sin(angle)
        canvas.circle(ex, ey, max(5.0, radius * 0.075), fill=electron_color, outline="#FFF3C4")
    if label:
        canvas.text(cx, cy + radius + 20, label, 19, MUTED, anchor="ma")


def draw_shared_pair(
    canvas: Canvas,
    cx: float,
    cy: float,
    *,
    spread: float = 17,
    progress: float = 1.0,
    color: str = ELECTRON,
) -> None:
    progress = ease_out(progress)
    canvas.dashed_line(
        cx - spread * 2.2,
        cy,
        cx + spread * 2.2,
        cy,
        mix(color, "#FFFFFF", 0.1),
        width=2,
        dash=8,
        gap=7,
    )
    for direction in (-1, 1):
        x = cx + direction * spread * progress
        canvas.circle(x, cy, 9, fill=color, outline="#FFF3C4", width=2)


def draw_arrow_pair(
    canvas: Canvas,
    left_x: float,
    right_x: float,
    y: float,
    *,
    color: str = PRIMARY,
    progress: float = 1.0,
) -> None:
    draw_left = ease_out(min(1.0, progress * 1.6))
    draw_right = ease_out(max(0.0, min(1.0, progress * 1.6 - 0.4)))
    canvas.arrow(left_x + 62, y, right_x - 62, y, color, width=3, head=11, progress=draw_left)
    canvas.arrow(
        right_x - 62, y + 26, left_x + 62, y + 26, color, width=3, head=11, progress=draw_right
    )
